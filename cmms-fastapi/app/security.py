from __future__ import annotations

import hmac
import re
import secrets
from datetime import timedelta
from urllib.parse import quote

import bcrypt
from bson import ObjectId
from fastapi import HTTPException, Request

from app.database import login_attempts, users
from app.utils import ROLE_LABELS, initials, utcnow

PASSWORD_MIN_LENGTH = 10
LOGIN_WINDOW_SECONDS = 600
MAX_LOGIN_FAILURES = 6


def hash_password(raw: str) -> str:
    if len(raw.encode("utf-8")) > 72:
        raise ValueError("Password maksimal 72 byte")
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_error(raw: str) -> str | None:
    if len(raw) < PASSWORD_MIN_LENGTH:
        return f"Password minimal {PASSWORD_MIN_LENGTH} karakter."
    if len(raw.encode("utf-8")) > 72:
        return "Password maksimal 72 byte."
    if not re.search(r"[A-Za-z]", raw) or not re.search(r"\d", raw):
        return "Password harus memuat huruf dan angka."
    return None


def csrf_token(request: Request) -> str:
    token = request.session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["_csrf"] = token
    return token


def check_csrf(request: Request, provided: str | None) -> None:
    expected = request.session.get("_csrf", "")
    if not expected or not provided or not hmac.compare_digest(str(provided), str(expected)):
        raise HTTPException(
            status_code=400,
            detail="Token keamanan formulir tidak valid atau kedaluwarsa. Muat ulang halaman lalu coba lagi.",
        )


def login_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{email.strip().lower()}"


def login_is_limited(request: Request, email: str) -> bool:
    key = login_key(request, email)
    since = utcnow() - timedelta(seconds=LOGIN_WINDOW_SECONDS)
    count = login_attempts().count_documents({"key": key, "ts": {"$gte": since}})
    return count >= MAX_LOGIN_FAILURES


def record_login_failure(request: Request, email: str) -> None:
    login_attempts().insert_one({"key": login_key(request, email), "ts": utcnow()})


def clear_login_failures(request: Request, email: str) -> None:
    login_attempts().delete_many({"key": login_key(request, email)})


def user_view(doc: dict | None) -> dict | None:
    if not doc:
        return None
    user = dict(doc)
    user["id"] = str(user.pop("_id"))
    user["initials"] = initials(user.get("nama_lengkap"))
    user["role_label"] = ROLE_LABELS.get(user.get("role", ""), user.get("role", "—"))
    return user


def get_optional_user(request: Request) -> dict | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    try:
        doc = users().find_one({"_id": ObjectId(str(uid)), "active": True})
    except Exception:
        request.session.clear()
        return None
    if not doc:
        request.session.pop("uid", None)
        return None
    return user_view(doc)


def require_user(request: Request) -> dict:
    user = get_optional_user(request)
    if not user:
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query
        raise HTTPException(status_code=303, headers={"Location": f"/login?next={quote(target, safe='')}"})
    return user


def require_admin(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Halaman ini hanya dapat diakses oleh Administrator.")
    return user


def is_admin(user: dict | None) -> bool:
    return bool(user and user.get("role") == "admin")


def flash(request: Request, tone: str, message: str) -> None:
    items = request.session.setdefault("_flash", [])
    items.append({"tone": tone, "message": message})
    request.session["_flash"] = items


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("_flash", [])
