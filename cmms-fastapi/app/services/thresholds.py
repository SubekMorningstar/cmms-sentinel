from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId

from app.database import alerts
from app.services.audit import audit
from app.services.notifications import notify_role
from app.services.work_orders import create_work_order, open_for_sensor
from app.utils import ALERT_LEVEL, format_number, sensor_meta, sensor_state, utcnow

ACTIONS = {
    "temperature": "Periksa sistem pendinginan, aliran udara, dan kondisi bearing. Turunkan beban bila perlu.",
    "vibration": "Periksa alignment, keseimbangan rotor, pelumasan, dan kondisi bearing. Jadwalkan analisis getaran.",
    "power": "Periksa beban motor, suplai listrik, dan efisiensi transmisi. Validasi arus tiap fase.",
    "sound": "Periksa sumber kebisingan mekanis, pelumasan, dan pengencangan komponen. Gunakan APD pendengaran.",
}


def active_alert(machine_id: ObjectId, sensor: str) -> dict | None:
    return alerts().find_one(
        {
            "machine_id": machine_id,
            "sensor": sensor,
            "status": {"$in": ["open", "acknowledged"]},
        }
    )


def _message(machine: dict, sensor: str, level: str, value: float, threshold_value: float) -> str:
    meta = sensor_meta(sensor)
    return (
        f"{meta['label']} {format_number(value)} {meta['unit']} pada {machine.get('code')} "
        f"melampaui batas {ALERT_LEVEL.get(level, level).lower()} "
        f"({format_number(threshold_value)} {meta['unit']})."
    )


def evaluate_reading(
    reading: dict,
    machine: dict,
    machine_thresholds: list[dict],
    *,
    ts: datetime | None = None,
) -> dict[str, Any]:
    moment = ts or reading.get("ts") or utcnow()
    created_alerts: list[dict] = []
    updated_alerts: list[dict] = []
    resolved_alerts: list[dict] = []
    created_orders: list[dict] = []

    for threshold in machine_thresholds:
        if not threshold.get("enabled", True):
            continue
        sensor = threshold.get("sensor")
        if sensor not in reading:
            if not (reading.get("sensor_fault") and reading.get("fault_sensor") == sensor):
                continue
        value = reading.get(sensor)
        if value is None:
            if reading.get("sensor_fault") and reading.get("fault_sensor") == sensor:
                current = active_alert(machine["_id"], sensor)
                details = {
                    "source": reading.get("source"),
                    "simulation_run_id": reading.get("simulation_run_id"),
                    "scenario_id": reading.get("scenario_id"),
                    "fault_label": True,
                    "sensor_fault": True,
                }
                message = f"Sensor {sensor_meta(sensor)['label']} pada {machine.get('code')} terputus; data tidak diterima."
                if current:
                    alerts().update_one(
                        {"_id": current["_id"]},
                        {
                            "$set": {"last_seen": moment, "consecutive_normal": 0, **details},
                            "$inc": {"readings_seen": 1},
                        },
                    )
                else:
                    doc = {
                        "machine_id": machine["_id"],
                        "machine_code": machine.get("code"),
                        "machine_name": machine.get("name"),
                        "sensor": sensor,
                        "level": "warning",
                        "status": "open",
                        "value": None,
                        "threshold_value": None,
                        "unit": sensor_meta(sensor)["unit"],
                        "message": message,
                        "first_seen": moment,
                        "last_seen": moment,
                        "readings_seen": 1,
                        "consecutive_normal": 0,
                        "acknowledged_by": None,
                        "acknowledged_at": None,
                        "resolved_at": None,
                        "wo_id": None,
                        **details,
                    }
                    inserted = alerts().insert_one(doc)
                    doc["_id"] = inserted.inserted_id
                    created_alerts.append(doc)
                    audit(
                        None,
                        "Alert sensor terputus",
                        "alert",
                        inserted.inserted_id,
                        message,
                    )
            continue
        value = float(value)
        state = sensor_state(value, threshold)
        current = active_alert(machine["_id"], sensor)

        if state == "normal":
            if not current:
                continue
            streak = int(current.get("consecutive_normal", 0)) + 1
            if streak >= int(threshold.get("normal_reset_readings", 3)):
                alerts().update_one(
                    {"_id": current["_id"]},
                    {
                        "$set": {
                            "status": "resolved",
                            "resolved_at": moment,
                            "value": value,
                            "consecutive_normal": streak,
                            "resolution_note": "Pulih otomatis setelah nilai kembali normal.",
                        }
                    },
                )
                resolved_alerts.append(current)
                audit(
                    None,
                    "Alert pulih otomatis",
                    "alert",
                    current["_id"],
                    f"{machine.get('code')} · {sensor_meta(sensor)['label']} kembali normal.",
                )
            else:
                alerts().update_one(
                    {"_id": current["_id"]},
                    {"$set": {"value": value, "consecutive_normal": streak, "last_seen": moment}},
                )
            continue

        level = "critical" if state == "critical" else "warning"
        threshold_value = float(threshold.get("critical") if level == "critical" else threshold.get("warning"))
        message = _message(machine, sensor, level, value, threshold_value)

        if current:
            escalate = level == "critical" and current.get("level") != "critical"
            updates = {
                "value": value,
                "last_seen": moment,
                "consecutive_normal": 0,
                "threshold_value": threshold_value,
                "message": message,
            }
            if reading.get("simulation_run_id"):
                updates.update(
                    {
                        "source": reading.get("source"),
                        "simulation_run_id": reading["simulation_run_id"],
                        "scenario_id": reading.get("scenario_id"),
                        "fault_label": bool(reading.get("fault_label")),
                    }
                )
            if escalate:
                updates["level"] = "critical"
                updates["escalated_at"] = moment
            alerts().update_one({"_id": current["_id"]}, {"$set": updates})
            alerts().update_one({"_id": current["_id"]}, {"$inc": {"readings_seen": 1}})
            updated_alerts.append({**current, **updates})
            if escalate:
                audit(
                    None,
                    "Alert meningkat",
                    "alert",
                    current["_id"],
                    f"{machine.get('code')} · {sensor_meta(sensor)['label']} naik ke level kritis.",
                )
                notify_role(
                    "admin",
                    event_key=f"critical-alert-escalated:{current['_id']}:{moment.isoformat()}",
                    title="Alert meningkat menjadi kritis",
                    message=message,
                    href=f"/alerts/{current['_id']}",
                    created_at=moment,
                )
        else:
            doc = {
                "machine_id": machine["_id"],
                "machine_code": machine.get("code"),
                "machine_name": machine.get("name"),
                "sensor": sensor,
                "level": level,
                "status": "open",
                "value": value,
                "threshold_value": threshold_value,
                "unit": sensor_meta(sensor)["unit"],
                "message": message,
                "first_seen": moment,
                "last_seen": moment,
                "readings_seen": 1,
                "consecutive_normal": 0,
                "acknowledged_by": None,
                "acknowledged_at": None,
                "resolved_at": None,
                "wo_id": None,
                "source": reading.get("source"),
                "simulation_run_id": reading.get("simulation_run_id"),
                "scenario_id": reading.get("scenario_id"),
                "fault_label": bool(reading.get("fault_label")),
            }
            inserted = alerts().insert_one(doc)
            doc["_id"] = inserted.inserted_id
            created_alerts.append(doc)
            if level == "critical":
                notify_role(
                    "admin",
                    event_key=f"critical-alert:{inserted.inserted_id}",
                    title="Alert kritis pada aset",
                    message=message,
                    href=f"/alerts/{inserted.inserted_id}",
                    created_at=moment,
                )
            audit(
                None,
                "Alert dibuat",
                "alert",
                inserted.inserted_id,
                message,
            )
            current = doc

        if level == "critical":
            open_wo = open_for_sensor(machine["_id"], sensor)
            if not open_wo:
                order = create_work_order(
                    machine,
                    title=f"Perbaikan kritis · {sensor_meta(sensor)['label']} {machine.get('code')}",
                    description=f"{message}\n\nRekomendasi tindakan: {ACTIONS.get(sensor, 'Lakukan inspeksi menyeluruh.')}",
                    priority="critical",
                    wo_type="corrective",
                    sensor=sensor,
                    alert=current,
                    source="automatic",
                    due_at=moment + timedelta(hours=4),
                    simulation_run_id=reading.get("simulation_run_id"),
                    scenario_id=reading.get("scenario_id"),
                )
                alerts().update_one(
                    {"_id": current["_id"]},
                    {"$set": {"wo_id": order["_id"]}},
                )
                created_orders.append(order)
                audit(
                    None,
                    "Work order otomatis",
                    "work_order",
                    order["_id"],
                    f"{order['code']} dibuat dari alert kritis {machine.get('code')} · {sensor_meta(sensor)['label']}.",
                )
            elif current.get("wo_id") is None:
                alerts().update_one({"_id": current["_id"]}, {"$set": {"wo_id": open_wo["_id"]}})

    return {
        "created_alerts": created_alerts,
        "updated_alerts": updated_alerts,
        "resolved_alerts": resolved_alerts,
        "created_orders": created_orders,
    }
