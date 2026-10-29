from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.database import machines
from app.security import require_user
from app.services.analytics import monitoring_payload
from app.services.telemetry import DEMO_SOURCES
from app.utils import SENSORS, dumps
from app.web import render

router = APIRouter()
ALLOWED_HOURS = {1: "1 jam", 6: "6 jam", 24: "24 jam", 168: "7 hari"}


@router.get("/cbm-monitoring")
def monitoring_page(
    request: Request,
    machine: str | None = Query(None, max_length=40),
    hours: int = Query(24),
):
    user = require_user(request)
    if hours not in ALLOWED_HOURS:
        hours = 24
    machine_list = list(machines().find({"active": True}).sort("code", 1))
    if not machine_list:
        return render(
            request,
            "monitoring/index.html",
            user=user,
            active_page="monitoring",
            empty=True,
            machines=[],
            machine=None,
            hours=hours,
            allowed_hours=ALLOWED_HOURS,
            payload=None,
            chart_json="{}",
        )
    selected = None
    if machine:
        selected = next((item for item in machine_list if item.get("code") == machine), None)
        if not selected:
            raise HTTPException(status_code=404, detail="Mesin tidak ditemukan atau sudah diarsipkan.")
    selected = selected or machine_list[0]
    payload = monitoring_payload(selected, hours)
    snapshot = payload["snapshot"]
    chart_data = {
        "machine": {
            "code": selected.get("code"),
            "name": selected.get("name"),
            "unit": "",
        },
        "series": payload["series"],
        "thresholds": payload["thresholds"],
        "sensor_meta": {
            sensor: {"label": meta["label"], "unit": meta["unit"]}
            for sensor, meta in SENSORS.items()
        },
        "states": {
            sensor: data["state"] for sensor, data in snapshot["sensors"].items()
        },
        "hours": hours,
    }
    return render(
        request,
        "monitoring/index.html",
        user=user,
        active_page="monitoring",
        empty=False,
        machines=machine_list,
        machine=selected,
        hours=hours,
        allowed_hours=ALLOWED_HOURS,
        payload=payload,
        snapshot=snapshot,
        has_synthetic_series=bool(DEMO_SOURCES.intersection(payload["sources"])),
        chart_json=dumps(chart_data),
    )
