from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.config import settings
from app.database import audit_logs, database_health, machines, readings, users
from app.security import require_admin
from app.services.analytics import dataset_stats
from app.services.audit import audit
from app.utils import SENSOR_ORDER, utcnow
from app.web import render

router = APIRouter()
PAGE_SIZE = 25
STARTED_AT = utcnow()
DATASET_FILES = {
    "sensor_readings.csv": ("text/csv", settings.dataset_readings_csv),
    "fault_scenarios.csv": ("text/csv", settings.dataset_scenarios_csv),
    "DATASET.md": ("text/markdown", settings.dataset_metadata),
}


def _page_window(current: int, total: int) -> list[int | None]:
    if total <= 7:
        return list(range(1, total + 1))
    pages = {1, total, current}
    for delta in (-1, 1):
        pages.add(max(1, min(total, current + delta)))
    ordered = sorted(pages)
    result: list[int | None] = []
    previous = 0
    for page in ordered:
        if previous and page - previous > 1:
            result.append(None)
        result.append(page)
        previous = page
    return result


def _masked_key() -> str:
    key = settings.ingest_api_key
    if len(key) <= 8:
        return "•" * 12
    return f"{key[:3]}{'•' * 10}{key[-2:]}"


def _uptime() -> str:
    seconds = int((utcnow() - STARTED_AT).total_seconds())
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days} hari {hours} jam"
    return f"{hours} jam {minutes} menit {secs} detik"


def _file_info(path: Path) -> dict:
    if not path.exists():
        return {"name": path.name, "exists": False, "size": 0, "modified": None}
    stat = path.stat()
    return {
        "name": path.name,
        "exists": True,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    }


@router.get("/admin/audit")
def audit_page(
    request: Request,
    q: str = Query("", max_length=100),
    entity: str = Query("", max_length=40),
    page: int = Query(1, ge=1, le=10000),
):
    current = require_admin(request)
    query: dict = {}
    if entity:
        query["entity"] = entity
    needle = q.strip()
    if needle:
        pattern = {"$regex": re.escape(needle), "$options": "i"}
        query["$or"] = [
            {"action": pattern},
            {"actor_name": pattern},
            {"detail": pattern},
            {"entity_id": pattern},
        ]
    total = audit_logs().count_documents(query)
    pages = max(math.ceil(total / PAGE_SIZE), 1)
    page = min(page, pages)
    docs = list(
        audit_logs()
        .find(query)
        .sort("ts", -1)
        .skip((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    for doc in docs:
        doc["id"] = str(doc.pop("_id"))
    since = utcnow() - timedelta(hours=24)
    summary = {
        "total": audit_logs().count_documents({}),
        "today": audit_logs().count_documents({"ts": {"$gte": since}}),
        "user_actions": audit_logs().count_documents({"ts": {"$gte": since}, "actor_role": {"$ne": "system"}}),
        "system_actions": audit_logs().count_documents({"ts": {"$gte": since}, "actor_role": "system"}),
    }
    entities = sorted(audit_logs().distinct("entity"))
    params = {key: value for key, value in {"q": needle, "entity": entity}.items() if value}
    base_qs = urlencode(params)
    return render(
        request,
        "admin/audit.html",
        user=current,
        active_page="audit",
        items=docs,
        summary=summary,
        filters={"q": needle, "entity": entity},
        entities=entities,
        pagination={
            "page": page,
            "pages": pages,
            "total": total,
            "numbers": _page_window(page, pages),
        },
        page_prefix="?" + base_qs + "&" if base_qs else "?",
    )


@router.get("/integration")
def integration_page(request: Request):
    current = require_admin(request)
    stats = dataset_stats()
    latest_reading = stats.pop("latest_reading", None)
    file_info = [_file_info(path) for _, (_, path) in DATASET_FILES.items()]
    sensor_summary = []
    latest = latest_reading or {}
    for sensor in SENSOR_ORDER:
        sensor_summary.append({"sensor": sensor, "value": latest.get(sensor)})
    total_readings = stats["readings"] or 1
    sample_rows = list(
        readings()
        .find({}, {"_id": 0})
        .sort("ts", -1)
        .limit(8)
    )
    machine_map = {doc["_id"]: doc.get("code") for doc in machines().find({}, {"code": 1})}
    for row in sample_rows:
        row["machine_code"] = machine_map.get(row.get("machine_id"), "—")
    return render(
        request,
        "admin/integration.html",
        user=current,
        active_page="integration",
        stats=stats,
        latest_reading=latest_reading,
        file_info=file_info,
        api_key_masked=_masked_key(),
        api_key_length=len(settings.ingest_api_key),
        base_url=str(request.base_url).rstrip("/"),
        health=database_health(),
        uptime=_uptime(),
        started_at=STARTED_AT,
        sample_rows=sample_rows,
        sensor_summary=sensor_summary,
        total_readings=total_readings,
        collections_ok=True,
        active_machines=machines().count_documents({"active": True}),
        active_users=users().count_documents({"active": True}),
    )


@router.get("/integration/dataset/{name}")
def integration_dataset(request: Request, name: str):
    current = require_admin(request)
    if name not in DATASET_FILES:
        raise HTTPException(status_code=404, detail="Berkas dataset tidak tersedia.")
    media_type, path = DATASET_FILES[name]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Berkas dataset belum dibuat. Jalankan seed terlebih dahulu.")
    audit(current, "Mengunduh dataset", "dataset", name, f"Berkas {name} diunduh.", request)
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )
