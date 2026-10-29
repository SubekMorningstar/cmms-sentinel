from __future__ import annotations

import re
from datetime import timedelta

from bson import ObjectId

from app.database import (
    inventory_items,
    machines,
    maintenance_plans,
    notifications,
    readings,
    users,
    work_orders,
)
from app.services.maintenance import generate_due_preventive_work_orders, notify_upcoming_work_orders
from app.services.work_orders import create_work_order
from app.utils import to_local, utcnow


CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _token(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, f"GET {path} -> {response.status_code}"
    match = CSRF_RE.search(response.text)
    assert match
    return match.group(1)


def _login_as(client, email: str, password: str) -> None:
    profile = client.get("/profile", follow_redirects=False)
    if profile.status_code == 200:
        token = CSRF_RE.search(profile.text)
        assert token
        client.post("/logout", data={"csrf_token": token.group(1)}, follow_redirects=False)
    token = _token(client, "/login")
    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token, "next": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_role_dashboards_field_work_scheduling_inventory_and_notifications(client):
    _login_as(client, "admin@test.local", "AdminUji#2026")
    machine = machines().find_one({"active": True})
    if not machine:
        machine = {
            "_id": ObjectId(),
            "code": "OPS-TEST-01",
            "name": "Aset virtual operasi",
            "active": True,
            "location": "Area simulasi",
            "operational_status": "running",
            "criticality": "medium",
        }
        machines().insert_one(machine)
    technician = users().find_one({"email": "teknisi@test.local", "active": True})
    assert machine and technician

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert "Beban teknisi" in dashboard.text
    assert client.get("/schedule").status_code == 200
    assert client.get("/maintenance").status_code == 200
    assert client.get("/inventory").status_code == 200
    assert client.get("/notifications").status_code == 200

    scheduled_for = utcnow() + timedelta(days=2)
    plan_response = client.post(
        "/maintenance/plans",
        data={
            "csrf_token": _token(client, "/maintenance"),
            "name": "Inspeksi preventif uji",
            "machine_id": str(machine["_id"]),
            "title": "Inspeksi rutin aset virtual",
            "description": "Periksa komponen dan fungsi aset virtual sesuai checklist.",
            "checklist": "Periksa kondisi komponen\nUji fungsi aset",
            "interval_days": "30",
            "next_due_at": to_local(scheduled_for).strftime("%Y-%m-%dT%H:%M"),
            "assigned_to": str(technician["_id"]),
        },
        follow_redirects=False,
    )
    assert plan_response.status_code == 303
    plan = maintenance_plans().find_one({"name": "Inspeksi preventif uji"})
    assert plan and plan["assigned_to"] == technician["_id"]

    gateway_machine = {
        "_id": ObjectId(),
        "code": "OPS-GW-TEST",
        "name": "Aset gateway uji",
        "active": True,
        "location": "Area gateway",
        "operational_status": "running",
        "criticality": "medium",
    }
    machines().insert_one(gateway_machine)
    readings().insert_one(
        {
            "machine_id": gateway_machine["_id"],
            "ts": utcnow(),
            "source": "gateway",
            "temperature": 42.0,
        }
    )
    rejected_plan = client.post(
        "/maintenance/plans",
        data={
            "csrf_token": _token(client, "/maintenance"),
            "name": "Jadwal gateway tidak boleh",
            "machine_id": str(gateway_machine["_id"]),
            "title": "Pemeriksaan aset gateway",
            "description": "Tidak boleh membuat rencana simulasi untuk gateway.",
            "interval_days": "30",
            "next_due_at": to_local(scheduled_for).strftime("%Y-%m-%dT%H:%M"),
        },
        follow_redirects=False,
    )
    assert rejected_plan.status_code == 303
    assert maintenance_plans().find_one({"name": "Jadwal gateway tidak boleh"}) is None

    maintenance_plans().update_one(
        {"_id": plan["_id"]},
        {"$set": {"next_due_at": utcnow() - timedelta(minutes=1)}},
    )
    assert generate_due_preventive_work_orders() == 1
    generated = work_orders().find_one({"maintenance_plan_id": str(plan["_id"])})
    assert generated and generated["source"] == "preventive"
    assert generated["checklist"][0]["label"] == "Periksa kondisi komponen"
    assert generate_due_preventive_work_orders() == 0

    inventory_response = client.post(
        "/inventory/items",
        data={
            "csrf_token": _token(client, "/inventory"),
            "part_code": "TEST-GREASE",
            "name": "Pelumas Uji",
            "unit": "tabung",
            "on_hand": "8",
            "minimum": "2",
        },
        follow_redirects=False,
    )
    assert inventory_response.status_code == 303
    part = inventory_items().find_one({"part_code": "TEST-GREASE"})
    assert part and part["on_hand"] == 8

    create_response = client.post(
        "/work-orders",
        data={
            "csrf_token": _token(client, "/work-orders/new"),
            "machine_id": str(machine["_id"]),
            "title": "Pemeriksaan lapangan uji",
            "description": "Lakukan pemeriksaan komponen aset dan dokumentasikan hasilnya.",
            "priority": "medium",
            "type": "inspection",
            "assigned_to": str(technician["_id"]),
            "due": "24h",
            "checklist": "Periksa kondisi awal\nUji fungsi",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303
    wo_id = create_response.headers["location"].rsplit("/", 1)[-1]
    wo = work_orders().find_one({"_id": ObjectId(wo_id)})
    assert wo and len(wo["checklist"]) == 2
    assert notifications().count_documents({"user_id": str(technician["_id"]), "read_at": None}) >= 1
    admin_user = users().find_one({"role": "admin", "active": True})
    unassigned = create_work_order(
        machine,
        title="WO privat untuk uji akses",
        description="Work order yang tidak ditugaskan kepada teknisi uji.",
        user=admin_user,
        due_at=utcnow() + timedelta(days=1),
    )

    _login_as(client, "teknisi@test.local", "TeknisiUji#2026")
    tech_dashboard = client.get("/dashboard")
    assert tech_dashboard.status_code == 200 and "Pekerjaan saya" in tech_dashboard.text
    assert client.get("/maintenance").status_code == 403
    assert client.get("/schedule").status_code == 403
    assert client.get(f"/work-orders/{unassigned['_id']}").status_code == 403

    started = client.post(
        f"/work-orders/{wo_id}/status",
        data={"csrf_token": _token(client, f"/work-orders/{wo_id}"), "status": "in_progress"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    consumed = client.post(
        f"/work-orders/{wo_id}/parts",
        data={
            "csrf_token": _token(client, f"/work-orders/{wo_id}"),
            "part_id": str(part["_id"]),
            "quantity": "2",
        },
        follow_redirects=False,
    )
    assert consumed.status_code == 303
    assert inventory_items().find_one({"_id": part["_id"]})["on_hand"] == 6
    for index in range(2):
        response = client.post(
            f"/work-orders/{wo_id}/checklist/{index}",
            data={"csrf_token": _token(client, f"/work-orders/{wo_id}")},
            follow_redirects=False,
        )
        assert response.status_code == 303
    submitted = client.post(
        f"/work-orders/{wo_id}/status",
        data={
            "csrf_token": _token(client, f"/work-orders/{wo_id}"),
            "status": "awaiting_review",
            "notes": "Pemeriksaan selesai dan aset berfungsi normal.",
            "inspection_result": "completed",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    assert work_orders().find_one({"_id": ObjectId(wo_id)})["status"] == "awaiting_review"
    assert len(work_orders().find_one({"_id": ObjectId(wo_id)})["parts_used"]) == 1
    notify_upcoming_work_orders()
    assert notifications().count_documents({"user_id": str(technician["_id"])}) >= 1

    read_all = client.post(
        "/notifications/read-all",
        data={"csrf_token": _token(client, "/notifications")},
        follow_redirects=False,
    )
    assert read_all.status_code == 303
    assert notifications().count_documents({"user_id": str(technician["_id"]), "read_at": None}) == 0

    _login_as(client, "admin@test.local", "AdminUji#2026")
    returned = client.post(
        f"/work-orders/{wo_id}/status",
        data={
            "csrf_token": _token(client, f"/work-orders/{wo_id}"),
            "status": "in_progress",
            "notes": "Lengkapi kembali pemeriksaan akhir sebelum disetujui.",
        },
        follow_redirects=False,
    )
    assert returned.status_code == 303
    assert work_orders().find_one({"_id": ObjectId(wo_id)})["status"] == "in_progress"

    _login_as(client, "teknisi@test.local", "TeknisiUji#2026")
    response = client.post(
        f"/work-orders/{wo_id}/checklist/0",
        data={"csrf_token": _token(client, f"/work-orders/{wo_id}")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = client.post(
        f"/work-orders/{wo_id}/checklist/0",
        data={"csrf_token": _token(client, f"/work-orders/{wo_id}")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    resubmitted = client.post(
        f"/work-orders/{wo_id}/status",
        data={
            "csrf_token": _token(client, f"/work-orders/{wo_id}"),
            "status": "awaiting_review",
            "notes": "Checklist diperiksa ulang dan seluruh langkah selesai.",
            "inspection_result": "completed",
        },
        follow_redirects=False,
    )
    assert resubmitted.status_code == 303
    _login_as(client, "admin@test.local", "AdminUji#2026")
    approved = client.post(
        f"/work-orders/{wo_id}/status",
        data={
            "csrf_token": _token(client, f"/work-orders/{wo_id}"),
            "status": "resolved",
            "notes": "Admin memverifikasi checklist dan hasil inspeksi.",
            "review_outcome": "no_issue",
            "downtime_hours": "0",
        },
        follow_redirects=False,
    )
    assert approved.status_code == 303
    closed = work_orders().find_one({"_id": ObjectId(wo_id)})
    assert closed["status"] == "resolved" and closed["review_outcome"] == "no_issue"
    assert client.get("/schedule").status_code == 200
