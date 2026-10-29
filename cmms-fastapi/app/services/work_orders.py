from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId
from pymongo import ReturnDocument

from app.database import alerts, counters, work_orders
from app.utils import to_local, utcnow

STATUS_FLOW = {
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"awaiting_review", "cancelled"},
    "awaiting_review": {"resolved", "in_progress"},
    "resolved": set(),
    "cancelled": set(),
}

DEFAULT_CHECKLIST = {
    "corrective": ["Pastikan area kerja aman", "Periksa dan catat kondisi awal", "Lakukan tindakan perbaikan", "Uji fungsi setelah perbaikan", "Rapikan area kerja"],
    "preventive": ["Pastikan area kerja aman", "Periksa kondisi komponen", "Bersihkan dan lumasi sesuai kebutuhan", "Uji fungsi aset", "Catat temuan inspeksi"],
    "inspection": ["Pastikan area kerja aman", "Periksa kondisi visual", "Periksa indikator dan sensor", "Catat hasil pemeriksaan", "Laporkan temuan lanjutan"],
}


def generate_code(now: datetime | None = None) -> str:
    moment = to_local(now or utcnow())
    key = f"wo-{moment.strftime('%Y%m')}"
    doc = counters().find_one_and_update(
        {"_id": key},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    seq = int(doc.get("seq", 1))
    return f"WO-{moment.strftime('%Y%m')}-{seq:04d}"


def open_for_sensor(machine_id: ObjectId, sensor: str) -> dict | None:
    return work_orders().find_one(
        {
            "machine_id": machine_id,
            "sensor": sensor,
            "status": {"$in": ["pending", "in_progress", "awaiting_review"]},
        }
    )


def create_work_order(
    machine: dict,
    *,
    title: str,
    description: str,
    priority: str = "medium",
    wo_type: str = "corrective",
    user: dict | None = None,
    assigned_user: dict | None = None,
    due_at: datetime | None = None,
    sensor: str | None = None,
    alert: dict | None = None,
    source: str = "manual",
    created_at: datetime | None = None,
    simulation_run_id: str | None = None,
    scenario_id: str | None = None,
    checklist: list[str] | None = None,
    maintenance_plan_id: str | None = None,
    maintenance_occurrence: str | None = None,
) -> dict:
    moment = created_at or utcnow()
    actor_name = user.get("nama_lengkap") if user else "Sistem"
    code = generate_code(moment)
    doc = {
        "code": code,
        "machine_id": machine["_id"],
        "machine_code": machine.get("code"),
        "machine_name": machine.get("name"),
        "title": title.strip(),
        "description": description.strip(),
        "priority": priority,
        "type": wo_type,
        "status": "pending",
        "sensor": sensor,
        "assigned_to": assigned_user.get("_id") if assigned_user else None,
        "assigned_name": assigned_user.get("nama_lengkap") if assigned_user else None,
        "created_by": user.get("id") if user else "system",
        "created_by_name": actor_name,
        "source": source,
        "alert_id": alert.get("_id") if alert else None,
        "simulation_run_id": simulation_run_id,
        "scenario_id": scenario_id,
        "maintenance_plan_id": maintenance_plan_id,
        "checklist": [
            {"label": item[:160], "done": False}
            for item in (checklist or DEFAULT_CHECKLIST.get(wo_type, DEFAULT_CHECKLIST["inspection"]))
            if item.strip()
        ][:20],
        "parts_used": [],
        "inspection_result": None,
        "review_outcome": None,
        "created_at": moment,
        "updated_at": moment,
        "due_at": due_at or (moment + timedelta(hours=4 if priority == "critical" else 24)),
        "started_at": None,
        "resolved_at": None,
        "cancelled_at": None,
        "downtime_minutes": None,
        "resolution_notes": "",
        "activities": [
            {
                "ts": moment,
                "actor": actor_name,
                "action": "created",
                "status": "pending",
                "note": "Work order dibuat." if source == "manual" else "Dibuat otomatis oleh sistem CBM.",
            }
        ],
    }
    if maintenance_occurrence:
        doc["maintenance_occurrence"] = maintenance_occurrence
    work_orders().insert_one(doc)
    return doc


def add_activity(
    wo_id: ObjectId,
    *,
    actor: str,
    action: str,
    status: str,
    note: str = "",
    ts: datetime | None = None,
) -> None:
    work_orders().update_one(
        {"_id": wo_id},
        {
            "$push": {
                "activities": {
                    "ts": ts or utcnow(),
                    "actor": actor,
                    "action": action,
                    "status": status,
                    "note": note,
                }
            },
            "$set": {"updated_at": utcnow()},
        },
    )


def transition(
    wo: dict,
    new_status: str,
    *,
    user: dict,
    notes: str = "",
    downtime_minutes: int | None = None,
    inspection_result: str | None = None,
    review_outcome: str | None = None,
) -> dict:
    current = wo.get("status", "pending")
    if new_status not in STATUS_FLOW.get(current, set()):
        raise ValueError(f"Perubahan status dari {current} ke {new_status} tidak diizinkan.")
    moment = utcnow()
    updates: dict = {"status": new_status, "updated_at": moment}
    action = "status_changed"
    actor_name = user.get("nama_lengkap", "Pengguna")
    if current == "awaiting_review" and new_status == "in_progress":
        updates["review_returned_at"] = moment
        action = "returned_for_rework"
    elif new_status == "in_progress":
        updates["started_at"] = wo.get("started_at") or moment
        if not wo.get("assigned_to"):
            updates["assigned_to"] = ObjectId(user["id"])
            updates["assigned_name"] = actor_name
        action = "started"
    elif new_status == "resolved":
        updates["resolved_at"] = moment
        updates["completed_at"] = moment
        updates["started_at"] = wo.get("started_at") or wo.get("created_at") or moment
        updates["resolution_notes"] = notes.strip()
        updates["downtime_minutes"] = max(int(downtime_minutes or 0), 0)
        if review_outcome:
            updates["review_outcome"] = review_outcome
        action = "resolved"
    elif new_status == "awaiting_review":
        updates["submitted_at"] = moment
        updates["inspection_result"] = inspection_result
        updates["resolution_notes"] = notes.strip()
        action = "submitted_for_review"
    elif new_status == "cancelled":
        updates["cancelled_at"] = moment
        updates["resolution_notes"] = notes.strip()
        action = "cancelled"

    work_orders().update_one({"_id": wo["_id"]}, {"$set": updates})
    add_activity(
        wo["_id"],
        actor=actor_name,
        action=action,
        status=new_status,
        note=notes.strip(),
        ts=moment,
    )
    if new_status == "resolved" and wo.get("alert_id"):
        alerts().update_one(
            {"_id": wo["alert_id"], "status": {"$in": ["open", "acknowledged"]}},
            {
                "$set": {
                    "status": "resolved",
                    "resolved_at": moment,
                    "resolved_by": user.get("id"),
                    "resolved_by_name": actor_name,
                    "resolution_note": f"Diselesaikan melalui {wo.get('code')}.",
                    "outcome": review_outcome or "confirmed_issue",
                }
            },
        )
    return work_orders().find_one({"_id": wo["_id"]})


def next_due_options(now: datetime | None = None) -> dict[str, datetime]:
    base = now or utcnow()
    return {
        "4h": base + timedelta(hours=4),
        "24h": base + timedelta(days=1),
        "72h": base + timedelta(days=3),
        "7d": base + timedelta(days=7),
    }
