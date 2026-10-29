from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import settings
from app.database import alerts, machines, thresholds, work_orders
from app.security import get_optional_user
from app.services.analytics import fleet_snapshots, monitoring_payload
from app.services.audit import audit
from app.services.thresholds import evaluate_reading
from app.utils import SENSOR_ORDER, utcnow

router = APIRouter(prefix="/api")
ALLOWED_HOURS = {1, 6, 24, 168}


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ts: datetime | None = None
    temperature: float | None = Field(None, ge=-40, le=300, description="Suhu dalam °C")
    vibration: float | None = Field(None, ge=0, le=200, description="Getaran RMS dalam mm/s")
    power: float | None = Field(None, ge=0, le=5000, description="Daya dalam kW")
    sound: float | None = Field(None, ge=0, le=200, description="Kebisingan dalam dB(A)")

    @field_validator("ts")
    @classmethod
    def normalize_ts(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def require_sensor(self):
        if all(getattr(self, sensor) is None for sensor in SENSOR_ORDER):
            raise ValueError("Minimal satu nilai sensor harus diisi.")
        return self


class IngestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_code: str = Field(min_length=1, max_length=40, examples=["CNC-01"])
    readings: list[ReadingIn] = Field(min_length=1, max_length=500)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _api_key_ok(request: Request) -> bool:
    supplied = request.headers.get("x-api-key", "")
    if not supplied:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), settings.ingest_api_key.encode("utf-8"))


def _require_read_access(request: Request) -> dict | None:
    if _api_key_ok(request):
        return None
    user = get_optional_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Sertakan header X-API-Key atau masuk melalui sesi web.",
            headers={"WWW-Authenticate": 'ApiKey realm="CMMS Sentinel"'},
        )
    return user


def _sender_name(request: Request) -> str:
    client = request.client.host if request.client else "gateway"
    return f"Gateway {client}"


def _clean_alert(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "machine_code": doc.get("machine_code"),
        "machine_name": doc.get("machine_name"),
        "sensor": doc.get("sensor"),
        "level": doc.get("level"),
        "status": doc.get("status"),
        "value": doc.get("value"),
        "threshold_value": doc.get("threshold_value"),
        "unit": doc.get("unit"),
        "message": doc.get("message"),
        "first_seen": _iso(doc.get("first_seen")),
        "last_seen": _iso(doc.get("last_seen")),
        "acknowledged_at": _iso(doc.get("acknowledged_at")),
        "acknowledged_by": doc.get("acknowledged_by_name"),
        "resolved_at": _iso(doc.get("resolved_at")),
        "work_order_id": str(doc["wo_id"]) if doc.get("wo_id") else None,
    }


def _snapshot_payload(snapshot: dict) -> dict:
    machine = snapshot["machine"]
    sensors = {}
    for sensor, data in snapshot["sensors"].items():
        threshold = data.get("threshold") or {}
        sensors[sensor] = {
            "value": data.get("value"),
            "unit": data.get("unit"),
            "state": data.get("state"),
            "warning": threshold.get("warning"),
            "critical": threshold.get("critical"),
            "enabled": threshold.get("enabled", True),
        }
    return {
        "id": snapshot["id"],
        "code": machine.get("code"),
        "name": machine.get("name"),
        "asset_type": machine.get("asset_type"),
        "location": machine.get("location"),
        "criticality": machine.get("criticality"),
        "operational_status": machine.get("operational_status"),
        "online": snapshot["online"],
        "last_reading": _iso(snapshot["last_ts"]),
        "health": {
            "score": snapshot["score"],
            "state": snapshot["health"]["key"],
            "label": snapshot["health"]["label"],
        },
        "active_alerts": snapshot["alert_count"],
        "open_work_orders": snapshot["wo_count"],
        "sensors": sensors,
    }


@router.post("/ingest", status_code=201)
def ingest_readings(request: Request, payload: IngestPayload):
    if not _api_key_ok(request):
        raise HTTPException(status_code=401, detail="API key tidak valid.")
    code = payload.machine_code.strip().upper()
    machine = machines().find_one({"code": code, "active": True})
    if not machine:
        raise HTTPException(status_code=404, detail=f"Mesin {code} tidak ditemukan atau tidak aktif.")
    moment = utcnow()
    docs = []
    for reading in payload.readings:
        ts = reading.ts or moment
        if ts > moment + timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="Timestamp tidak boleh lebih dari 5 menit di masa depan.")
        if ts < moment - timedelta(days=366):
            raise HTTPException(status_code=422, detail="Timestamp lebih lama dari 366 hari.")
        docs.append(
            {
                "ts": ts,
                "machine_id": machine["_id"],
                "machine_code": machine.get("code"),
                "temperature": reading.temperature,
                "vibration": reading.vibration,
                "power": reading.power,
                "sound": reading.sound,
                "source": "iot",
            }
        )
    from app.database import readings

    readings().insert_many(docs)
    latest = max(docs, key=lambda item: item["ts"])
    machine_thresholds = list(
        thresholds().find({"machine_id": machine["_id"], "enabled": True})
    )
    result = evaluate_reading(latest, machine, machine_thresholds, ts=latest["ts"])
    audit(
        None,
        "Ingest data sensor",
        "machine",
        machine["_id"],
        f"{len(docs)} pembacaan dari {_sender_name(request)} untuk {code}.",
        request,
    )
    return {
        "ok": True,
        "accepted": len(docs),
        "machine_code": code,
        "latest_ts": _iso(latest["ts"]),
        "alerts": {
            "created": [_clean_alert(item) for item in result["created_alerts"]],
            "updated": [_clean_alert(item) for item in result["updated_alerts"]],
            "resolved": [_clean_alert(item) for item in result["resolved_alerts"]],
        },
        "work_orders_created": [
            {"id": str(item["_id"]), "code": item["code"]}
            for item in result["created_orders"]
        ],
    }


@router.get("/machines")
def api_machines(request: Request):
    _require_read_access(request)
    snapshots = fleet_snapshots()
    return {
        "ok": True,
        "count": len(snapshots),
        "generated_at": _iso(utcnow()),
        "machines": [_snapshot_payload(item) for item in snapshots],
    }


@router.get("/machines/{code}/latest")
def api_machine_latest(
    request: Request,
    code: str,
    hours: int = Query(24),
):
    _require_read_access(request)
    if hours not in ALLOWED_HOURS:
        hours = 24
    machine = machines().find_one({"code": code.strip().upper(), "active": True})
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin tidak ditemukan atau tidak aktif.")
    payload = monitoring_payload(machine, hours, max_points=180)
    serialized_alerts = []
    for alert in payload["alerts"]:
        item = dict(alert)
        item["_id"] = ObjectId(item["id"])
        serialized_alerts.append(_clean_alert(item))
    return {
        "ok": True,
        "generated_at": _iso(utcnow()),
        "hours": hours,
        "machine": _snapshot_payload(payload["snapshot"]),
        "series": payload["series"],
        "alerts": serialized_alerts,
        "work_orders": [
            {
                "id": item["id"],
                "code": item.get("code"),
                "title": item.get("title"),
                "status": item.get("status"),
                "priority": item.get("priority"),
                "due_at": _iso(item.get("due_at")),
            }
            for item in payload["work_orders"]
        ],
    }


@router.get("/alerts")
def api_alerts(
    request: Request,
    status: str = Query("active", max_length=20),
    limit: int = Query(50, ge=1, le=200),
):
    _require_read_access(request)
    query: dict = {}
    if status == "active":
        query["status"] = {"$in": ["open", "acknowledged"]}
    elif status in {"open", "acknowledged", "resolved"}:
        query["status"] = status
    docs = list(alerts().find(query).sort("last_seen", -1).limit(limit))
    return {
        "ok": True,
        "count": len(docs),
        "generated_at": _iso(utcnow()),
        "alerts": [_clean_alert(doc) for doc in docs],
    }


@router.get("/work-orders")
def api_work_orders(
    request: Request,
    status: str = Query("active", max_length=20),
    limit: int = Query(50, ge=1, le=200),
):
    _require_read_access(request)
    query: dict = {}
    if status == "active":
        query["status"] = {"$in": ["pending", "in_progress"]}
    elif status in {"pending", "in_progress", "resolved", "cancelled"}:
        query["status"] = status
    docs = list(work_orders().find(query).sort("created_at", -1).limit(limit))
    items = [
        {
            "id": str(doc["_id"]),
            "code": doc.get("code"),
            "machine_code": doc.get("machine_code"),
            "machine_name": doc.get("machine_name"),
            "title": doc.get("title"),
            "type": doc.get("type"),
            "priority": doc.get("priority"),
            "status": doc.get("status"),
            "source": doc.get("source"),
            "assigned_to": doc.get("assigned_name"),
            "created_at": _iso(doc.get("created_at")),
            "due_at": _iso(doc.get("due_at")),
            "started_at": _iso(doc.get("started_at")),
            "resolved_at": _iso(doc.get("resolved_at")),
            "downtime_minutes": doc.get("downtime_minutes"),
        }
        for doc in docs
    ]
    return {
        "ok": True,
        "count": len(items),
        "generated_at": _iso(utcnow()),
        "work_orders": items,
    }
