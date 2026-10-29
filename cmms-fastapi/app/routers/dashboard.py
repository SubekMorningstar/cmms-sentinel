from __future__ import annotations

from datetime import timedelta

from bson import ObjectId
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.database import alerts, machines, users, work_orders
from app.security import is_admin, require_user
from app.services.analytics import dashboard_payload
from app.utils import dumps, local_day_label, utcnow
from app.web import render

router = APIRouter()


@router.get("/")
def index(request: Request):
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/dashboard")
def dashboard_page(request: Request):
    user = require_user(request)
    if not is_admin(user):
        return _technician_dashboard(request, user)
    payload = dashboard_payload()
    now = utcnow()
    open_statuses = {"$in": ["pending", "in_progress", "awaiting_review"]}
    technicians = list(users().find({"active": True, "role": "teknisi"}).sort("nama_lengkap", 1))
    for tech in technicians:
        query = {"assigned_to": tech["_id"], "status": open_statuses}
        tech["open_count"] = work_orders().count_documents(query)
        tech["overdue_count"] = work_orders().count_documents({**query, "due_at": {"$lt": now}})
    review_orders = list(
        work_orders().find({"status": "awaiting_review"}).sort("submitted_at", 1).limit(5)
    )
    machine_states = [
        {
            "id": snapshot["id"],
            "code": snapshot["machine"].get("code"),
            "name": snapshot["machine"].get("name"),
            "online": snapshot["online"],
            "health": snapshot["health"],
            "scenario_label": snapshot.get("scenario_label"),
            "is_synthetic": snapshot.get("is_synthetic"),
        }
        for snapshot in payload["snapshots"][:6]
    ]
    chart_data = {
        "trend": payload["trend"],
        "wo_breakdown": payload["wo_breakdown"],
        "alert_breakdown": payload["alert_breakdown"],
        "health_states": payload["kpis"]["states"],
    }
    return render(
        request,
        "dashboard/index.html",
        user=user,
        active_page="dashboard",
        kpis=payload["kpis"],
        snapshots=payload["snapshots"],
        alerts=payload["alerts"],
        work_orders=payload["work_orders"],
        alert_breakdown=payload["alert_breakdown"],
        wo_breakdown=payload["wo_breakdown"],
        chart_json=dumps(chart_data),
        today_label=local_day_label(payload["kpis"]["latest_ts"]),
        trend_source_label=payload["trend_source"],
        trend_range_start=payload["trend_range_start"],
        trend_range_end=payload["trend_range_end"],
        chart_data_sources=payload["chart_data_sources"],
        technicians=technicians,
        review_orders=review_orders,
        machine_states=machine_states,
        admin_overdue=work_orders().count_documents(
            {"status": open_statuses, "due_at": {"$lt": now}}
        ),
    )


def _technician_dashboard(request: Request, user: dict):
    user_id = ObjectId(user["id"])
    now = utcnow()
    query = {
        "assigned_to": user_id,
        "status": {"$in": ["pending", "in_progress", "awaiting_review"]},
    }
    orders = list(work_orders().find(query).sort([("due_at", 1), ("priority", 1)]).limit(8))
    machine_ids = {item.get("machine_id") for item in orders if item.get("machine_id")}
    machine_map = {
        item["_id"]: item
        for item in machines().find({"_id": {"$in": list(machine_ids)}}, {"code": 1, "name": 1, "location": 1})
    }
    for wo in orders:
        wo["id"] = str(wo.pop("_id"))
        asset = machine_map.get(wo.get("machine_id"), {})
        wo["machine_location"] = asset.get("location", "—")
        wo["machine_name"] = asset.get("name", wo.get("machine_name", "—"))
        wo["machine_code"] = asset.get("code", wo.get("machine_code", "—"))
        wo["is_overdue"] = bool(wo.get("due_at") and wo["due_at"] < now)
    assigned_open = work_orders().count_documents(query)
    overdue = work_orders().count_documents({**query, "due_at": {"$lt": now}})
    awaiting_review = work_orders().count_documents({**query, "status": "awaiting_review"})
    due_soon = work_orders().count_documents(
        {**query, "due_at": {"$gte": now, "$lte": now + timedelta(hours=24)}}
    )
    critical_alerts = alerts().count_documents(
        {"status": {"$in": ["open", "acknowledged"]}, "level": "critical"}
    )
    return render(
        request,
        "dashboard/technician.html",
        user=user,
        active_page="dashboard",
        orders=orders,
        assigned_open=assigned_open,
        overdue=overdue,
        awaiting_review=awaiting_review,
        due_soon=due_soon,
        critical_alerts=critical_alerts,
    )
