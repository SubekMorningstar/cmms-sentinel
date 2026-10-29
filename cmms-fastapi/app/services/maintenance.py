from __future__ import annotations

import logging
import asyncio
from datetime import timedelta

from pymongo.errors import DuplicateKeyError

from app.database import machines, maintenance_plans, readings, users, work_orders
from app.services.notifications import notify_user
from app.services.telemetry import REAL_SOURCES
from app.services.work_orders import create_work_order
from app.utils import utcnow

log = logging.getLogger(__name__)


def is_virtual_machine(machine_id) -> bool:
    return not readings().find_one(
        {"machine_id": machine_id, "source": {"$in": sorted(REAL_SOURCES)}},
        {"_id": 1},
    )


def generate_due_preventive_work_orders(now=None) -> int:
    moment = now or utcnow()
    due_plans = list(
        maintenance_plans()
        .find({"active": True, "next_due_at": {"$lte": moment}})
        .sort("next_due_at", 1)
        .limit(50)
    )
    created = 0
    for plan in due_plans:
        scheduled_for = plan["next_due_at"]
        occurrence = f"{plan['_id']}:{scheduled_for.isoformat()}"
        existing = work_orders().find_one({"maintenance_occurrence": occurrence}, {"_id": 1})
        if existing:
            maintenance_plans().update_one(
                {"_id": plan["_id"], "next_due_at": scheduled_for},
                {"$set": {"next_due_at": moment + timedelta(days=plan["interval_days"]), "last_generated_at": moment}},
            )
            continue
        machine = machines().find_one({"_id": plan["machine_id"], "active": True})
        if not machine:
            log.warning("Rencana preventif %s dilewati: aset nonaktif atau tidak ditemukan", plan.get("name"))
            continue
        if not is_virtual_machine(machine["_id"]):
            log.warning("Rencana preventif %s dilewati: aset memiliki telemetry gateway", plan.get("name"))
            continue
        assigned_user = users().find_one({"_id": plan.get("assigned_to"), "active": True}) if plan.get("assigned_to") else None
        next_due = moment + timedelta(days=plan["interval_days"])
        try:
            wo = create_work_order(
                machine,
                title=plan["title"],
                description=plan["description"],
                priority=plan.get("priority", "medium"),
                wo_type="preventive",
                assigned_user=assigned_user,
                due_at=moment + timedelta(hours=24),
                source="preventive",
                checklist=plan.get("checklist"),
                maintenance_plan_id=str(plan["_id"]),
                maintenance_occurrence=occurrence,
            )
        except DuplicateKeyError:
            maintenance_plans().update_one(
                {"_id": plan["_id"], "next_due_at": scheduled_for},
                {"$set": {"next_due_at": next_due, "last_generated_at": moment}},
            )
            continue
        updated = maintenance_plans().update_one(
            {"_id": plan["_id"], "next_due_at": scheduled_for},
            {"$set": {"next_due_at": next_due, "last_generated_at": moment}},
        )
        if not updated.modified_count:
            log.error("Work order preventif dibuat tetapi jadwal %s gagal diklaim", plan["_id"])
        if assigned_user:
            notify_user(
                str(assigned_user["_id"]),
                event_key=f"work-order-assigned:{wo['_id']}",
                title="Inspeksi preventif baru ditugaskan",
                message=f"{wo['code']} · {wo['title']}",
                href=f"/work-orders/{wo['_id']}",
                created_at=moment,
            )
        created += 1
    return created


def notify_upcoming_work_orders(now=None) -> int:
    moment = now or utcnow()
    due_soon = work_orders().find(
        {
            "status": {"$in": ["pending", "in_progress", "awaiting_review"]},
            "due_at": {"$gte": moment, "$lte": moment + timedelta(hours=24)},
            "assigned_to": {"$ne": None},
        },
        {"_id": 1, "assigned_to": 1, "code": 1, "title": 1, "due_at": 1},
    )
    count = 0
    for wo in due_soon:
        notify_user(
            str(wo["assigned_to"]),
            event_key=f"work-order-due:{wo['_id']}:{wo['due_at'].isoformat()}",
            title="Tenggat work order mendekat",
            message=f"{wo['code']} · {wo['title']}",
            href=f"/work-orders/{wo['_id']}",
        )
        count += 1
    return count


async def maintenance_scheduler_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(generate_due_preventive_work_orders)
            await asyncio.to_thread(notify_upcoming_work_orders)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Scheduler preventif atau notifikasi tenggat gagal")
        await asyncio.sleep(60)
