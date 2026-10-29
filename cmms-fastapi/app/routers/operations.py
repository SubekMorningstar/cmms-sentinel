from __future__ import annotations

from datetime import datetime, timedelta

from bson import ObjectId
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.database import (
    inventory_items,
    machines,
    maintenance_plans,
    notifications,
    simulation_runs,
    users,
    work_orders,
)
from app.security import check_csrf, flash, is_admin, require_user
from app.services.audit import audit
from app.services.maintenance import generate_due_preventive_work_orders, is_virtual_machine
from app.services.notifications import notify_user
from app.services.work_orders import create_work_order
from pymongo.errors import DuplicateKeyError
from app.utils import TZ, utcnow
from app.web import render

router = APIRouter()


def _admin(user: dict) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Halaman ini hanya dapat diakses Administrator.")


def _machine_list() -> list[dict]:
    return list(machines().find({"active": True}).sort("code", 1))


@router.get("/schedule")
def schedule_page(request: Request):
    user = require_user(request)
    _admin(user)
    now = utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    queue = list(
        work_orders()
        .find({"status": {"$in": ["pending", "in_progress", "awaiting_review"]}})
        .sort([("due_at", 1), ("priority", 1)])
        .limit(100)
    )
    technicians = list(users().find({"active": True, "role": "teknisi"}).sort("nama_lengkap", 1))
    for tech in technicians:
        query = {"assigned_to": tech["_id"], "status": {"$in": ["pending", "in_progress", "awaiting_review"]}}
        tech["open_count"] = work_orders().count_documents(query)
        tech["week_count"] = work_orders().count_documents({**query, "due_at": {"$gte": start, "$lt": end}})
        tech["capacity_target"] = 5
    for wo in queue:
        wo["id"] = str(wo.pop("_id"))
        wo["is_overdue"] = wo.get("due_at") and wo["due_at"] < now
    return render(
        request,
        "operations/schedule.html",
        user=user,
        active_page="schedule",
        technicians=technicians,
        queue=queue,
        week_start=start,
        week_end=end,
    )


@router.get("/maintenance")
def maintenance_page(request: Request):
    user = require_user(request)
    _admin(user)
    generate_due_preventive_work_orders()
    plans = list(maintenance_plans().find({}).sort([("active", -1), ("next_due_at", 1)]))
    techs = list(users().find({"active": True, "role": "teknisi"}).sort("nama_lengkap", 1))
    return render(
        request,
        "operations/maintenance.html",
        user=user,
        active_page="maintenance",
        plans=plans,
        machines=_machine_list(),
        technicians=techs,
    )


@router.post("/maintenance/plans")
async def maintenance_plan_create(request: Request, csrf_token: str = Form("")):
    user = require_user(request)
    _admin(user)
    check_csrf(request, csrf_token)
    raw = dict(await request.form())
    name = raw.get("name", "").strip()
    machine_id = raw.get("machine_id", "").strip()
    title = raw.get("title", "").strip()
    description = raw.get("description", "").strip()
    checklist = [line.strip()[:160] for line in raw.get("checklist", "").splitlines() if line.strip()][:20]
    assigned_id = raw.get("assigned_to", "").strip()
    try:
        interval = int(raw.get("interval_days", ""))
        next_due = datetime.strptime(raw.get("next_due_at", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=TZ).astimezone(utcnow().tzinfo)
    except ValueError:
        interval = 0
        next_due = None
    machine_oid = ObjectId(machine_id) if ObjectId.is_valid(machine_id) else None
    assigned_oid = ObjectId(assigned_id) if ObjectId.is_valid(assigned_id) else None
    machine = machines().find_one({"_id": machine_oid, "active": True}) if machine_oid else None
    assigned = users().find_one({"_id": assigned_oid, "active": True, "role": "teknisi"}) if assigned_oid else None
    if next_due is None:
        machine = assigned = None
    if not machine or (assigned_id and not assigned) or not 1 <= interval <= 365 or not next_due or next_due < utcnow() - timedelta(hours=1):
        flash(request, "error", "Periksa mesin, teknisi, tanggal mulai, dan interval (1–365 hari).")
        return RedirectResponse("/maintenance", status_code=303)
    if not is_virtual_machine(machine["_id"]):
        flash(request, "error", "Rencana preventif simulasi hanya dapat dibuat untuk aset virtual tanpa telemetry gateway.")
        return RedirectResponse("/maintenance", status_code=303)
    if not 3 <= len(name) <= 120 or not 5 <= len(title) <= 140 or not 5 <= len(description) <= 2000:
        flash(request, "error", "Nama, judul, dan deskripsi rencana harus diisi dengan panjang yang valid.")
        return RedirectResponse("/maintenance", status_code=303)
    plan = {
        "name": name,
        "machine_id": machine["_id"],
        "machine_code": machine["code"],
        "machine_name": machine["name"],
        "title": title,
        "description": description,
        "checklist": checklist,
        "interval_days": interval,
        "priority": "medium",
        "assigned_to": assigned["_id"] if assigned else None,
        "assigned_name": assigned.get("nama_lengkap") if assigned else None,
        "next_due_at": next_due,
        "last_generated_at": None,
        "active": True,
        "created_at": utcnow(),
        "created_by": user["id"],
    }
    result = maintenance_plans().insert_one(plan)
    audit(user, "Membuat jadwal preventif", "maintenance_plan", result.inserted_id, f"{name} · {machine['code']} setiap {interval} hari.", request)
    flash(request, "success", "Jadwal pemeliharaan preventif berhasil dibuat.")
    return RedirectResponse("/maintenance", status_code=303)


@router.post("/maintenance/plans/{plan_id}/toggle")
def maintenance_plan_toggle(request: Request, plan_id: str, csrf_token: str = Form("")):
    user = require_user(request)
    _admin(user)
    check_csrf(request, csrf_token)
    try:
        oid = ObjectId(plan_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan.")
    plan = maintenance_plans().find_one({"_id": oid})
    if not plan:
        raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan.")
    active = not plan.get("active", False)
    maintenance_plans().update_one({"_id": oid}, {"$set": {"active": active, "updated_at": utcnow()}})
    audit(user, "Mengubah jadwal preventif", "maintenance_plan", oid, f"{plan['name']} · {'aktif' if active else 'dijeda'}.", request)
    flash(request, "success", f"Jadwal {'diaktifkan' if active else 'dijeda'}.")
    return RedirectResponse("/maintenance", status_code=303)


@router.get("/inventory")
def inventory_page(request: Request):
    user = require_user(request)
    items = list(inventory_items().find({"active": True}).sort("name", 1))
    for item in items:
        item["low_stock"] = item.get("on_hand", 0) <= item.get("minimum", 0)
    return render(request, "operations/inventory.html", user=user, active_page="inventory", items=items)


@router.post("/inventory/items")
def inventory_item_create(
    request: Request,
    csrf_token: str = Form(""),
    part_code: str = Form(""),
    name: str = Form(""),
    unit: str = Form("unit"),
    on_hand: int = Form(0, ge=0, le=1_000_000),
    minimum: int = Form(0, ge=0, le=1_000_000),
):
    user = require_user(request)
    _admin(user)
    check_csrf(request, csrf_token)
    part_code = part_code.strip().upper()
    name = name.strip()
    unit = unit.strip()
    if not 2 <= len(part_code) <= 30 or not 2 <= len(name) <= 120 or not 1 <= len(unit) <= 20:
        flash(request, "error", "Kode, nama, dan satuan suku cadang tidak valid.")
        return RedirectResponse("/inventory", status_code=303)
    try:
        item = {
            "part_code": part_code,
            "name": name,
            "unit": unit,
            "on_hand": on_hand,
            "minimum": minimum,
            "active": True,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        result = inventory_items().insert_one(item)
    except DuplicateKeyError:
        flash(request, "error", "Kode suku cadang sudah digunakan.")
        return RedirectResponse("/inventory", status_code=303)
    audit(user, "Menambahkan suku cadang", "inventory_item", result.inserted_id, f"{part_code} · {name}.", request)
    flash(request, "success", f"Suku cadang {part_code} ditambahkan.")
    return RedirectResponse("/inventory", status_code=303)


@router.post("/inventory/items/{item_id}/adjust")
def inventory_adjust(
    request: Request,
    item_id: str,
    csrf_token: str = Form(""),
    change: int = Form(..., ge=-100000, le=100000),
):
    user = require_user(request)
    _admin(user)
    check_csrf(request, csrf_token)
    if change == 0:
        flash(request, "error", "Masukkan perubahan stok selain nol.")
        return RedirectResponse("/inventory", status_code=303)
    try:
        oid = ObjectId(item_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Suku cadang tidak ditemukan.")
    item = inventory_items().find_one({"_id": oid, "active": True})
    if not item:
        raise HTTPException(status_code=404, detail="Suku cadang tidak ditemukan.")
    result = inventory_items().update_one(
        {"_id": oid, "on_hand": {"$gte": max(-change, 0)}},
        {"$inc": {"on_hand": change}, "$set": {"updated_at": utcnow()}},
    )
    if not result.modified_count:
        flash(request, "error", "Jumlah stok tidak dapat dikurangi melebihi stok tersedia.")
    else:
        audit(user, "Menyesuaikan stok", "inventory_item", oid, f"{item['part_code']} · perubahan {change:+d}.", request)
        flash(request, "success", f"Stok {item['part_code']} diperbarui.")
    return RedirectResponse("/inventory", status_code=303)


@router.get("/notifications")
def notifications_page(request: Request):
    user = require_user(request)
    rows = list(
        notifications()
        .find({"user_id": user["id"]})
        .sort([("read_at", 1), ("created_at", -1)])
        .limit(100)
    )
    for item in rows:
        item["id"] = str(item.pop("_id"))
    return render(request, "operations/notifications.html", user=user, active_page="notifications", items=rows)


@router.post("/notifications/{notification_id}/read")
def notification_read(request: Request, notification_id: str, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    try:
        oid = ObjectId(notification_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Notifikasi tidak ditemukan.")
    notifications().update_one(
        {"_id": oid, "user_id": user["id"], "read_at": None},
        {"$set": {"read_at": utcnow()}},
    )
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/read-all")
def notifications_read_all(request: Request, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    notifications().update_many(
        {"user_id": user["id"], "read_at": None},
        {"$set": {"read_at": utcnow()}},
    )
    flash(request, "success", "Semua notifikasi ditandai telah dibaca.")
    return RedirectResponse("/notifications", status_code=303)


@router.get("/simulation/compare")
def simulation_compare(request: Request, runs: list[str] = Query(default=[])):
    user = require_user(request)
    _admin(user)
    run_ids = [item for item in runs if len(item) <= 64][:4]
    selected = list(simulation_runs().find({"run_id": {"$in": run_ids}}).sort("created_at", -1)) if run_ids else []
    recent = list(
        simulation_runs()
        .find({}, {"_id": 0})
        .sort("created_at", -1)
        .limit(12)
    )
    for run in selected:
        run["id"] = run.get("run_id")
    return render(
        request,
        "operations/experiment_compare.html",
        user=user,
        active_page="simulation",
        runs=selected,
        recent=recent,
        selected_ids=run_ids,
    )
