from __future__ import annotations

import csv
import io
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.database import alerts, machines, readings, work_orders
from app.security import require_user
from app.services.analytics import fleet_snapshots, report_payload
from app.services.audit import audit
from app.utils import (
    ALERT_LEVEL,
    PRIORITY,
    SOURCE_LABEL,
    WO_STATUS,
    WO_TYPE,
    dumps,
    to_local,
    utcnow,
)
from app.web import render

router = APIRouter()
ALLOWED_DAYS = {7: "7 hari", 14: "14 hari", 30: "30 hari", 90: "90 hari"}
EXPORT_DATASETS = {
    "work_orders": "Work order",
    "alerts": "Alert",
    "readings": "Pembacaan sensor",
    "machines": "Master mesin",
}
MAX_EXPORT_ROWS = 50000


def _safe_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Ya" if value else "Tidak"
    text = str(value).replace("\x00", "").strip()
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        text = "'" + text
    return text


def _stamp(value) -> str:
    local = to_local(value)
    return local.strftime("%Y-%m-%d %H:%M:%S") if local else ""


def _decimal(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _machine_map() -> dict:
    return {doc["_id"]: doc for doc in machines().find({})}


@router.get("/reports")
def reports_page(
    request: Request,
    days: int = Query(14),
):
    user = require_user(request)
    if days not in ALLOWED_DAYS:
        days = 14
    payload = report_payload(days)
    chart_data = {
        "wo_trend": payload["wo_trend"],
        "alert_breakdown": payload["alert_breakdown"],
        "wo_breakdown": payload["wo_breakdown"],
        "health": [
            {
                "code": item["machine"].get("code"),
                "score": item["score"],
                "health": item["health"]["label"],
            }
            for item in payload["per_machine"]
        ],
    }
    params = urlencode({"days": days})
    return render(
        request,
        "reports/index.html",
        user=user,
        active_page="reports",
        payload=payload,
        days=days,
        allowed_days=ALLOWED_DAYS,
        chart_json=dumps(chart_data),
        export_suffix=params,
        generated_at=utcnow(),
    )


@router.get("/reports/export.csv")
def export_csv(
    request: Request,
    dataset: str = Query("work_orders", max_length=30),
    days: int = Query(14),
):
    user = require_user(request)
    if dataset not in EXPORT_DATASETS:
        raise HTTPException(status_code=404, detail="Dataset ekspor tidak tersedia.")
    if days not in ALLOWED_DAYS:
        days = 14
    start = utcnow() - timedelta(days=days)
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    machine_map = _machine_map()

    if dataset == "work_orders":
        writer.writerow(
            [
                "Kode", "Mesin", "Nama Mesin", "Judul", "Jenis", "Prioritas", "Status",
                "Sumber", "Ditugaskan", "Dibuat", "Tenggat", "Mulai", "Selesai",
                "Downtime (menit)", "Catatan", "Data simulasi", "Skenario", "Run ID",
            ]
        )
        docs = work_orders().find(
            {
                "$or": [
                    {"created_at": {"$gte": start}},
                    {"resolved_at": {"$gte": start}},
                ]
            }
        ).sort("created_at", -1).limit(MAX_EXPORT_ROWS)
        for doc in docs:
            writer.writerow(
                [
                    _safe_cell(doc.get("code")),
                    _safe_cell(doc.get("machine_code")),
                    _safe_cell(doc.get("machine_name")),
                    _safe_cell(doc.get("title")),
                    _safe_cell(WO_TYPE.get(doc.get("type"), doc.get("type"))),
                    _safe_cell(PRIORITY.get(doc.get("priority"), doc.get("priority"))),
                    _safe_cell(WO_STATUS.get(doc.get("status"), doc.get("status"))),
                    _safe_cell(SOURCE_LABEL.get(doc.get("source"), doc.get("source"))),
                    _safe_cell(doc.get("assigned_name")),
                    _stamp(doc.get("created_at")),
                    _stamp(doc.get("due_at")),
                    _stamp(doc.get("started_at")),
                    _stamp(doc.get("resolved_at")),
                    doc.get("downtime_minutes") if doc.get("downtime_minutes") is not None else "",
                    _safe_cell(doc.get("resolution_notes")),
                    "Ya" if doc.get("simulation_run_id") else "Tidak",
                    _safe_cell(doc.get("scenario_id")),
                    _safe_cell(doc.get("simulation_run_id")),
                ]
            )
    elif dataset == "alerts":
        writer.writerow(
            [
                "Mesin", "Nama Mesin", "Sensor", "Level", "Status", "Nilai", "Satuan",
                "Batas", "Pesan", "Pertama Terdeteksi", "Terakhir Terdeteksi",
                "Diketahui Oleh", "Waktu Diketahui", "Diselesaikan Oleh", "Waktu Selesai",
                "Catatan Penyelesaian", "Sumber", "Data simulasi", "Skenario", "Run ID",
            ]
        )
        docs = alerts().find(
            {"$or": [{"first_seen": {"$gte": start}}, {"resolved_at": {"$gte": start}}]}
        ).sort("first_seen", -1).limit(MAX_EXPORT_ROWS)
        for doc in docs:
            writer.writerow(
                [
                    _safe_cell(doc.get("machine_code")),
                    _safe_cell(doc.get("machine_name")),
                    _safe_cell(doc.get("sensor")),
                    _safe_cell(ALERT_LEVEL.get(doc.get("level"), doc.get("level"))),
                    _safe_cell({"open": "Aktif", "acknowledged": "Diketahui", "resolved": "Selesai"}.get(doc.get("status"), doc.get("status"))),
                    _decimal(doc.get("value")),
                    _safe_cell(doc.get("unit")),
                    _decimal(doc.get("threshold_value")),
                    _safe_cell(doc.get("message")),
                    _stamp(doc.get("first_seen")),
                    _stamp(doc.get("last_seen")),
                    _safe_cell(doc.get("acknowledged_by_name")),
                    _stamp(doc.get("acknowledged_at")),
                    _safe_cell(doc.get("resolved_by_name")),
                    _stamp(doc.get("resolved_at")),
                    _safe_cell(doc.get("resolution_note")),
                    _safe_cell(SOURCE_LABEL.get(doc.get("source"), doc.get("source"))),
                    "Ya" if doc.get("simulation_run_id") else "Tidak",
                    _safe_cell(doc.get("scenario_id")),
                    _safe_cell(doc.get("simulation_run_id")),
                ]
            )
    elif dataset == "readings":
        writer.writerow(["Waktu", "Kode Mesin", "Suhu (C)", "Getaran (mm/s)", "Daya (kW)", "Suara (dBA)", "Sumber", "Data simulasi", "Skenario", "Run ID"])
        docs = readings().find(
            {"ts": {"$gte": start}},
            {"ts": 1, "machine_id": 1, "temperature": 1, "vibration": 1, "power": 1, "sound": 1, "source": 1, "scenario_id": 1, "simulation_run_id": 1, "_id": 0},
        ).sort("ts", 1).limit(MAX_EXPORT_ROWS)
        for doc in docs:
            machine = machine_map.get(doc.get("machine_id"))
            writer.writerow(
                [
                    _stamp(doc.get("ts")),
                    _safe_cell(machine.get("code") if machine else ""),
                    _decimal(doc.get("temperature")),
                    _decimal(doc.get("vibration")),
                    _decimal(doc.get("power")),
                    _decimal(doc.get("sound")),
                    _safe_cell(SOURCE_LABEL.get(doc.get("source"), doc.get("source"))),
                    "Ya" if doc.get("source") in {"simulator", "dataset-seed"} else "Tidak",
                    _safe_cell(doc.get("scenario_id")),
                    _safe_cell(doc.get("simulation_run_id")),
                ]
            )
    else:
        writer.writerow(
            [
                "Kode", "Nama", "Tipe", "Lokasi", "Produsen", "Model", "Nomor Seri",
                "Kekritisan", "Status", "Skor Kesehatan", "Kondisi", "Online",
                "Alert Aktif", "WO Aktif", "Daya (kW)", "Kecepatan (rpm)",
                "Sumber terbaru", "Data simulasi", "Skenario aktif",
            ]
        )
        for snapshot in fleet_snapshots(include_archived=True):
            machine = snapshot["machine"]
            writer.writerow(
                [
                    _safe_cell(machine.get("code")),
                    _safe_cell(machine.get("name")),
                    _safe_cell(machine.get("asset_type")),
                    _safe_cell(machine.get("location")),
                    _safe_cell(machine.get("manufacturer")),
                    _safe_cell(machine.get("model")),
                    _safe_cell(machine.get("serial_number")),
                    _safe_cell(machine.get("criticality")),
                    _safe_cell(machine.get("operational_status")),
                    snapshot["score"] if snapshot["score"] is not None else "",
                    _safe_cell(snapshot["health"]["label"]),
                    "Ya" if snapshot["online"] else "Tidak",
                    snapshot["alert_count"],
                    snapshot["wo_count"],
                    _decimal(machine.get("rated_power_kw")),
                    machine.get("rated_speed_rpm") or "",
                    _safe_cell(snapshot.get("source_label")),
                    "Ya" if snapshot.get("is_synthetic") else "Tidak",
                    _safe_cell(snapshot.get("scenario_label")),
                ]
            )

    audit(
        user,
        "Ekspor data",
        "report",
        dataset,
        f"Ekspor {EXPORT_DATASETS[dataset]} {days} hari ({output.getvalue().count(chr(10)) - 1} baris).",
        request,
    )
    filename = f"cmms-{dataset}-{utcnow().strftime('%Y%m%d-%H%M')}.csv"
    content = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
