from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import STATIC_DIR, settings
from app.database import close_database, database_health, init_database
from app.routers import (
    admin,
    alerts,
    api,
    assets,
    auth,
    dashboard,
    monitoring,
    operations,
    reports,
    simulation,
    thresholds,
    users,
    work_orders,
)
from app.web import render_error

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cmms")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    simulator: asyncio.Task | None = None
    maintenance: asyncio.Task | None = None
    if settings.demo_telemetry:
        from app.services.telemetry import telemetry_loop

        simulator = asyncio.create_task(telemetry_loop())
    from app.services.maintenance import maintenance_scheduler_loop

    maintenance = asyncio.create_task(maintenance_scheduler_loop())
    log.info("CMMS Sentinel siap · database %s", settings.mongodb_db)
    yield
    if simulator:
        simulator.cancel()
        with suppress(asyncio.CancelledError):
            await simulator
    if maintenance:
        maintenance.cancel()
        with suppress(asyncio.CancelledError):
            await maintenance
    close_database()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(18)
        request = Request(scope)
        request.state.csp_nonce = nonce
        path = scope.get("path", "")
        is_static = path.startswith("/static/")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                if not is_static:
                    csp = (
                        "default-src 'self'; "
                        "base-uri 'self'; "
                        "object-src 'none'; "
                        "frame-ancestors 'none'; "
                        "form-action 'self'; "
                        "img-src 'self' data:; "
                        "font-src 'self'; "
                        "style-src 'self' 'unsafe-inline'; "
                        f"script-src 'self' 'nonce-{nonce}'; "
                        "connect-src 'self'"
                    )
                    header_map = {
                        "content-security-policy": csp,
                        "x-content-type-options": "nosniff",
                        "x-frame-options": "DENY",
                        "referrer-policy": "strict-origin-when-cross-origin",
                        "permissions-policy": "camera=(), microphone=(), geolocation=()",
                        "x-robots-tag": "noindex, nofollow",
                    }
                    if settings.session_https_only and scope.get("scheme") == "https":
                        header_map["strict-transport-security"] = "max-age=31536000; includeSubDomains"
                    existing = {key.decode("latin-1").lower() for key, _ in headers}
                    for key, value in header_map.items():
                        if key not in existing:
                            headers.append((key.encode("latin-1"), value.encode("latin-1")))
                    content_type = ""
                    for key, value in headers:
                        if key.decode("latin-1").lower() == "content-type":
                            content_type = value.decode("latin-1")
                    if content_type.startswith("text/html"):
                        if "cache-control" not in existing:
                            headers.append((b"cache-control", b"no-store, max-age=0"))
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.session_https_only,
)
app.add_middleware(GZipMiddleware, minimum_size=1500)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(monitoring.router)
app.include_router(assets.router)
app.include_router(thresholds.router)
app.include_router(work_orders.router)
app.include_router(operations.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(simulation.router)
app.include_router(users.router)
app.include_router(admin.router)
app.include_router(api.router)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    location = (exc.headers or {}).get("Location")
    if exc.status_code in {301, 302, 303, 307, 308} and location:
        return RedirectResponse(location, status_code=exc.status_code)
    if _is_api(request):
        return JSONResponse(
            {"ok": False, "detail": exc.detail or "Permintaan tidak dapat diproses."},
            status_code=exc.status_code,
        )
    detail = exc.detail if isinstance(exc.detail, str) else "Permintaan tidak dapat diproses."
    titles = {
        400: "Permintaan Tidak Valid",
        401: "Autentikasi Diperlukan",
        403: "Akses Ditolak",
        404: "Halaman Tidak Ditemukan",
        405: "Metode Tidak Diizinkan",
    }
    return render_error(
        request,
        exc.status_code if exc.status_code in {400, 403, 404} else 400,
        titles.get(exc.status_code, "Terjadi Kesalahan"),
        detail,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if _is_api(request):
        return JSONResponse({"ok": False, "detail": "Payload tidak valid.", "errors": exc.errors()}, status_code=422)
    return render_error(
        request,
        400,
        "Data Formulir Tidak Valid",
        "Beberapa isian tidak sesuai. Kembali ke halaman sebelumnya dan periksa kembali data Anda.",
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error pada %s", request.url.path)
    if _is_api(request):
        return JSONResponse({"ok": False, "detail": "Terjadi kesalahan internal."}, status_code=500)
    return render_error(
        request,
        500,
        "Kesalahan Sistem",
        "Terjadi kesalahan yang tidak terduga. Tim operasional telah dicatat melalui log aplikasi.",
    )


@app.get("/health", tags=["system"])
def health():
    db = database_health()
    status_code = 200 if db["ok"] else 503
    return JSONResponse(
        {
            "ok": db["ok"],
            "app": settings.app_name,
            "version": settings.app_version,
            "database": db["database"],
            "environment": settings.app_env,
        },
        status_code=status_code,
    )
