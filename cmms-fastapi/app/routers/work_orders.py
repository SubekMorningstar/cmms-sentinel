from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from bson import ObjectId
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.database import alerts, inventory_items, machines, users, work_orders
from app.security import check_csrf, flash, is_admin, require_user
from app.services.audit import audit
from app.services.notifications import notify_role, notify_user
from app.services.work_orders import (
    DEFAULT_CHECKLIST,
    STATUS_FLOW,
    add_activity,
    create_work_order,
    next_due_options,
    transition,
)
from app.utils import PRIORITY, TZ, WO_TYPE, utcnow
from app.web import render

router = APIRouter()
PAGE_SIZE = 12
STATUS_LABELS = {
    "pending": "Menunggu",
    "in_progress": "Dikerjakan",
    "awaiting_review": "Menunggu tinjauan",
    "resolved": "Selesai",
    "cancelled": "Dibatalkan",
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


def _machine_choices() -> list[dict]:
    return list(machines().find({}).sort([("active", -1), ("code", 1)]))


def _assignees(user: dict) -> list[dict]:
    query = {"active": True, "role": "teknisi"}
    if not is_admin(user):
        query["_id"] = ObjectId(user["id"])
    return list(users().find(query).sort("nama_lengkap", 1))


def _form_context(request: Request, user: dict) -> dict:
    due_options = next_due_options()
    return {
        "user": user,
        "active_page": "work_orders",
        "machines": _machine_choices(),
        "assignees": _assignees(user),
        "due_options": [
            ("4h", "4 jam", due_options["4h"]),
            ("24h", "24 jam", due_options["24h"]),
            ("72h", "3 hari", due_options["72h"]),
            ("7d", "7 hari", due_options["7d"]),
        ],
        "status_labels": STATUS_LABELS,
    }


def _default_form(user: dict, machine_code: str | None = None) -> dict:
    assignees = _assignees(user)
    return {
        "machine_id": "",
        "machine_code": machine_code or "",
        "title": "",
        "description": "",
        "priority": "medium",
        "type": "corrective",
        "assigned_to": assignees[0]["_id"] if len(assignees) == 1 else "",
        "due": "24h",
        "due_custom": "",
    }


def _summary(user: dict) -> dict:
    active_filter = {"status": {"$in": ["pending", "in_progress", "awaiting_review"]}}
    if not is_admin(user):
        active_filter["assigned_to"] = ObjectId(user["id"])
    now = utcnow()
    return {
        "active": work_orders().count_documents(active_filter),
        "overdue": work_orders().count_documents({**active_filter, "due_at": {"$lt": now}}),
        "critical": work_orders().count_documents({**active_filter, "priority": "critical"}),
        "review": work_orders().count_documents(
            {"status": "awaiting_review"} if is_admin(user) else {
                "status": "awaiting_review",
                "assigned_to": ObjectId(user["id"]),
            }
        ),
        "resolved_7d": work_orders().count_documents(
            {"status": "resolved", "resolved_at": {"$gte": now - timedelta(days=7)}}
        ),
        "automatic": work_orders().count_documents({**active_filter, "source": "automatic"}),
    }


@router.get("/work-orders")
def work_orders_page(
    request: Request,
    status: str = Query("active", max_length=20),
    priority: str = Query("", max_length=20),
    type: str = Query("", max_length=20),
    machine: str = Query("", max_length=40),
    simulation_run_id: str = Query("", max_length=16),
    assigned_to: str = Query("", max_length=32),
    q: str = Query("", max_length=80),
    page: int = Query(1, ge=1, le=10000),
):
    user = require_user(request)
    query: dict = {}
    if status == "active":
        query["status"] = {"$in": ["pending", "in_progress", "awaiting_review"]}
    elif status == "overdue":
        query["status"] = {"$in": ["pending", "in_progress", "awaiting_review"]}
        query["due_at"] = {"$lt": utcnow()}
    elif status in STATUS_LABELS:
        query["status"] = status
    elif status == "review":
        query["status"] = "awaiting_review"
    if not is_admin(user):
        query["assigned_to"] = ObjectId(user["id"])
    elif assigned_to:
        try:
            query["assigned_to"] = ObjectId(assigned_to)
        except Exception:
            query["assigned_to"] = None
    if priority in PRIORITY:
        query["priority"] = priority
    if type in WO_TYPE:
        query["type"] = type
    if machine:
        query["machine_code"] = machine
    if re.fullmatch(r"[a-f0-9]{16}", simulation_run_id):
        query["simulation_run_id"] = simulation_run_id
    needle = q.strip()
    if needle:
        pattern = {"$regex": re.escape(needle), "$options": "i"}
        query["$or"] = [
            {"code": pattern},
            {"title": pattern},
            {"machine_code": pattern},
            {"machine_name": pattern},
            {"assigned_name": pattern},
        ]
    total = work_orders().count_documents(query)
    pages = max(math.ceil(total / PAGE_SIZE), 1)
    page = min(page, pages)
    if status in {"resolved", "cancelled", "all"}:
        ordering = [("created_at", -1)]
    elif status == "overdue":
        ordering = [("due_at", 1)]
    else:
        ordering = [("due_at", 1), ("priority", 1)]
    docs = list(
        work_orders()
        .find(query)
        .sort(ordering)
        .skip((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    now = utcnow()
    machine_by_id = {
        item["_id"]: item
        for item in machines().find(
            {"_id": {"$in": [doc.get("machine_id") for doc in docs if doc.get("machine_id")]}},
            {"location": 1},
        )
    }
    items = []
    for doc in docs:
        item = dict(doc)
        item["id"] = str(item.pop("_id"))
        item["is_overdue"] = bool(
            item.get("due_at")
            and item["due_at"] < now
            and item.get("status") in {"pending", "in_progress", "awaiting_review"}
        )
        item["machine_location"] = machine_by_id.get(item.get("machine_id"), {}).get("location", "—")
        for activity in item.get("activities", []):
            activity.pop("_id", None)
        items.append(item)
    params = {
        key: value
        for key, value in {
            "status": status,
            "priority": priority,
            "type": type,
            "machine": machine,
            "simulation_run_id": simulation_run_id,
            "assigned_to": assigned_to if is_admin(user) else "",
            "q": needle,
        }.items()
        if value
    }
    base_qs = urlencode(params)
    return render(
        request,
        "work_orders/index.html",
        user=user,
        active_page="work_orders",
        items=items,
        summary=_summary(user),
        filters={
            "status": status,
            "priority": priority,
            "type": type,
            "machine": machine,
            "simulation_run_id": simulation_run_id,
            "assigned_to": assigned_to if is_admin(user) else "",
            "q": needle,
        },
        machines=_machine_choices(),
        status_labels=STATUS_LABELS,
        pagination={
            "page": page,
            "pages": pages,
            "total": total,
            "per_page": PAGE_SIZE,
            "numbers": _page_window(page, pages),
        },
        page_prefix="?" + base_qs + "&" if base_qs else "?",
    )


@router.get("/work-orders/new")
def work_order_new(request: Request, machine: str = Query("", max_length=40)):
    user = require_user(request)
    context = _form_context(request, user)
    form = _default_form(user, machine)
    if machine:
        match = next((item for item in context["machines"] if item.get("code") == machine and item.get("active")), None)
        if match:
            form["machine_id"] = str(match["_id"])
    elif context["machines"]:
        form["machine_id"] = str(context["machines"][0]["_id"])
    return render(
        request,
        "work_orders/form.html",
        mode="new",
        active_page_title="Work order baru",
        form=form,
        error=None,
        can_assign=is_admin(user),
        wo=None,
        **context,
    )


@router.post("/work-orders")
async def work_order_create(request: Request, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    context = _form_context(request, user)
    raw = dict(await request.form())
    form = {
        "machine_id": raw.get("machine_id", "").strip(),
        "machine_code": "",
        "title": raw.get("title", "").strip(),
        "description": raw.get("description", "").strip(),
        "priority": raw.get("priority", "medium"),
        "type": raw.get("type", "corrective"),
        "assigned_to": raw.get("assigned_to", "").strip(),
        "due": raw.get("due", "24h"),
        "due_custom": raw.get("due_custom", "").strip(),
        "checklist": raw.get("checklist", "").strip(),
    }
    errors: list[str] = []
    machine = None
    try:
        machine = machines().find_one({"_id": ObjectId(form["machine_id"]), "active": True})
    except Exception:
        machine = None
    if not machine:
        errors.append("Pilih mesin yang valid.")
    else:
        form["machine_code"] = machine.get("code", "")
    if not 5 <= len(form["title"]) <= 140:
        errors.append("Judul work order wajib 5–140 karakter.")
    if not 5 <= len(form["description"]) <= 2000:
        errors.append("Deskripsi pekerjaan wajib 5–2.000 karakter.")
    if len(form["checklist"]) > 1600 or len([line for line in form["checklist"].splitlines() if line.strip()]) > 20:
        errors.append("Checklist maksimal 20 langkah dan 1.600 karakter.")
    if form["priority"] not in PRIORITY:
        errors.append("Prioritas tidak valid.")
    if form["type"] not in WO_TYPE:
        errors.append("Jenis pekerjaan tidak valid.")
    assigned_doc = None
    if form["assigned_to"]:
        try:
            assigned_doc = users().find_one(
                {"_id": ObjectId(form["assigned_to"]), "active": True, "role": "teknisi"}
            )
        except Exception:
            assigned_doc = None
        if not assigned_doc:
            errors.append("Teknisi yang dipilih tidak valid.")
        elif not is_admin(user) and str(assigned_doc["_id"]) != user["id"]:
            errors.append("Anda hanya dapat menugaskan work order kepada diri sendiri.")
    elif not is_admin(user):
        assigned_doc = users().find_one({"_id": ObjectId(user["id"]), "active": True})
        form["assigned_to"] = user["id"]
    due_at = None
    if form["due"] == "custom":
        if not form["due_custom"]:
            errors.append("Tentukan tanggal tenggat khusus.")
        else:
            try:
                due_at = datetime.strptime(form["due_custom"], "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
                due_at = due_at.astimezone(utcnow().tzinfo)
                if due_at < utcnow() - timedelta(hours=1):
                    errors.append("Tenggat tidak boleh berada di masa lalu.")
            except ValueError:
                errors.append("Format tenggat khusus tidak valid.")
    else:
        due_at = next_due_options().get(form["due"])
        if not due_at:
            errors.append("Pilihan tenggat tidak valid.")
            due_at = next_due_options()["24h"]
    if errors:
        return render(
            request,
            "work_orders/form.html",
            mode="new",
            active_page_title="Work order baru",
            form=form,
            error=" ".join(errors[:3]),
            can_assign=is_admin(user),
            wo=None,
            status_code=400,
            **context,
        )
    wo = create_work_order(
        machine,
        title=form["title"],
        description=form["description"],
        priority=form["priority"],
        wo_type=form["type"],
        user=user,
        assigned_user=assigned_doc,
        due_at=due_at,
        source="manual",
        checklist=[line.strip() for line in form["checklist"].splitlines() if line.strip()],
    )
    if assigned_doc and str(assigned_doc["_id"]) != user["id"]:
        notify_user(
            str(assigned_doc["_id"]),
            event_key=f"work-order-assigned:{wo['_id']}",
            title="Work order baru ditugaskan",
            message=f"{wo['code']} · {wo['title']}",
            href=f"/work-orders/{wo['_id']}",
        )
    audit(
        user,
        "Membuat work order",
        "work_order",
        wo["_id"],
        f"{wo['code']} · {wo['title']} ({machine.get('code')}).",
        request,
    )
    flash(request, "success", f"Work order {wo['code']} berhasil dibuat.")
    return RedirectResponse(f"/work-orders/{wo['_id']}", status_code=303)


@router.get("/work-orders/{wo_id}")
def work_order_detail(request: Request, wo_id: str):
    user = require_user(request)
    wo = _get_wo(wo_id)
    assigned_raw = str(wo.get("assigned_to") or "")
    if not is_admin(user) and assigned_raw != user["id"]:
        raise HTTPException(status_code=403, detail="Work order ini bukan tugas Anda.")
    if not wo.get("checklist"):
        wo["checklist"] = [
            {"label": label, "done": False}
            for label in DEFAULT_CHECKLIST.get(wo.get("type"), DEFAULT_CHECKLIST["inspection"])
        ]
        work_orders().update_one({"_id": wo["_id"]}, {"$set": {"checklist": wo["checklist"]}})
    wo.setdefault("parts_used", [])
    machine = machines().find_one({"_id": wo["machine_id"]})
    if not machine:
        raise HTTPException(status_code=404, detail="Mesin terkait tidak ditemukan.")
    item = dict(wo)
    item["id"] = str(item.pop("_id"))
    for activity in item.get("activities", []):
        activity.pop("_id", None)
    related_alerts = list(alerts().find({"machine_id": wo["machine_id"]}).sort("last_seen", -1).limit(4))
    for alert in related_alerts:
        alert["id"] = str(alert.pop("_id"))
    can_act = is_admin(user) or assigned_raw == user["id"]
    allowed = sorted(STATUS_FLOW.get(wo.get("status"), set()))
    if not is_admin(user):
        allowed = [status for status in allowed if status not in {"resolved", "cancelled"}]
        if wo.get("status") == "awaiting_review":
            allowed = []
    elif wo.get("status") == "in_progress":
        allowed = [status for status in allowed if status != "awaiting_review"]
    return render(
        request,
        "work_orders/detail.html",
        user=user,
        active_page="work_orders",
        active_page_title=f"Work Order {item.get('code')}",
        wo=item,
        machine=machine,
        related_alerts=related_alerts,
        allowed_statuses=allowed,
        can_act=can_act,
        can_assign=is_admin(user),
        assignees=_assignees(user),
        status_labels=STATUS_LABELS,
        inventory_items=list(inventory_items().find({"active": True}).sort("name", 1)),
    )


@router.post("/work-orders/{wo_id}/status")
async def work_order_status(request: Request, wo_id: str, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    wo = _get_wo(wo_id)
    assigned_raw = str(wo.get("assigned_to") or "")
    if not is_admin(user) and assigned_raw and assigned_raw != user["id"]:
        raise HTTPException(status_code=403, detail="Work order ini ditugaskan kepada teknisi lain.")
    raw = dict(await request.form())
    next_status = raw.get("status", "").strip()
    notes = raw.get("notes", "").strip()
    if next_status not in STATUS_FLOW.get(wo.get("status"), set()):
        flash(request, "error", "Perubahan status tidak diizinkan dari status saat ini.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    if next_status == "cancelled" and not is_admin(user):
        raise HTTPException(status_code=403, detail="Hanya Administrator yang dapat membatalkan work order.")
    if next_status in {"resolved", "cancelled", "awaiting_review"} and len(notes) < 5:
        flash(request, "error", "Catatan hasil pekerjaan wajib diisi minimal 5 karakter.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    if len(notes) > 2000:
        flash(request, "error", "Catatan maksimal 2.000 karakter.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    downtime = None
    inspection_result = raw.get("inspection_result", "").strip()
    review_outcome = raw.get("review_outcome", "").strip()
    if next_status == "awaiting_review":
        if inspection_result not in {"completed", "issue_found", "follow_up"}:
            flash(request, "error", "Pilih hasil pemeriksaan sebelum mengirim pekerjaan untuk ditinjau.")
            return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
        if not wo.get("checklist") or any(not item.get("done") for item in wo.get("checklist", [])):
            flash(request, "error", "Selesaikan semua checklist sebelum mengirim work order untuk ditinjau.")
            return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    if next_status == "resolved":
        if not is_admin(user) or wo.get("status") != "awaiting_review":
            raise HTTPException(status_code=403, detail="Penyelesaian akhir hanya dapat disetujui admin setelah tinjauan.")
        if review_outcome not in {"confirmed_issue", "no_issue", "monitor"}:
            flash(request, "error", "Pilih hasil tinjauan admin.")
            return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    if next_status == "resolved":
        downtime_raw = str(raw.get("downtime_hours", "")).strip().replace(",", ".")
        try:
            downtime_hours = float(downtime_raw) if downtime_raw else 0.0
            if not 0 <= downtime_hours <= 720:
                raise ValueError
            downtime = int(round(downtime_hours * 60))
        except ValueError:
            flash(request, "error", "Durasi downtime harus berupa angka 0–720 jam.")
            return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    try:
        updated_wo = transition(
            wo,
            next_status,
            user=user,
            notes=notes,
            downtime_minutes=downtime,
            inspection_result=inspection_result or None,
            review_outcome=review_outcome or None,
        )
    except ValueError as exc:
        flash(request, "error", str(exc))
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    if next_status == "awaiting_review":
        notify_role(
            "admin",
            event_key=f"work-order-review:{wo['_id']}:{updated_wo['submitted_at'].isoformat()}",
            title="Work order menunggu tinjauan",
            message=f"{wo.get('code')} · {wo.get('title')}",
            href=f"/work-orders/{wo_id}",
            created_at=updated_wo["submitted_at"],
        )
    elif next_status == "in_progress" and wo.get("status") == "awaiting_review" and wo.get("assigned_to"):
        notify_user(
            str(wo["assigned_to"]),
            event_key=f"work-order-returned:{wo['_id']}:{updated_wo['review_returned_at'].isoformat()}",
            title="Work order dikembalikan untuk perbaikan",
            message=f"{wo.get('code')} · {wo.get('title')}",
            href=f"/work-orders/{wo_id}",
            created_at=updated_wo["review_returned_at"],
        )
    audit(
        user,
        f"Work order {STATUS_LABELS.get(next_status, next_status).lower()}",
        "work_order",
        wo["_id"],
        f"{wo.get('code')} diubah ke status {next_status}.",
        request,
    )
    flash(request, "success", f"Work order {wo.get('code')} diperbarui menjadi {STATUS_LABELS.get(next_status, next_status)}.")
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


@router.post("/work-orders/{wo_id}/assign")
def work_order_assign(
    request: Request,
    wo_id: str,
    csrf_token: str = Form(""),
    assigned_to: str = Form(""),
):
    user = require_user(request)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Hanya Administrator yang dapat mengubah penugasan.")
    check_csrf(request, csrf_token)
    wo = _get_wo(wo_id)
    if wo.get("status") in {"resolved", "cancelled"}:
        flash(request, "error", "Work order yang sudah selesai tidak dapat ditugaskan ulang.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    assigned_doc = None
    if assigned_to:
        try:
            assigned_doc = users().find_one({"_id": ObjectId(assigned_to), "active": True, "role": "teknisi"})
        except Exception:
            assigned_doc = None
        if not assigned_doc:
            flash(request, "error", "Teknisi yang dipilih tidak valid.")
            return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    previous_assignee = str(wo.get("assigned_to") or "")
    work_orders().update_one(
        {"_id": wo["_id"]},
        {
            "$set": {
                "assigned_to": assigned_doc["_id"] if assigned_doc else None,
                "assigned_name": assigned_doc.get("nama_lengkap") if assigned_doc else None,
                "updated_at": utcnow(),
            }
        },
    )
    if assigned_doc and str(assigned_doc["_id"]) != previous_assignee:
        notify_user(
            str(assigned_doc["_id"]),
            event_key=f"work-order-reassigned:{wo['_id']}:{str(assigned_doc['_id'])}:{utcnow().isoformat()}",
            title="Work order ditugaskan kepada Anda",
            message=f"{wo.get('code')} · {wo.get('title')}",
            href=f"/work-orders/{wo_id}",
        )
    add_activity(
        wo["_id"],
        actor=user.get("nama_lengkap", "Administrator"),
        action="assigned",
        status=wo.get("status", "pending"),
        note=f"Ditugaskan kepada {assigned_doc.get('nama_lengkap')}." if assigned_doc else "Penugasan dilepas.",
    )
    audit(
        user,
        "Mengubah penugasan",
        "work_order",
        wo["_id"],
        f"{wo.get('code')} → {assigned_doc.get('nama_lengkap') if assigned_doc else 'tanpa teknisi'}.",
        request,
    )
    flash(request, "success", "Penugasan work order berhasil diperbarui.")
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


@router.post("/work-orders/{wo_id}/note")
async def work_order_note(request: Request, wo_id: str, csrf_token: str = Form("")):
    user = require_user(request)
    check_csrf(request, csrf_token)
    wo = _get_wo(wo_id)
    if not is_admin(user) and str(wo.get("assigned_to") or "") != user["id"]:
        raise HTTPException(status_code=403, detail="Work order ini bukan tugas Anda.")
    if wo.get("status") in {"resolved", "cancelled"}:
        flash(request, "error", "Work order yang sudah ditutup tidak dapat ditambahi catatan.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    raw = dict(await request.form())
    note = raw.get("note", "").strip()
    if not 3 <= len(note) <= 1000:
        flash(request, "error", "Catatan wajib 3–1.000 karakter.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    add_activity(
        wo["_id"],
        actor=user.get("nama_lengkap", "Pengguna"),
        action="note",
        status=wo.get("status", "pending"),
        note=note,
    )
    flash(request, "success", "Catatan pekerjaan ditambahkan.")
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)

@router.post("/work-orders/{wo_id}/checklist/{item_index}")
def work_order_checklist(
    request: Request,
    wo_id: str,
    item_index: int,
    csrf_token: str = Form(""),
):
    user = require_user(request)
    check_csrf(request, csrf_token)
    wo = _get_wo(wo_id)
    if not is_admin(user) and str(wo.get("assigned_to") or "") != user["id"]:
        raise HTTPException(status_code=403, detail="Work order ini bukan tugas Anda.")
    checklist = wo.get("checklist", [])
    if wo.get("status") != "in_progress" or item_index < 0 or item_index >= len(checklist):
        flash(request, "error", "Checklist hanya dapat diperbarui pada pekerjaan yang sedang dikerjakan.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    done = not bool(checklist[item_index].get("done"))
    work_orders().update_one(
        {"_id": wo["_id"], "status": "in_progress"},
        {"$set": {f"checklist.{item_index}.done": done, "updated_at": utcnow()}},
    )
    add_activity(
        wo["_id"],
        actor=user.get("nama_lengkap", "Pengguna"),
        action="checklist",
        status=wo.get("status", "in_progress"),
        note=f"{'Selesai' if done else 'Dibatalkan'}: {checklist[item_index].get('label', 'Langkah kerja')}",
    )
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)

@router.post("/work-orders/{wo_id}/parts")
def work_order_consume_part(
    request: Request,
    wo_id: str,
    csrf_token: str = Form(""),
    part_id: str = Form(""),
    quantity: int = Form(1, ge=1, le=10000),
):
    user = require_user(request)
    check_csrf(request, csrf_token)
    wo = _get_wo(wo_id)
    if not is_admin(user) and str(wo.get("assigned_to") or "") != user["id"]:
        raise HTTPException(status_code=403, detail="Work order ini bukan tugas Anda.")
    if wo.get("status") != "in_progress":
        flash(request, "error", "Suku cadang hanya dapat dicatat pada pekerjaan yang sedang dikerjakan.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    try:
        item_id = ObjectId(part_id)
    except Exception:
        item_id = None
    item = inventory_items().find_one({"_id": item_id, "active": True}) if item_id else None
    if not item:
        flash(request, "error", "Pilih suku cadang yang tersedia.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    updated = inventory_items().update_one(
        {"_id": item["_id"], "on_hand": {"$gte": quantity}},
        {"$inc": {"on_hand": -quantity}, "$set": {"updated_at": utcnow()}},
    )
    if not updated.modified_count:
        flash(request, "error", f"Stok {item['part_code']} tidak mencukupi.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    usage = {
        "item_id": item["_id"],
        "part_code": item["part_code"],
        "name": item["name"],
        "quantity": quantity,
        "unit": item.get("unit", "unit"),
        "used_at": utcnow(),
        "used_by": user.get("nama_lengkap"),
    }
    recorded = work_orders().update_one(
        {"_id": wo["_id"], "status": "in_progress"},
        {"$push": {"parts_used": usage}},
    )
    if not recorded.modified_count:
        inventory_items().update_one(
            {"_id": item["_id"]},
            {"$inc": {"on_hand": quantity}, "$set": {"updated_at": utcnow()}},
        )
        flash(request, "error", "Status work order berubah; stok dikembalikan dan pemakaian tidak dicatat.")
        return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)
    add_activity(
        wo["_id"],
        actor=user.get("nama_lengkap", "Pengguna"),
        action="part_used",
        status=wo.get("status", "in_progress"),
        note=f"Digunakan {quantity} {item.get('unit', 'unit')} · {item['part_code']} {item['name']}.",
    )
    audit(
        user,
        "Mencatat pemakaian suku cadang",
        "work_order",
        wo["_id"],
        f"{quantity} {item.get('unit', 'unit')} · {item['part_code']} digunakan pada {wo.get('code')}.",
        request,
    )
    flash(request, "success", "Pemakaian suku cadang dicatat dan stok diperbarui.")
    return RedirectResponse(f"/work-orders/{wo_id}", status_code=303)


def _get_wo(wo_id: str) -> dict:
    try:
        wo = work_orders().find_one({"_id": ObjectId(wo_id)})
    except Exception:
        wo = None
    if not wo:
        raise HTTPException(status_code=404, detail="Work order tidak ditemukan.")
    return wo
