from __future__ import annotations

import math
import re
from datetime import timedelta
from urllib.parse import urlencode

from bson import ObjectId
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.database import alerts, machines, thresholds, users, work_orders
from app.security import check_csrf, flash, is_admin, require_user
from app.services.audit import audit
from app.services.notifications import notify_user
from app.services.thresholds import ACTIONS
from app.services.work_orders import create_work_order, open_for_sensor
from app.utils import ALERT_LEVEL, SENSOR_ORDER, SENSORS, utcnow
from app.web import render

router = APIRouter()
PAGE_SIZE = 15


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


def _summary() -> dict:
    active = {"status": {"$in": ["open", "acknowledged"]}}
    return {
        "active": alerts().count_documents(active),
        "critical": alerts().count_documents({**active, "level": "critical"}),
        "acknowledged": alerts().count_documents({"status": "acknowledged"}),
        "resolved_24h": alerts().count_documents(
            {"status": "resolved", "resolved_at": {"$gte": utcnow() - timedelta(hours=24)}}
        ),
    }


def _alert_or_404(alert_id: str) -> dict:
    try:
        alert = alerts().find_one({"_id": ObjectId(alert_id)})
    except Exception:
        alert = None
    if not alert:
        raise HTTPException(status_code=404, detail="Alert tidak ditemukan.")
    return alert


@router.get("/alerts")
def alerts_page(
    request: Request,
    status: str = Query("active", max_length=20),
    level: str = Query("", max_length=20),
    sensor: str = Query("", max_length=20),
    machine: str = Query("", max_length=40),
    q: str = Query("", max_length=80),
    page: int = Query(1, ge=1, le=10000),
):
    user = require_user(request)
    query: dict = {}
    if status == "active":
        query["status"] = {"$in": ["open", "acknowledged"]}
    elif status in {"open", "acknowledged", "resolved"}:
        query["status"] = status
    if level in ALERT_LEVEL:
        query["level"] = level
    if sensor in SENSORS:
        query["sensor"] = sensor
    if machine:
        query["machine_code"] = machine
    needle = q.strip()
    if needle:
        pattern = {"$regex": re.escape(needle), "$options": "i"}
        query["$or"] = [
            {"message": pattern},
            {"machine_code": pattern},
            {"machine_name": pattern},
        ]
    total = alerts().count_documents(query)
    pages = max(math.ceil(total / PAGE_SIZE), 1)
    page = min(page, pages)
    ordering = [("resolved_at", -1)] if status == "resolved" else [("last_seen", -1)]
    docs = list(
        alerts().find(query).sort(ordering).skip((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    )
    items = []
    for doc in docs:
        item = dict(doc)
        item["id"] = str(item.pop("_id"))
        items.append(item)
    params = {
        key: value
        for key, value in {
            "status": status,
            "level": level,
            "sensor": sensor,
            "machine": machine,
            "q": needle,
        }.items()
        if value
    }
    base_qs = urlencode(params)
    machine_choices = list(machines().find({}).sort("code", 1))
    return render(
        request,
        "alerts/index.html",
        user=user,
        active_page="alerts",
        items=items,
        summary=_summary(),
        filters={
            "status": status,
            "level": level,
            "sensor": sensor,
            "machine": machine,
            "q": needle,
        },
        machines=machine_choices,
        sensor_order=SENSOR_ORDER,
        pagination={
            "page": page,
            "pages": pages,
            "total": total,
            "numbers": _page_window(page, pages),
        },
        page_prefix="?" + base_qs + "&" if base_qs else "?",
    )


@router.get("/alerts/{alert_id}")
def alert_detail(request: Request, alert_id: str):
    user = require_user(request)
    alert = _alert_or_404(alert_id)
    machine = machines().find_one({"_id": alert.get("machine_id")})
    threshold = thresholds().find_one({"machine_id": alert.get("machine_id"), "sensor": alert.get("sensor")})
    linked_wo = None
    if alert.get("wo_id"):
        linked_wo = work_orders().find_one({"_id": alert["wo_id"]})
    open_wo = open_for_sensor(alert["machine_id"], alert.get("sensor")) if machine else None
    other_alerts = list(
        alerts()
        .find({"_id": {"$ne": alert["_id"]}, "machine_id": alert.get("machine_id")})
        .sort("last_seen", -1)
        .limit(5)
    )
    for item in other_alerts:
        item["id"] = str(item.pop("_id"))
    item = dict(alert)
    item["id"] = str(item.pop("_id"))
    value_pct = None
    warning_pct = critical_pct = None
    if threshold and alert.get("value") is not None:
        critical = float(threshold.get("critical") or 1)
        scale = max(critical * 1.2, 0.001)
        value_pct = round(min(max(float(alert["value"]) / scale * 100, 0), 100), 1)
        warning_pct = round(min(float(threshold.get("warning") or 0) / scale * 100, 100), 1)
        critical_pct = round(min(critical / scale * 100, 100), 1)
    if linked_wo:
        linked_wo["id"] = str(linked_wo.pop("_id"))
    if open_wo:
        open_wo["id"] = str(open_wo.pop("_id"))
    return render(
        request,
        "alerts/detail.html",
        user=user,
        active_page="alerts",
        active_page_title=f"Alert {SENSORS.get(alert.get('sensor'), {}).get('label', 'Sensor')} · {alert.get('machine_code')}",
        alert=item,
        machine=machine,
        threshold=threshold,
        linked_wo=linked_wo,
        open_wo=open_wo,
        other_alerts=other_alerts,
        recommendation=ACTIONS.get(alert.get("sensor"), "Lakukan inspeksi menyeluruh."),
        sensor=SENSORS.get(alert.get("sensor"), {}),
        is_active=alert.get("status") in {"open", "acknowledged"},
        can_cancel=is_admin(user),
        value_pct=value_pct,
        warning_pct=warning_pct,
        critical_pct=critical_pct,
    )


@router.post("/alerts/{alert_id}/acknowledge")
def alert_acknowledge(request: Request, alert_id: str, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    alert = _alert_or_404(alert_id)
    if alert.get("status") != "open":
        flash(request, "error", "Alert ini tidak berada pada status aktif.")
        return RedirectResponse(f"/alerts/{alert_id}", status_code=303)
    alerts().update_one(
        {"_id": alert["_id"]},
        {
            "$set": {
                "status": "acknowledged",
                "acknowledged_by": user["id"],
                "acknowledged_by_name": user.get("nama_lengkap"),
                "acknowledged_at": utcnow(),
            }
        },
    )
    audit(user, "Mengetahui alert", "alert", alert["_id"], f"Alert {alert.get('machine_code')} · {alert.get('sensor')} diketahui.", request)
    flash(request, "success", "Alert ditandai diketahui. Tindak lanjuti sesuai rekomendasi.")
    return RedirectResponse(f"/alerts/{alert_id}", status_code=303)


@router.post("/alerts/{alert_id}/resolve")
async def alert_resolve(request: Request, alert_id: str, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    alert = _alert_or_404(alert_id)
    if alert.get("status") == "resolved":
        flash(request, "info", "Alert sudah berstatus selesai.")
        return RedirectResponse(f"/alerts/{alert_id}", status_code=303)
    raw = dict(await request.form())
    note = raw.get("note", "").strip()
    if not 5 <= len(note) <= 1000:
        flash(request, "error", "Catatan penyelesaian wajib 5–1.000 karakter.")
        return RedirectResponse(f"/alerts/{alert_id}", status_code=303)
    alerts().update_one(
        {"_id": alert["_id"]},
        {
            "$set": {
                "status": "resolved",
                "resolved_at": utcnow(),
                "resolved_by": user["id"],
                "resolved_by_name": user.get("nama_lengkap"),
                "resolution_note": note,
            }
        },
    )
    open_wo = open_for_sensor(alert["machine_id"], alert.get("sensor"))
    audit(user, "Menyelesaikan alert", "alert", alert["_id"], f"Alert {alert.get('machine_code')} diselesaikan manual.", request)
    if open_wo:
        flash(request, "success", f"Alert diselesaikan. Work order {open_wo.get('code')} masih terbuka dan perlu ditutup bila pekerjaan telah selesai.")
    else:
        flash(request, "success", "Alert berhasil diselesaikan.")
    return RedirectResponse(f"/alerts/{alert_id}", status_code=303)


@router.post("/alerts/{alert_id}/work-order")
def alert_create_wo(request: Request, alert_id: str, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    alert = _alert_or_404(alert_id)
    if alert.get("status") == "resolved":
        flash(request, "error", "Alert yang sudah selesai tidak dapat dijadikan work order.")
        return RedirectResponse(f"/alerts/{alert_id}", status_code=303)
    machine = machines().find_one({"_id": alert.get("machine_id"), "active": True})
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin terkait tidak ditemukan atau sudah diarsipkan.")
    existing = open_for_sensor(machine["_id"], alert.get("sensor"))
    if existing:
        flash(request, "info", f"Work order {existing.get('code')} sudah terbuka untuk sensor ini.")
        return RedirectResponse(f"/work-orders/{existing['_id']}", status_code=303)
    meta = SENSORS.get(alert.get("sensor"), {})
    level = alert.get("level", "warning")
    wo = create_work_order(
        machine,
        title=f"Tindak lanjut alert {meta.get('label', 'sensor')} · {machine.get('code')}",
        description=(
            f"{alert.get('message')}\n\nRekomendasi tindakan: "
            f"{ACTIONS.get(alert.get('sensor'), 'Lakukan inspeksi menyeluruh.')}"
        ),
        priority="critical" if level == "critical" else "high",
        wo_type="corrective",
        user=user,
        assigned_user=(
            None
            if is_admin(user)
            else users().find_one({"_id": ObjectId(user["id"]), "active": True, "role": "teknisi"})
        ),
        sensor=alert.get("sensor"),
        alert=alert,
        source="manual",
        due_at=utcnow() + timedelta(hours=4 if level == "critical" else 24),
        simulation_run_id=alert.get("simulation_run_id"),
        scenario_id=alert.get("scenario_id"),
    )
    if wo.get("assigned_to"):
        notify_user(
            str(wo["assigned_to"]),
            event_key=f"work-order-assigned:{wo['_id']}",
            title="Work order dari alert ditugaskan kepada Anda",
            message=f"{wo['code']} · {wo['title']}",
            href=f"/work-orders/{wo['_id']}",
        )
    alerts().update_one({"_id": alert["_id"]}, {"$set": {"wo_id": wo["_id"]}})
    audit(
        user,
        "Membuat WO dari alert",
        "work_order",
        wo["_id"],
        f"{wo['code']} dibuat dari alert {alert.get('machine_code')} · {alert.get('sensor')}.",
        request,
    )
    flash(request, "success", f"Work order {wo['code']} berhasil dibuat dari alert.")
    return RedirectResponse(f"/work-orders/{wo['_id']}", status_code=303)
