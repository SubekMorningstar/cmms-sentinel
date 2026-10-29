from __future__ import annotations

import re
from datetime import timedelta

from bson import ObjectId

from app.database import (
    alerts,
    machines,
    readings,
    simulation_controls,
    simulation_runs,
    thresholds,
    users,
    work_orders,
)
from app.services.telemetry import ensure_telemetry
from app.services.thresholds import evaluate_reading
from app.utils import to_local, utcnow


def _admin_session(client):
    response = client.get("/simulation", follow_redirects=False)
    if response.status_code == 200:
        return
    login_page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text)
    assert token
    response = client.post(
        "/login",
        data={
            "email": "admin@test.local",
            "password": "AdminUji#2026",
            "csrf_token": token.group(1),
            "next": "/simulation",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_simulation_control_and_labeled_experiment_end_to_end(client):
    _admin_session(client)
    machine_id = ObjectId()
    machine_code = "SIM-TEST-01"
    now = utcnow().replace(second=0, microsecond=0)
    machine = {
        "_id": machine_id,
        "code": machine_code,
        "name": "Mesin virtual pengujian",
        "active": True,
        "location": "Lab simulasi",
        "criticality": "medium",
        "operational_status": "running",
    }
    machines().insert_one(machine)
    limits = {
        "temperature": (70, 85, 50),
        "vibration": (5, 9, 2),
        "power": (12, 16, 10),
        "sound": (80, 90, 60),
    }
    thresholds().insert_many(
        [
            {
                "machine_id": machine_id,
                "sensor": sensor,
                "warning": warning,
                "critical": critical,
                "hysteresis": 0.5,
                "normal_reset_readings": 3,
                "enabled": True,
            }
            for sensor, (warning, critical, _value) in limits.items()
        ]
    )
    readings().insert_many(
        [
            {
                "ts": now - timedelta(minutes=5 * (index + 2)),
                "machine_id": machine_id,
                "machine_code": machine_code,
                **{sensor: value for sensor, (_warning, _critical, value) in limits.items()},
                "quality": "good",
                "source": "dataset-seed" if index == 0 else "simulator",
            }
            for index in range(96)
        ]
    )

    simulation_page = client.get("/simulation")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', simulation_page.text)
    assert simulation_page.status_code == 200
    assert csrf
    assert "Kondisi normal" in simulation_page.text
    assert "Data simulasi" in simulation_page.text
    control_response = client.post(
        "/simulation/control",
        data={
            "csrf_token": csrf.group(1),
            "machine_code": machine_code,
            "status": "stopped",
            "scenario_id": "",
            "seed": "4207",
        },
        follow_redirects=False,
    )
    assert control_response.status_code == 303
    assert simulation_controls().find_one({"machine_id": machine_id})["status"] == "stopped"
    scenario_control = client.post(
        "/simulation/control",
        data={
            "csrf_token": csrf.group(1),
            "machine_code": machine_code,
            "status": "running",
            "scenario_id": "sensor-disconnected",
            "severity": "medium",
            "duration_minutes": "120",
            "seed": "4207",
        },
        follow_redirects=False,
    )
    assert scenario_control.status_code == 303
    active_control = simulation_controls().find_one({"machine_id": machine_id})
    assert active_control["scenario_id"] == "sensor-disconnected"
    assert active_control["fault_sensor"] == "vibration"
    assert active_control["severity"] == "medium"
    assert active_control["duration_minutes"] == 120
    assert active_control["scenario_ends_at"] > active_control["scenario_started_at"]
    scenario_page = client.get("/simulation")
    assert "Sensor terputus" in scenario_page.text
    assert "Getaran · Sedang" in scenario_page.text
    assert "durasi 120 menit" in scenario_page.text
    normal_control = client.post(
        "/simulation/control",
        data={
            "csrf_token": csrf.group(1),
            "machine_code": machine_code,
            "status": "running",
            "scenario_id": "normal",
            "severity": "high",
            "duration_minutes": "60",
            "seed": "4207",
        },
        follow_redirects=False,
    )
    assert normal_control.status_code == 303
    active_control = simulation_controls().find_one({"machine_id": machine_id})
    assert active_control["scenario_id"] == "normal"
    assert active_control["fault_sensor"] is None
    assert active_control["scenario_ends_at"] > active_control["scenario_started_at"]
    assert ensure_telemetry(now=utcnow() + timedelta(minutes=10)) > 0
    normal_telemetry = readings().find_one(
        {"machine_id": machine_id, "scenario_id": "normal", "fault_label": False},
        sort=[("ts", -1)],
    )
    assert normal_telemetry
    assert normal_telemetry["source"] == "simulator"

    experiment_start = to_local(
        (now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5))
        - timedelta(minutes=30)
    ).strftime("%Y-%m-%dT%H:%M")
    experiment_end = to_local(
        now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
    ).strftime("%Y-%m-%dT%H:%M")
    experiment_response = client.post(
        "/simulation/experiments",
        data={
            "csrf_token": csrf.group(1),
            "machine_code": machine_code,
            "scenario_id": "bearing-wear",
            "start_at": experiment_start,
            "end_at": experiment_end,
            "severity": "high",
            "seed": "4207",
        },
        follow_redirects=False,
    )
    assert experiment_response.status_code == 303
    run = simulation_runs().find_one({"machine_code": machine_code})
    assert run
    assert run["seed"] == 4207
    assert run["scenario_id"] == "bearing-wear"
    assert run["severity"] == "high"
    assert run["sample_count"] == 7
    assert run["metrics"]["recall_pct"] == 100
    assert run["metrics"]["detected"] is True
    assert run["metrics"]["detection_latency_minutes"] == 0
    assert run["metrics"]["detection_method"] == "skor penyimpangan pada data simulasi >=25"
    assert run["metrics"]["work_orders_created"] == 1
    assert alerts().count_documents({"simulation_run_id": run["run_id"], "fault_label": True}) == 1
    order = work_orders().find_one({"simulation_run_id": run["run_id"]})
    assert order
    assert order["scenario_id"] == "bearing-wear"
    assert order["alert_id"]
    order_id = str(order["_id"])
    order_page = client.get(f"/work-orders/{order_id}")
    order_csrf = re.search(r'name="csrf_token" value="([^"]+)"', order_page.text)
    assert order_page.status_code == 200
    assert order_csrf
    technician = users().find_one({"role": "teknisi", "active": True})
    assignment = client.post(
        f"/work-orders/{order_id}/assign",
        data={"csrf_token": order_csrf.group(1), "assigned_to": str(technician["_id"])},
        follow_redirects=False,
    )
    assert assignment.status_code == 303
    assert work_orders().find_one({"_id": order["_id"]})["assigned_to"] == technician["_id"]
    started = client.post(
        f"/work-orders/{order_id}/status",
        data={"csrf_token": order_csrf.group(1), "status": "in_progress", "notes": ""},
        follow_redirects=False,
    )
    assert started.status_code == 303
    order_state = work_orders().find_one({"_id": order["_id"]})
    for index in range(len(order_state["checklist"])):
        checked = client.post(
            f"/work-orders/{order_id}/checklist/{index}",
            data={"csrf_token": order_csrf.group(1)},
            follow_redirects=False,
        )
        assert checked.status_code == 303
    submitted = client.post(
        f"/work-orders/{order_id}/status",
        data={
            "csrf_token": order_csrf.group(1),
            "status": "awaiting_review",
            "notes": "Pemeriksaan simulasi selesai",
            "inspection_result": "issue_found",
        },
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    reviewed = client.post(
        f"/work-orders/{order_id}/status",
        data={
            "csrf_token": order_csrf.group(1),
            "status": "resolved",
            "notes": "Pemeriksaan hasil simulasi disetujui.",
            "review_outcome": "confirmed_issue",
            "downtime_hours": "0.5",
        },
        follow_redirects=False,
    )
    assert reviewed.status_code == 303
    assert work_orders().find_one({"_id": order["_id"]})["status"] == "resolved"
    assert alerts().find_one({"_id": order["alert_id"]})["status"] == "resolved"
    assert client.get(
        f"/work-orders?status=all&simulation_run_id={run['run_id']}"
    ).status_code == 200
    assert "Data simulasi" in client.get("/reports?days=7").text
    page = client.get("/simulation")
    assert page.status_code == 200
    comparison = client.get("/simulation/compare", params={"runs": [run["run_id"]]})
    assert comparison.status_code == 200 and run["run_id"] in comparison.text
    repeat_response = client.post(
        f"/simulation/experiments/{run['run_id']}/repeat",
        data={"csrf_token": csrf.group(1)},
        follow_redirects=False,
    )
    assert repeat_response.status_code == 303
    repeated = simulation_runs().find_one(
        {"machine_code": machine_code, "run_id": {"$ne": run["run_id"]}}
    )
    assert repeated
    assert repeated["seed"] == run["seed"]
    assert repeated["severity"] == run["severity"]
    assert repeated["duration_minutes"] == run["duration_minutes"]
    assert repeated["baseline_snapshot"] == run["baseline_snapshot"]
    assert repeated["started_at"] == run["started_at"]
    assert repeated["ended_at"] == run["ended_at"]
    first_values = list(
        readings().find(
            {"simulation_run_id": run["run_id"]},
            {"_id": 0, "temperature": 1, "vibration": 1, "power": 1, "sound": 1},
        ).sort("ts", 1)
    )
    repeated_values = list(
        readings().find(
            {"simulation_run_id": repeated["run_id"]},
            {"_id": 0, "temperature": 1, "vibration": 1, "power": 1, "sound": 1},
        ).sort("ts", 1)
    )
    assert repeated_values == first_values
    normal_response = client.post(
        "/simulation/experiments",
        data={
            "csrf_token": csrf.group(1),
            "machine_code": machine_code,
            "scenario_id": "normal",
            "start_at": experiment_start,
            "end_at": experiment_end,
            "severity": "high",
            "seed": "4207",
        },
        follow_redirects=False,
    )
    assert normal_response.status_code == 303
    normal_run = simulation_runs().find_one(
        {"machine_code": machine_code, "scenario_id": "normal"}
    )
    assert normal_run
    assert normal_run["fault_started_at"] is None
    assert normal_run["metrics"]["recall_pct"] is None
    assert normal_run["metrics"]["false_alarms_per_hour"] is not None
    normal_readings = list(
        readings().find(
            {"simulation_run_id": normal_run["run_id"]},
            {"_id": 0, "scenario_id": 1, "fault_label": 1},
        )
    )
    assert len(normal_readings) == normal_run["sample_count"]
    assert all(
        row["scenario_id"] == "normal" and row["fault_label"] is False
        for row in normal_readings
    )
    profile = client.get("/profile")
    logout_csrf = re.search(r'name="csrf_token" value="([^"]+)"', profile.text)
    assert logout_csrf
    logout_response = client.post(
        "/logout",
        data={"csrf_token": logout_csrf.group(1)},
        follow_redirects=False,
    )
    assert logout_response.status_code == 303
    for collection in (
        readings(),
        thresholds(),
        alerts(),
        work_orders(),
        simulation_controls(),
        simulation_runs(),
    ):
        collection.delete_many({"machine_id": machine_id})
    machines().delete_one({"_id": machine_id})


def test_sensor_disconnection_creates_alert_and_linked_work_order(client):
    _admin_session(client)
    machine_id = ObjectId()
    machine_code = "SIM-GAP-TEST"
    machine = {
        "_id": machine_id,
        "code": machine_code,
        "name": "Sensor disconnect test",
        "active": True,
    }
    machines().insert_one(machine)
    thresholds().insert_one(
        {
            "machine_id": machine_id,
            "sensor": "vibration",
            "warning": 5,
            "critical": 9,
            "hysteresis": 0.5,
            "normal_reset_readings": 3,
            "enabled": True,
        }
    )
    moment = utcnow()
    run_id = "a" * 16
    reading = {
        "ts": moment,
        "machine_id": machine_id,
        "machine_code": machine_code,
        "temperature": 50,
        "power": 10,
        "sound": 60,
        "quality": "partial",
        "source": "simulator",
        "simulation_run_id": run_id,
        "scenario_id": "sensor-disconnected",
        "fault_sensor": "vibration",
        "fault_label": True,
        "sensor_fault": True,
    }
    try:
        result = evaluate_reading(reading, machine, list(thresholds().find({"machine_id": machine_id})))
        alert = alerts().find_one({"simulation_run_id": run_id})
        assert len(result["created_alerts"]) == 1
        assert alert
        assert alert["sensor"] == "vibration"
        assert alert["value"] is None
        assert alert["source"] == "simulator"
        assert alert["scenario_id"] == "sensor-disconnected"
        assert alert["fault_label"] is True
        assert alert["level"] == "warning"
        detail = client.get(f"/alerts/{alert['_id']}")
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)
        assert detail.status_code == 200
        assert csrf
        created = client.post(
            f"/alerts/{alert['_id']}/work-order",
            data={"csrf_token": csrf.group(1)},
            follow_redirects=False,
        )
        assert created.status_code == 303
        order = work_orders().find_one({"simulation_run_id": run_id})
        assert order
        assert order["scenario_id"] == "sensor-disconnected"
        assert order["alert_id"] == alert["_id"]
        profile = client.get("/profile")
        logout_csrf = re.search(r'name="csrf_token" value="([^"]+)"', profile.text)
        assert logout_csrf
        assert client.post(
            "/logout",
            data={"csrf_token": logout_csrf.group(1)},
            follow_redirects=False,
        ).status_code == 303
    finally:
        alerts().delete_many({"machine_id": machine_id})
        work_orders().delete_many({"machine_id": machine_id})
        thresholds().delete_many({"machine_id": machine_id})
        machines().delete_one({"_id": machine_id})
