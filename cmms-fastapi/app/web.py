from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import TEMPLATES_DIR, settings
from app.database import alerts, machines, notifications as notification_collection, work_orders
from app.security import csrf_token, get_optional_user, is_admin, pop_flashes
from app.services.analytics import shift_label
from app.utils import (
    ALERT_LEVEL,
    ALERT_STATUS,
    CRITICALITY,
    MACHINE_STATUS,
    PRIORITY,
    ROLE_LABELS,
    SENSORS,
    SENSOR_ORDER,
    SOURCE_LABEL,
    WO_STATUS,
    WO_TYPE,
    badge_tone,
    format_date,
    format_dt,
    format_int,
    format_number,
    format_time,
    health_state,
    local_day_label,
    relative_time,
    sensor_meta,
    sensor_score,
    sensor_state,
    status_label,
    to_local,
    utcnow,
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

templates.env.filters.update(
    {
        "dt": format_dt,
        "date_only": format_date,
        "time_only": format_time,
        "relative": relative_time,
        "num": format_number,
        "intnum": format_int,
        "sensor_meta": sensor_meta,
        "state": sensor_state,
        "health": health_state,
        "label": status_label,
        "tone": badge_tone,
        "score": sensor_score,
        "date_input": lambda value: to_local(value).strftime("%Y-%m-%d") if value else "",
        "local_day": local_day_label,
    }
)

templates.env.globals.update(
    {
        "sensors": SENSORS,
        "sensor_order": SENSOR_ORDER,
        "status_maps": {
            "wo_status": WO_STATUS,
            "priority": PRIORITY,
            "alert_status": ALERT_STATUS,
            "alert_level": ALERT_LEVEL,
            "machine_status": MACHINE_STATUS,
            "criticality": CRITICALITY,
            "wo_type": WO_TYPE,
            "role": ROLE_LABELS,
            "source": SOURCE_LABEL,
        },
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "year": utcnow().year,
        "nav_labels": {
            "dashboard": "Pusat Operasi",
            "monitoring": "Condition Monitoring",
            "alerts": "Pusat Peringatan",
            "work_orders": "Work Order",
            "reports": "Laporan & Analitik",
            "assets": "Aset & Mesin",
            "thresholds": "Threshold Sensor",
            "users": "Pengguna",
            "audit": "Audit Trail",
            "integration": "Integrasi & Dataset",
            "simulation": "Laboratorium Simulasi",
            "schedule": "Penjadwalan Teknisi",
            "maintenance": "Pemeliharaan Preventif",
            "inventory": "Persediaan Suku Cadang",
            "notifications": "Notifikasi",
            "profile": "Profil Saya",
        },
        "nav_urls": {
            "dashboard": "/dashboard",
            "monitoring": "/cbm-monitoring",
            "alerts": "/alerts",
            "work_orders": "/work-orders",
            "reports": "/reports",
            "assets": "/assets",
            "thresholds": "/thresholds",
            "users": "/users",
            "audit": "/admin/audit",
            "integration": "/integration",
            "simulation": "/simulation",
            "schedule": "/schedule",
            "maintenance": "/maintenance",
            "inventory": "/inventory",
            "notifications": "/notifications",
            "profile": "/profile",
        },
    }
)


def shell_context(request: Request, user: dict | None = None) -> dict[str, Any]:
    current = user if user is not None else get_optional_user(request)
    active_alert_count = 0
    notifications: list[dict] = []
    unread_notifications = 0
    fleet = {"machines": 0, "open_wos": 0, "critical_alerts": 0}
    if current:
        alert_filter = {"status": {"$in": ["open", "acknowledged"]}}
        active_alert_count = alerts().count_documents(alert_filter)
        fleet["critical_alerts"] = alerts().count_documents(
            {"status": {"$in": ["open", "acknowledged"]}, "level": "critical"}
        )
        fleet["open_wos"] = work_orders().count_documents(
            {"status": {"$in": ["pending", "in_progress", "awaiting_review"]}}
        )
        fleet["machines"] = machines().count_documents({"active": True})
        unread_notifications = notification_collection().count_documents(
            {"user_id": current["id"], "read_at": None}
        )
        notifications = list(
            notification_collection()
            .find({"user_id": current["id"]})
            .sort("created_at", -1)
            .limit(5)
        )
        for item in notifications:
            item["id"] = str(item.pop("_id"))

    return {
        "request": request,
        "current_user": current,
        "is_admin": is_admin(current),
        "csrf_token": csrf_token(request),
        "flashes": pop_flashes(request),
        "notifications": notifications,
        "unread_notifications": unread_notifications,
        "active_alert_count": active_alert_count,
        "fleet": fleet,
        "active_path": request.url.path,
        "now": utcnow(),
        "current_year": utcnow().year,
        "shift": shift_label(),
        "timezone": settings.timezone,
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    }


def render(
    request: Request,
    template: str,
    *,
    user: dict | None = None,
    status_code: int = 200,
    **context: Any,
):
    payload = shell_context(request, user)
    payload.update(context)
    return templates.TemplateResponse(request, template, payload, status_code=status_code)


def render_error(request: Request, status_code: int, title: str, message: str):
    user = get_optional_user(request)
    context = {
        "request": request,
        "current_user": user,
        "status_code": status_code,
        "title": title,
        "message": message,
        "active_alert_count": 0,
        "csrf_token": csrf_token(request),
        "flashes": [],
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
    }
    return templates.TemplateResponse(request, f"errors/{status_code}.html", context, status_code=status_code)
