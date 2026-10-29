from __future__ import annotations

import re

from bson import ObjectId
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pymongo.errors import DuplicateKeyError

from app.database import users, work_orders
from app.security import (
    check_csrf,
    flash,
    hash_password,
    password_error,
    require_admin,
    require_user,
    user_view,
    verify_password,
)
from app.services.audit import audit
from app.utils import ROLE_LABELS, utcnow
from app.web import render

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = {"admin", "teknisi"}


def _get_user(user_id: str) -> dict:
    try:
        doc = users().find_one({"_id": ObjectId(user_id)})
    except Exception:
        doc = None
    if not doc:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    return doc


def _form_values(doc: dict | None = None) -> dict:
    if not doc:
        return {"nama_lengkap": "", "email": "", "role": "teknisi", "active": True}
    return {
        "nama_lengkap": doc.get("nama_lengkap", ""),
        "email": doc.get("email", ""),
        "role": doc.get("role", "teknisi"),
        "active": bool(doc.get("active", True)),
    }


def _active_admin_count(exclude_id: ObjectId | None = None) -> int:
    query = {"role": "admin", "active": True}
    if exclude_id:
        query["_id"] = {"$ne": exclude_id}
    return users().count_documents(query)


def _validate(form: dict, *, current: dict | None = None) -> list[str]:
    errors: list[str] = []
    if not 2 <= len(form["nama_lengkap"]) <= 80:
        errors.append("Nama lengkap wajib 2–80 karakter.")
    if not EMAIL_RE.fullmatch(form["email"]):
        errors.append("Format email tidak valid.")
    else:
        existing = users().find_one({"email": form["email"]})
        if existing and (not current or existing["_id"] != current["_id"]):
            errors.append("Email sudah digunakan pengguna lain.")
    if form["role"] not in ROLES:
        errors.append("Peran pengguna tidak valid.")
    return errors


def _summary() -> dict:
    return {
        "total": users().count_documents({}),
        "admins": users().count_documents({"role": "admin", "active": True}),
        "technicians": users().count_documents({"role": "teknisi", "active": True}),
        "inactive": users().count_documents({"active": False}),
    }


@router.get("/users")
def users_page(
    request: Request,
    q: str = Query("", max_length=80),
    role: str = Query("", max_length=20),
    active: str = Query("", max_length=5),
):
    current = require_admin(request)
    query: dict = {}
    if role in ROLES:
        query["role"] = role
    if active in {"1", "0"}:
        query["active"] = active == "1"
    needle = q.strip()
    if needle:
        pattern = {"$regex": re.escape(needle), "$options": "i"}
        query["$or"] = [{"nama_lengkap": pattern}, {"email": pattern}]
    assigned: dict[str, int] = {}
    for row in work_orders().aggregate(
        [
            {"$match": {"status": {"$in": ["pending", "in_progress"]}, "assigned_to": {"$ne": None}}},
            {"$group": {"_id": "$assigned_to", "count": {"$sum": 1}}},
        ]
    ):
        assigned[str(row["_id"])] = row["count"]
    docs = list(users().find(query).sort([("role", 1), ("nama_lengkap", 1)]))
    items = []
    for doc in docs:
        item = user_view(doc)
        item["open_assignments"] = assigned.get(item["id"], 0)
        items.append(item)
    return render(
        request,
        "users/index.html",
        user=current,
        active_page="users",
        items=items,
        summary=_summary(),
        filters={"q": needle, "role": role, "active": active},
    )


@router.get("/users/new")
def user_new(request: Request):
    current = require_admin(request)
    return render(
        request,
        "users/form.html",
        user=current,
        active_page="users",
        active_page_title="Pengguna baru",
        mode="new",
        target=None,
        form=_form_values(),
        error=None,
    )


@router.post("/users")
async def user_create(request: Request, csrf_token: str = Form("")):
    current = require_admin(request)
    check_csrf(request, csrf_token)
    raw = dict(await request.form())
    form = {
        "nama_lengkap": raw.get("nama_lengkap", "").strip(),
        "email": raw.get("email", "").strip().lower(),
        "role": raw.get("role", "teknisi"),
        "active": True,
    }
    errors = _validate(form)
    pw_error = password_error(raw.get("password", ""))
    if pw_error:
        errors.append(pw_error)
    if errors:
        return render(
            request,
            "users/form.html",
            user=current,
            active_page="users",
            active_page_title="Pengguna baru",
            mode="new",
            target=None,
            form=form,
            error=" ".join(errors[:3]),
            status_code=400,
        )
    now = utcnow()
    doc = {
        **form,
        "password_hash": hash_password(raw.get("password", "")),
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }
    try:
        inserted = users().insert_one(doc)
    except DuplicateKeyError:
        return render(
            request,
            "users/form.html",
            user=current,
            active_page="users",
            active_page_title="Pengguna baru",
            mode="new",
            target=None,
            form=form,
            error="Email sudah digunakan pengguna lain.",
            status_code=400,
        )
    audit(
        current,
        "Menambah pengguna",
        "user",
        inserted.inserted_id,
        f"{form['email']} · {ROLE_LABELS.get(form['role'], form['role'])} ditambahkan.",
        request,
    )
    flash(request, "success", f"Pengguna {form['nama_lengkap']} berhasil ditambahkan.")
    return RedirectResponse("/users", status_code=303)


@router.get("/users/{user_id}/edit")
def user_edit(request: Request, user_id: str):
    current = require_admin(request)
    target = _get_user(user_id)
    return render(
        request,
        "users/form.html",
        user=current,
        active_page="users",
        active_page_title=f"Edit {target.get('nama_lengkap')}",
        mode="edit",
        target=user_view(target),
        form=_form_values(target),
        error=None,
    )


@router.post("/users/{user_id}")
async def user_update(request: Request, user_id: str, csrf_token: str = Form("")):
    current = require_admin(request)
    check_csrf(request, csrf_token)
    target = _get_user(user_id)
    raw = dict(await request.form())
    form = {
        "nama_lengkap": raw.get("nama_lengkap", "").strip(),
        "email": raw.get("email", "").strip().lower(),
        "role": raw.get("role", target.get("role")),
        "active": "active" in raw,
    }
    errors = _validate(form, current=target)
    is_self = str(target["_id"]) == current["id"]
    if is_self and not form["active"]:
        errors.append("Anda tidak dapat menonaktifkan akun sendiri.")
    if is_self and form["role"] != "admin":
        errors.append("Anda tidak dapat menurunkan peran akun sendiri.")
    if (
        target.get("role") == "admin"
        and target.get("active", True)
        and (form["role"] != "admin" or not form["active"])
        and _active_admin_count(exclude_id=target["_id"]) == 0
    ):
        errors.append("Minimal harus ada satu Administrator aktif.")
    new_password = raw.get("password", "")
    if new_password:
        pw_error = password_error(new_password)
        if pw_error:
            errors.append(pw_error)
    if errors:
        return render(
            request,
            "users/form.html",
            user=current,
            active_page="users",
            active_page_title=f"Edit {target.get('nama_lengkap')}",
            mode="edit",
            target=user_view(target),
            form=form,
            error=" ".join(errors[:3]),
            status_code=400,
        )
    updates = {**form, "updated_at": utcnow()}
    if new_password:
        updates["password_hash"] = hash_password(new_password)
    users().update_one({"_id": target["_id"]}, {"$set": updates})
    audit(
        current,
        "Memperbarui pengguna",
        "user",
        target["_id"],
        f"Akun {target.get('email')} diperbarui.",
        request,
    )
    flash(request, "success", f"Data pengguna {form['nama_lengkap']} berhasil diperbarui.")
    return RedirectResponse("/users", status_code=303)


@router.get("/profile")
def profile_page(request: Request):
    current = require_user(request)
    recent = list(
        work_orders()
        .find({"assigned_to": ObjectId(current["id"])})
        .sort("created_at", -1)
        .limit(5)
    )
    for item in recent:
        item["id"] = str(item.pop("_id"))
    return render(
        request,
        "users/profile.html",
        user=current,
        active_page="profile",
        recent_orders=recent,
        open_assignments=work_orders().count_documents(
            {"assigned_to": ObjectId(current["id"]), "status": {"$in": ["pending", "in_progress"]}}
        ),
    )


@router.post("/profile")
async def profile_update(request: Request, csrf_token: str = Form("")):
    current = require_user(request)
    check_csrf(request, csrf_token)
    raw = dict(await request.form())
    name = raw.get("nama_lengkap", "").strip()
    if not 2 <= len(name) <= 80:
        flash(request, "error", "Nama lengkap wajib 2–80 karakter.")
        return RedirectResponse("/profile", status_code=303)
    users().update_one(
        {"_id": ObjectId(current["id"])},
        {"$set": {"nama_lengkap": name, "updated_at": utcnow()}},
    )
    audit(current, "Memperbarui profil", "user", current["id"], "Nama profil diperbarui.", request)
    flash(request, "success", "Profil berhasil diperbarui.")
    return RedirectResponse("/profile", status_code=303)


@router.post("/profile/password")
async def profile_password(request: Request, csrf_token: str = Form("")):
    current = require_user(request)
    check_csrf(request, csrf_token)
    raw = dict(await request.form())
    current_password = raw.get("current_password", "")
    new_password = raw.get("new_password", "")
    confirm = raw.get("confirm_password", "")
    doc = users().find_one({"_id": ObjectId(current["id"])})
    if not doc or not verify_password(current_password, doc.get("password_hash", "")):
        flash(request, "error", "Password saat ini tidak sesuai.")
        return RedirectResponse("/profile", status_code=303)
    if new_password != confirm:
        flash(request, "error", "Konfirmasi password baru tidak sama.")
        return RedirectResponse("/profile", status_code=303)
    if new_password == current_password:
        flash(request, "error", "Password baru harus berbeda dari password saat ini.")
        return RedirectResponse("/profile", status_code=303)
    pw_error = password_error(new_password)
    if pw_error:
        flash(request, "error", pw_error)
        return RedirectResponse("/profile", status_code=303)
    users().update_one(
        {"_id": doc["_id"]},
        {"$set": {"password_hash": hash_password(new_password), "updated_at": utcnow()}},
    )
    audit(current, "Mengubah password", "user", doc["_id"], "Password akun diperbarui.", request)
    flash(request, "success", "Password berhasil diperbarui.")
    return RedirectResponse("/profile", status_code=303)
