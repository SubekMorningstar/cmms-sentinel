from __future__ import annotations

import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.config import settings
from app.database import users
from app.security import (
    check_csrf,
    clear_login_failures,
    flash,
    get_optional_user,
    login_is_limited,
    record_login_failure,
    require_user,
    verify_password,
)
from app.services.audit import audit
from app.utils import safe_next, utcnow
from app.web import render

router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _demo_accounts() -> list[dict[str, str]]:
    if not settings.show_demo_credentials:
        return []
    return [
        {"role": "Administrator", "email": settings.seed_admin_email, "password": settings.seed_admin_password},
        {"role": "Teknisi", "email": settings.seed_teknisi_email, "password": settings.seed_teknisi_password},
    ]


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    if get_optional_user(request):
        return RedirectResponse("/dashboard", status_code=303)
    return render(
        request,
        "auth/login.html",
        error=None,
        email="",
        next_url=safe_next(next),
        demo_accounts=_demo_accounts(),
        body_class="login-page",
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
    next: str = Form("/dashboard"),
):
    check_csrf(request, csrf_token)
    email = email.strip().lower()
    next_url = safe_next(next)
    if login_is_limited(request, email):
        return render(
            request,
            "auth/login.html",
            error="Terlalu banyak percobaan login. Coba lagi dalam 10 menit.",
            email=email,
            next_url=next_url,
            demo_accounts=_demo_accounts(),
            body_class="login-page",
            status_code=429,
        )
    if not email or not EMAIL_RE.fullmatch(email) or not password:
        record_login_failure(request, email)
        return render(
            request,
            "auth/login.html",
            error="Email atau password tidak valid.",
            email=email,
            next_url=next_url,
            demo_accounts=_demo_accounts(),
            body_class="login-page",
            status_code=401,
        )
    user = users().find_one({"email": email, "active": True})
    if not user or not verify_password(password, user.get("password_hash", "")):
        record_login_failure(request, email)
        return render(
            request,
            "auth/login.html",
            error="Email atau password salah.",
            email=email,
            next_url=next_url,
            demo_accounts=_demo_accounts(),
            body_class="login-page",
            status_code=401,
        )
    request.session.clear()
    request.session["uid"] = str(user["_id"])
    clear_login_failures(request, email)
    users().update_one({"_id": user["_id"]}, {"$set": {"last_login_at": utcnow()}})
    actor = {
        "id": str(user["_id"]),
        "nama_lengkap": user.get("nama_lengkap"),
        "role": user.get("role"),
    }
    audit(actor, "Login berhasil", "auth", user["_id"], f"Masuk sebagai {user.get('role')}.", request)
    flash(request, "success", f"Selamat datang, {user.get('nama_lengkap')}.")
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form("")):
    check_csrf(request, csrf_token)
    user = require_user(request)
    audit(user, "Logout", "auth", user.get("id"), "Pengguna keluar dari aplikasi.", request)
    request.session.clear()
    flash(request, "success", "Anda telah keluar dari aplikasi.")
    return RedirectResponse("/login", status_code=303)
