from __future__ import annotations

import json
import re

from bson import ObjectId

from app.config import settings
from app.database import alerts, machines, readings, thresholds, users, work_orders
from app.security import verify_password
from app.utils import utcnow

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
CHART_DATA_RE = re.compile(
    r'<script type="application/json" data-chart-data="page"[^>]*>(.*?)</script>',
    re.DOTALL,
)
STATE: dict[str, str] = {}

ASSET_PAYLOAD = {
    "name": "Pompa Transfer Uji",
    "asset_type": "Centrifugal Pump",
    "location": "Area Uji - Line 1",
    "manufacturer": "Grundfos",
    "model": "NK 65-200",
    "serial_number": "TST-SN-0001",
    "criticality": "high",
    "operational_status": "running",
    "rated_power_kw": "15",
    "rated_speed_rpm": "2900",
    "installed_at": "2024-02-15",
    "notes": "Aset dibuat oleh pengujian otomatis.",
}

THRESHOLD_PAYLOAD = {
    f"{sensor}_{field}": value
    for sensor, (warning, critical) in {
        "temperature": ("70", "85"),
        "vibration": ("5", "9"),
        "power": ("12", "16"),
        "sound": ("80", "90"),
    }.items()
    for field, value in (
        ("warning", warning),
        ("critical", critical),
        ("hysteresis", "0.5"),
        ("normal", "3"),
        ("enabled", "on"),
    )
}


def token_from(html: str) -> str:
    match = CSRF_RE.search(html)
    assert match, "Token CSRF tidak ditemukan pada halaman"
    return match.group(1)


def visit_token(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, f"GET {path} -> {response.status_code}"
    return token_from(response.text)


def login(client, email: str, password: str) -> None:
    token = visit_token(client, "/login")
    response = client.post(
        "/login",
        data={"email": email, "password": password, "csrf_token": token, "next": "/dashboard"},
        follow_redirects=False,
    )
    assert response.status_code == 303, f"Login gagal: {response.status_code}"
    assert response.headers["location"].endswith("/dashboard")


def logout(client) -> None:
    token = visit_token(client, "/profile")
    response = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")


def machine_id() -> ObjectId:
    return ObjectId(STATE["machine_id"])


class TestEndToEnd:
    def test_health_guards_and_login(self, client):
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert health.json()["database"] == "cmms_ops_test"

        guarded = client.get("/dashboard", follow_redirects=False)
        assert guarded.status_code == 303
        assert "/login" in guarded.headers["location"]

        no_csrf = client.post(
            "/login",
            data={"email": "admin@test.local", "password": "AdminUji#2026"},
            follow_redirects=False,
        )
        assert no_csrf.status_code == 400

        wrong_password = client.post(
            "/login",
            data={
                "email": "admin@test.local",
                "password": "PasswordSalah#1",
                "csrf_token": visit_token(client, "/login"),
            },
            follow_redirects=False,
        )
        assert wrong_password.status_code == 401

        login(client, "admin@test.local", "AdminUji#2026")
        readings().insert_one(
            {
                "ts": utcnow(),
                "machine_id": ObjectId(),
                "temperature": 60.5,
                "vibration": 3.1,
                "power": 10.2,
                "sound": 70.4,
            }
        )
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "Pusat Operasi" in dashboard.text
        assert f"cmms.js?v={settings.app_version}" in dashboard.text
        assert "Daya (kW)" in dashboard.text
        assert "Suara (dB(A))" in dashboard.text
        chart_match = CHART_DATA_RE.search(dashboard.text)
        assert chart_match
        trend = json.loads(chart_match.group(1))["trend"]
        assert trend["power"] == [10.2]
        assert trend["sound"] == [70.4]

    def test_asset_create_edit_and_validation(self, client):
        token = visit_token(client, "/assets/new")
        response = client.post(
            "/assets",
            data={"csrf_token": token, "code": "TST-01", **ASSET_PAYLOAD},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text[:400]
        location = response.headers["location"]
        assert location.startswith("/assets/")
        STATE["machine_id"] = location.rstrip("/").split("/")[-1]

        machine = machines().find_one({"_id": machine_id()})
        assert machine and machine["code"] == "TST-01" and machine["active"] is True
        assert thresholds().count_documents({"machine_id": machine["_id"]}) == 4

        invalid = client.post(
            "/assets",
            data={
                "csrf_token": token,
                "code": "TST-99",
                **{**ASSET_PAYLOAD, "name": "X"},
            },
            follow_redirects=False,
        )
        assert invalid.status_code == 400
        assert "Nama mesin wajib" in invalid.text

        token = visit_token(client, f"/assets/{STATE['machine_id']}/edit")
        updated = client.post(
            f"/assets/{STATE['machine_id']}",
            data={
                "csrf_token": token,
                "code": "TST-01",
                **{**ASSET_PAYLOAD, "name": "Pompa Transfer Uji (Revisi)", "criticality": "critical"},
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        machine = machines().find_one({"_id": machine_id()})
        assert machine["name"] == "Pompa Transfer Uji (Revisi)"
        assert machine["criticality"] == "critical"

        detail = client.get(f"/assets/{STATE['machine_id']}")
        assert detail.status_code == 200
        assert "Pompa Transfer Uji (Revisi)" in detail.text
        assert "Skor anomali pola sensor" in detail.text
        assert "Belum cukup riwayat" in detail.text

    def test_asset_archive_and_restore(self, client):
        token = visit_token(client, "/assets/new")
        response = client.post(
            "/assets",
            data={
                "csrf_token": token,
                "code": "TST-02",
                **{
                    **ASSET_PAYLOAD,
                    "name": "Kompresor Uji Arsip",
                    "serial_number": "TST-SN-0002",
                },
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        second_id = response.headers["location"].rstrip("/").split("/")[-1]
        STATE["machine2_id"] = second_id

        token = visit_token(client, f"/assets/{second_id}")
        archived = client.post(
            f"/assets/{second_id}/archive",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert archived.status_code == 303
        machine = machines().find_one({"_id": ObjectId(second_id)})
        assert machine["active"] is False
        assert machine["operational_status"] == "retired"

        token = visit_token(client, f"/assets/{second_id}")
        restored = client.post(
            f"/assets/{second_id}/restore",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert restored.status_code == 303
        machine = machines().find_one({"_id": ObjectId(second_id)})
        assert machine["active"] is True
        assert machine["operational_status"] == "standby"

    def test_threshold_update(self, client):
        token = visit_token(client, "/thresholds?machine=TST-01")
        response = client.post(
            f"/thresholds/{STATE['machine_id']}",
            data={"csrf_token": token, **THRESHOLD_PAYLOAD},
            follow_redirects=False,
        )
        assert response.status_code == 303
        doc = thresholds().find_one({"machine_id": machine_id(), "sensor": "temperature"})
        assert doc["warning"] == 70.0 and doc["critical"] == 85.0
        assert doc["normal_reset_readings"] == 3 and doc["enabled"] is True

        invalid_payload = {
            **THRESHOLD_PAYLOAD,
            "temperature_warning": "90",
            "temperature_critical": "85",
        }
        invalid = client.post(
            f"/thresholds/{STATE['machine_id']}",
            data={"csrf_token": visit_token(client, "/thresholds?machine=TST-01"), **invalid_payload},
            follow_redirects=False,
        )
        assert invalid.status_code == 400
        assert "batas peringatan" in invalid.text

    def test_work_order_lifecycle(self, client):
        technician = users().find_one({"email": "teknisi@test.local"})
        token = visit_token(client, "/work-orders/new")
        created = client.post(
            "/work-orders",
            data={
                "csrf_token": token,
                "machine_id": STATE["machine_id"],
                "title": "Inspeksi bearing pompa transfer",
                "description": "Periksa getaran dan pelumasan bearing pompa transfer line 1.",
                "priority": "high",
                "type": "preventive",
                "assigned_to": str(technician["_id"]),
                "due": "24h",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, created.text[:400]
        wo_id = created.headers["location"].rstrip("/").split("/")[-1]
        STATE["wo_id"] = wo_id
        wo = work_orders().find_one({"_id": ObjectId(wo_id)})
        assert wo["status"] == "pending" and wo["source"] == "manual"

        logout(client)
        login(client, "teknisi@test.local", "TeknisiUji#2026")
        assert client.get("/dashboard").status_code == 200
        assert "Pekerjaan saya" in client.get("/dashboard").text

        note = client.post(
            f"/work-orders/{wo_id}/note",
            data={
                "csrf_token": visit_token(client, f"/work-orders/{wo_id}"),
                "note": "Pemeriksaan awal selesai, bearing dalam kondisi baik.",
            },
            follow_redirects=False,
        )
        assert note.status_code == 303
        wo = work_orders().find_one({"_id": ObjectId(wo_id)})
        assert any(item["action"] == "note" for item in wo["activities"])

        started = client.post(
            f"/work-orders/{wo_id}/status",
            data={"csrf_token": visit_token(client, f"/work-orders/{wo_id}"), "status": "in_progress"},
            follow_redirects=False,
        )
        assert started.status_code == 303
        wo = work_orders().find_one({"_id": ObjectId(wo_id)})
        assert wo["status"] == "in_progress" and wo["started_at"] is not None
        for index in range(len(wo["checklist"])):
            checked = client.post(
                f"/work-orders/{wo_id}/checklist/{index}",
                data={"csrf_token": visit_token(client, f"/work-orders/{wo_id}")},
                follow_redirects=False,
            )
            assert checked.status_code == 303

        submitted = client.post(
            f"/work-orders/{wo_id}/status",
            data={
                "csrf_token": visit_token(client, f"/work-orders/{wo_id}"),
                "status": "awaiting_review",
                "notes": "Bearing dilumasi ulang dan getaran kembali normal.",
                "inspection_result": "issue_found",
            },
            follow_redirects=False,
        )
        assert submitted.status_code == 303
        wo = work_orders().find_one({"_id": ObjectId(wo_id)})
        assert wo["status"] == "awaiting_review" and wo["submitted_at"] is not None

        logout(client)
        login(client, "admin@test.local", "AdminUji#2026")
        reviewed = client.post(
            f"/work-orders/{wo_id}/status",
            data={
                "csrf_token": visit_token(client, f"/work-orders/{wo_id}"),
                "status": "resolved",
                "notes": "Checklist dan hasil inspeksi telah ditinjau admin.",
                "review_outcome": "confirmed_issue",
                "downtime_hours": "1.5",
            },
            follow_redirects=False,
        )
        assert reviewed.status_code == 303
        wo = work_orders().find_one({"_id": ObjectId(wo_id)})
        assert wo["status"] == "resolved" and wo["downtime_minutes"] == 90
        assert wo["review_outcome"] == "confirmed_issue"

        token = visit_token(client, "/work-orders/new")
        second = client.post(
            "/work-orders",
            data={
                "csrf_token": token,
                "machine_id": STATE["machine_id"],
                "title": "Pemeriksaan rutin mingguan",
                "description": "Pemeriksaan rutin mingguan seluruh komponen pompa transfer.",
                "priority": "medium",
                "type": "inspection",
                "assigned_to": "",
                "due": "72h",
            },
            follow_redirects=False,
        )
        assert second.status_code == 303
        wo2_id = second.headers["location"].rstrip("/").split("/")[-1]
        STATE["wo2_id"] = wo2_id
        assigned = client.post(
            f"/work-orders/{wo2_id}/assign",
            data={
                "csrf_token": visit_token(client, f"/work-orders/{wo2_id}"),
                "assigned_to": str(technician["_id"]),
            },
            follow_redirects=False,
        )
        assert assigned.status_code == 303
        wo2 = work_orders().find_one({"_id": ObjectId(wo2_id)})
        assert wo2["assigned_name"] == "Teknisi Uji"

        missing_csrf = client.post(
            f"/work-orders/{wo2_id}/note",
            data={"note": "Tanpa token"},
            follow_redirects=False,
        )
        assert missing_csrf.status_code == 400

    def test_alert_lifecycle(self, client):
        machine = machines().find_one({"_id": machine_id()})
        moment = utcnow()
        inserted = alerts().insert_one(
            {
                "machine_id": machine["_id"],
                "machine_code": machine["code"],
                "machine_name": machine["name"],
                "sensor": "temperature",
                "level": "critical",
                "status": "open",
                "value": 96.5,
                "threshold_value": 85.0,
                "unit": "°C",
                "message": "Suhu 96.5 °C melebihi batas kritis 85 °C.",
                "first_seen": moment,
                "last_seen": moment,
            }
        )
        alert_id = str(inserted.inserted_id)
        STATE["alert_id"] = alert_id

        listing = client.get("/alerts")
        assert listing.status_code == 200
        detail = client.get(f"/alerts/{alert_id}")
        assert detail.status_code == 200
        assert "Suhu 96.5" in detail.text

        acknowledged = client.post(
            f"/alerts/{alert_id}/acknowledge",
            data={"csrf_token": visit_token(client, f"/alerts/{alert_id}")},
            follow_redirects=False,
        )
        assert acknowledged.status_code == 303
        alert = alerts().find_one({"_id": inserted.inserted_id})
        assert alert["status"] == "acknowledged"
        assert alert["acknowledged_by_name"] == "Admin Uji"

        created = client.post(
            f"/alerts/{alert_id}/work-order",
            data={"csrf_token": visit_token(client, f"/alerts/{alert_id}")},
            follow_redirects=False,
        )
        assert created.status_code == 303
        wo_id = created.headers["location"].rstrip("/").split("/")[-1]
        alert = alerts().find_one({"_id": inserted.inserted_id})
        wo = work_orders().find_one({"_id": ObjectId(wo_id)})
        assert str(alert["wo_id"]) == wo_id
        assert wo["priority"] == "critical" and wo["type"] == "corrective"
        assert wo["sensor"] == "temperature" and wo["source"] == "manual"

        resolved = client.post(
            f"/alerts/{alert_id}/resolve",
            data={
                "csrf_token": visit_token(client, f"/alerts/{alert_id}"),
                "note": "Filter pendingin dibersihkan dan suhu kembali normal.",
            },
            follow_redirects=False,
        )
        assert resolved.status_code == 303
        alert = alerts().find_one({"_id": inserted.inserted_id})
        assert alert["status"] == "resolved"
        assert alert["resolved_by_name"] == "Admin Uji"

    def test_user_management(self, client):
        token = visit_token(client, "/users/new")
        created = client.post(
            "/users",
            data={
                "csrf_token": token,
                "nama_lengkap": "Budi Uji",
                "email": "budi@test.local",
                "role": "teknisi",
                "password": "BudiUji#2026",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        created_user = users().find_one({"email": "budi@test.local"})
        assert created_user and verify_password("BudiUji#2026", created_user["password_hash"])
        STATE["budi_id"] = str(created_user["_id"])

        duplicate = client.post(
            "/users",
            data={
                "csrf_token": visit_token(client, "/users/new"),
                "nama_lengkap": "Budi Duplikat",
                "email": "budi@test.local",
                "role": "teknisi",
                "password": "BudiUji#2026",
            },
            follow_redirects=False,
        )
        assert duplicate.status_code == 400
        assert "Email sudah digunakan" in duplicate.text

        updated = client.post(
            f"/users/{STATE['budi_id']}",
            data={
                "csrf_token": visit_token(client, f"/users/{STATE['budi_id']}/edit"),
                "nama_lengkap": "Budi Santoso",
                "email": "budi@test.local",
                "role": "teknisi",
                "active": "on",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        assert users().find_one({"email": "budi@test.local"})["nama_lengkap"] == "Budi Santoso"

    def test_profile_update(self, client):
        token = visit_token(client, "/profile")
        response = client.post(
            "/profile",
            data={"csrf_token": token, "nama_lengkap": "Admin Operasional"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        admin = users().find_one({"email": "admin@test.local"})
        assert admin["nama_lengkap"] == "Admin Operasional"

    def test_csv_exports(self, client):
        token = visit_token(client, "/work-orders/new")
        injection = client.post(
            "/work-orders",
            data={
                "csrf_token": token,
                "machine_id": STATE["machine_id"],
                "title": "=SUM(1,1) cek injeksi csv",
                "description": "Work order untuk menguji proteksi formula pada ekspor CSV.",
                "priority": "low",
                "type": "inspection",
                "assigned_to": "",
                "due": "7d",
            },
            follow_redirects=False,
        )
        assert injection.status_code == 303

        for dataset in ("work_orders", "alerts", "readings", "machines"):
            response = client.get("/reports/export.csv", params={"dataset": dataset})
            assert response.status_code == 200, dataset
            assert response.headers["content-type"].startswith("text/csv")
            assert response.content.startswith("\ufeff".encode())
            csv_header = response.content.decode("utf-8-sig").splitlines()[0]
            assert "Data simulasi" in csv_header, dataset

        work_order_csv = client.get(
            "/reports/export.csv", params={"dataset": "work_orders"}
        ).content.decode("utf-8")
        assert "'=SUM(1,1)" in work_order_csv

        missing = client.get("/reports/export.csv", params={"dataset": "rahasia"})
        assert missing.status_code == 404

    def test_api_ingestion_and_validation(self, client):
        unauthorized = client.post(
            "/api/ingest",
            json={"machine_code": "TST-01", "readings": [{"temperature": 60}]},
        )
        assert unauthorized.status_code == 401

        wrong_key = client.post(
            "/api/ingest",
            json={"machine_code": "TST-01", "readings": [{"temperature": 60}]},
            headers={"x-api-key": "kunci-salah"},
        )
        assert wrong_key.status_code == 401

        headers = {"x-api-key": settings.ingest_api_key}
        before_readings = readings().count_documents({"machine_id": machine_id()})
        before_alerts = alerts().count_documents({"machine_id": machine_id()})
        accepted = client.post(
            "/api/ingest",
            json={
                "machine_code": "TST-01",
                "readings": [
                    {"temperature": 60.5, "vibration": 3.1, "power": 10.2, "sound": 70.4}
                ],
            },
            headers=headers,
        )
        assert accepted.status_code == 201, accepted.text[:400]
        assert accepted.json()["accepted"] == 1
        assert readings().count_documents({"machine_id": machine_id()}) == before_readings + 1
        assert alerts().count_documents({"machine_id": machine_id()}) == before_alerts

        out_of_range = client.post(
            "/api/ingest",
            json={"machine_code": "TST-01", "readings": [{"temperature": 400}]},
            headers=headers,
        )
        assert out_of_range.status_code == 422

        extra_field = client.post(
            "/api/ingest",
            json={"machine_code": "TST-01", "readings": [{"humidity": 40}]},
            headers=headers,
        )
        assert extra_field.status_code == 422

        unknown_machine = client.post(
            "/api/ingest",
            json={"machine_code": "TIDAK-ADA", "readings": [{"temperature": 60}]},
            headers=headers,
        )
        assert unknown_machine.status_code == 404

        fleet = client.get("/api/machines", headers=headers)
        assert fleet.status_code == 200
        assert fleet.json()["ok"] is True
        assert fleet.json()["count"] >= 2

        assert client.get("/api/machines").status_code == 200

        client.cookies.clear()
        anonymous = client.get("/api/machines")
        assert anonymous.status_code == 401
        login(client, "admin@test.local", "AdminUji#2026")

    def test_rbac_for_technician_and_logout(self, client):
        logout(client)
        login(client, "teknisi@test.local", "TeknisiUji#2026")

        assert client.get("/assets").status_code == 200
        assert client.get("/work-orders/new").status_code == 200
        assert client.get("/assets/new").status_code == 403
        assert client.get("/users").status_code == 403
        assert client.get("/integration").status_code == 403

        forbidden = client.post(
            f"/thresholds/{STATE['machine_id']}",
            data={"csrf_token": visit_token(client, "/profile"), **THRESHOLD_PAYLOAD},
            follow_redirects=False,
        )
        assert forbidden.status_code == 403

        archive_forbidden = client.post(
            f"/assets/{STATE['machine_id']}/archive",
            data={"csrf_token": visit_token(client, "/profile")},
            follow_redirects=False,
        )
        assert archive_forbidden.status_code == 403

        logout(client)
        guarded = client.get("/dashboard", follow_redirects=False)
        assert guarded.status_code == 303
        assert "/login" in guarded.headers["location"]
