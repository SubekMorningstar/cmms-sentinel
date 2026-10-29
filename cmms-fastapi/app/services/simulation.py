from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from bson import ObjectId

from app.database import (
    machines,
    readings,
    simulation_controls,
    simulation_runs,
    thresholds,
    work_orders,
)
from app.services.predictive import MODEL_HISTORY_DAYS, assess_machine
from app.services.telemetry import DEMO_SOURCES, REAL_SOURCES, SIMULATED_SOURCE
from app.services.thresholds import evaluate_reading
from app.utils import SENSOR_ORDER, sensor_state, utcnow

INTERVAL_MINUTES = 5
EXPERIMENT_HISTORY_POINTS = 5000
EXPERIMENTS_LIMIT = 12

SEVERITIES = {
    "low": {"label": "Ringan", "fraction": 0.6},
    "medium": {"label": "Sedang", "fraction": 1.05},
    "high": {"label": "Tinggi", "fraction": 1.2},
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {
        "label": "Kondisi normal",
        "fault_mode": "normal",
        "sensor": None,
        "sensor_label": None,
        "description": "Seluruh rentang berjalan tanpa gangguan; alarm yang muncul dihitung sebagai alarm keliru.",
    },
    "bearing-wear": {
        "label": "Degradasi bearing",
        "fault_mode": "bearing_degradation",
        "sensor": "vibration",
        "sensor_label": "Getaran",
        "description": "Getaran meningkat progresif hingga melampaui ambang kritis.",
    },
    "cooling-failure": {
        "label": "Gangguan pendinginan",
        "fault_mode": "cooling_failure",
        "sensor": "temperature",
        "sensor_label": "Suhu",
        "description": "Suhu operasi naik melampaui batas kritis.",
    },
    "motor-overload": {
        "label": "Beban motor berlebih",
        "fault_mode": "motor_overload",
        "sensor": "power",
        "sensor_label": "Daya",
        "description": "Daya motor meningkat hingga kondisi kritis.",
    },
    "abnormal-noise": {
        "label": "Suara mekanis abnormal",
        "fault_mode": "abnormal_noise",
        "sensor": "sound",
        "sensor_label": "Suara",
        "description": "Intensitas suara meningkat melewati ambang kritis.",
    },
    "sensor-disconnected": {
        "label": "Sensor terputus",
        "fault_mode": "sensor_disconnection",
        "sensor": "vibration",
        "sensor_label": "Getaran",
        "description": "Pembacaan sensor getaran hilang; sistem menandai masalah kualitas data.",
    },
}


def _scenario_or_raise(scenario_id: str) -> dict[str, Any]:
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        raise ValueError("Skenario simulasi tidak dikenal.")
    return {"id": scenario_id, **scenario}


def control_map() -> dict[ObjectId, dict]:
    return {
        item["machine_id"]: item
        for item in simulation_controls().find({})
    }


def update_machine_control(
    machine: dict,
    *,
    status: str,
    scenario_id: str,
    severity: str,
    duration_minutes: int,
    seed: int,
    actor: dict,
) -> dict:
    if status not in {"running", "stopped"}:
        raise ValueError("Status mesin virtual tidak valid.")
    if readings().find_one(
        {"machine_id": machine["_id"], "source": {"$in": sorted(REAL_SOURCES)}},
        {"_id": 1},
    ):
        raise ValueError("Kontrol simulator dinonaktifkan untuk mesin yang memiliki telemetry gateway.")
    scenario = _scenario_or_raise(scenario_id or "normal") if status == "running" else None
    if not 0 <= seed <= 2_147_483_647:
        raise ValueError("Seed harus di antara 0 dan 2.147.483.647.")
    if severity not in SEVERITIES:
        raise ValueError("Tingkat keparahan simulator tidak valid.")
    if duration_minutes not in {30, 60, 120, 240}:
        raise ValueError("Durasi skenario simulator harus 30, 60, 120, atau 240 menit.")
    moment = utcnow()
    running = status == "running"
    control = {
        "machine_id": machine["_id"],
        "machine_code": machine["code"],
        "status": status,
        "scenario_id": scenario["id"] if running and scenario else None,
        "scenario_label": scenario["label"] if running and scenario else None,
        "fault_sensor": scenario["sensor"] if running and scenario else None,
        "severity": severity,
        "scenario_started_at": moment if running and scenario else None,
        "scenario_ends_at": moment + timedelta(minutes=duration_minutes) if running and scenario else None,
        "duration_minutes": duration_minutes,
        "seed": seed,
        "updated_at": moment,
        "updated_by": actor.get("id"),
        "updated_by_name": actor.get("nama_lengkap"),
    }
    simulation_controls().update_one(
        {"machine_id": machine["_id"]},
        {"$set": control},
        upsert=True,
    )
    return control


def _machine_thresholds(machine_id: ObjectId) -> dict[str, dict]:
    return {
        item["sensor"]: item
        for item in thresholds().find({"machine_id": machine_id, "enabled": True})
    }


def _baseline(machine_id: ObjectId, limits: dict[str, dict], start: datetime) -> tuple[dict, list[dict]]:
    query: dict[str, Any] = {
        "machine_id": machine_id,
        "ts": {"$gte": start - timedelta(days=MODEL_HISTORY_DAYS), "$lt": start},
        "simulation_run_id": {"$exists": False},
        "fault_label": {"$ne": True},
    }
    if readings().find_one(
        {"machine_id": machine_id, "source": {"$in": sorted(REAL_SOURCES)}},
        {"_id": 1},
    ):
        query["source"] = {"$nin": sorted(DEMO_SOURCES)}
    history = list(
        readings()
        .find(query, {"_id": 0, "ts": 1, **{sensor: 1 for sensor in SENSOR_ORDER}})
        .sort("ts", -1)
        .limit(EXPERIMENT_HISTORY_POINTS)
    )
    if len(history) < 48:
        raise ValueError("Eksperimen memerlukan sedikitnya 48 pembacaan riwayat sebagai baseline.")

    baseline = {}
    for sensor in SENSOR_ORDER:
        values = [
            float(item[sensor])
            for item in history
            if item.get(sensor) is not None
            and sensor in limits
            and sensor_state(float(item[sensor]), limits[sensor]) == "normal"
        ]
        if len(values) < 48:
            raise ValueError(f"Riwayat normal sensor {sensor} belum cukup untuk eksperimen.")
        baseline[sensor] = median(values)
    return baseline, list(reversed(history))


def _fault_value(
    sensor: str,
    baseline_value: float,
    limit: dict,
    severity: str,
    progress: float = 1.0,
) -> float:
    span = max(float(limit["critical"]) - float(limit["warning"]), 0.1)
    fraction = SEVERITIES[severity]["fraction"]
    progress = min(max(progress, 0.0), 1.0)
    value = float(limit["warning"]) + span * fraction * progress
    if sensor == "sound":
        value = max(value, baseline_value + 8 * fraction * progress)
    return round(value, 2)


def run_experiment(
    machine_code: str,
    scenario_id: str,
    duration_minutes: int,
    seed: int | None,
    actor: dict,
    severity: str = "high",
    start_at: datetime | None = None,
    baseline_snapshot: dict[str, float] | None = None,
) -> dict[str, Any]:
    if duration_minutes not in {30, 60, 120}:
        raise ValueError("Durasi eksperimen harus 30, 60, atau 120 menit.")
    machine = machines().find_one({"code": machine_code, "active": True})
    if not machine:
        raise ValueError("Pilih mesin virtual yang aktif.")
    if readings().find_one(
        {"machine_id": machine["_id"], "source": {"$in": sorted(REAL_SOURCES)}},
        {"_id": 1},
    ):
        raise ValueError("Eksperimen simulasi hanya dapat dijalankan pada mesin virtual tanpa telemetry gateway.")
    scenario = _scenario_or_raise(scenario_id)
    sensor = scenario["sensor"]
    if severity not in SEVERITIES:
        raise ValueError("Tingkat keparahan eksperimen tidak valid.")
    rng_seed = int(seed if seed is not None else secrets.randbelow(2_000_000_000) + 1)
    if not 0 <= rng_seed <= 2_147_483_647:
        raise ValueError("Seed harus di antara 0 dan 2.147.483.647.")

    now = utcnow().replace(second=0, microsecond=0)
    end = now - timedelta(minutes=now.minute % INTERVAL_MINUTES)
    count = duration_minutes // INTERVAL_MINUTES + 1
    default_start = end - timedelta(minutes=(count - 1) * INTERVAL_MINUTES)
    start = start_at or default_start
    if start.tzinfo is None:
        raise ValueError("Waktu mulai eksperimen harus memiliki zona waktu.")
    start = start.astimezone(now.tzinfo)
    end = start + timedelta(minutes=(count - 1) * INTERVAL_MINUTES)
    if start.second or start.microsecond or start.minute % INTERVAL_MINUTES:
        raise ValueError("Waktu eksperimen harus tepat pada interval 5 menit.")
    if end > now - timedelta(minutes=now.minute % INTERVAL_MINUTES):
        raise ValueError("Rentang eksperimen tidak boleh berakhir pada waktu mendatang.")
    limits = _machine_thresholds(machine["_id"])
    if set(limits) != set(SENSOR_ORDER):
        raise ValueError("Empat threshold sensor harus aktif untuk menjalankan eksperimen.")
    historical_baseline, history = _baseline(machine["_id"], limits, start)
    baseline = baseline_snapshot or historical_baseline
    if set(baseline) != set(SENSOR_ORDER):
        raise ValueError("Snapshot baseline eksperimen tidak lengkap.")

    fault_start_index = count if scenario_id == "normal" else max(1, count // 2)
    run_id = secrets.token_hex(8)
    rng = random.Random(rng_seed)
    docs = []
    predictions: list[bool] = []
    labels: list[bool] = []
    data_gap_detected_at = None
    for index in range(count):
        ts = start + timedelta(minutes=index * INTERVAL_MINUTES)
        row = {
            "ts": ts,
            "machine_id": machine["_id"],
            "machine_code": machine["code"],
            **{
                key: round(value * (1 + rng.uniform(-0.012, 0.012)), 2)
                for key, value in baseline.items()
            },
            "quality": "partial" if scenario_id == "sensor-disconnected" and index >= fault_start_index else "good",
            "source": SIMULATED_SOURCE,
            "simulation_run_id": run_id,
            "scenario_id": scenario["id"],
            "fault_label": index >= fault_start_index,
            "fault_sensor": sensor if index >= fault_start_index else None,
            "severity": severity,
            "seed": rng_seed,
        }
        if index >= fault_start_index:
            if scenario_id == "sensor-disconnected":
                row.pop(sensor, None)
                row["sensor_fault"] = True
            else:
                fault_duration = count - fault_start_index
                progress = (index - fault_start_index + 1) / fault_duration
                row[sensor] = _fault_value(
                    sensor,
                    baseline[sensor],
                    limits[sensor],
                    severity,
                    progress,
                )
        assessment = assess_machine(row, limits, history[-EXPERIMENT_HISTORY_POINTS:])
        predictions.append(bool(assessment["score"] is not None and assessment["score"] >= 25))
        labels.append(bool(row["fault_label"]))
        history.append({key: row.get(key) for key in ("ts", *SENSOR_ORDER)})
        docs.append(row)

    readings().insert_many(docs, ordered=True)
    for doc in docs:
        evaluation = evaluate_reading(doc, machine, list(limits.values()), ts=doc["ts"])
        if (
            scenario_id == "sensor-disconnected"
            and doc.get("sensor_fault")
            and data_gap_detected_at is None
            and any(
                item.get("sensor") == sensor
                for item in evaluation["created_alerts"] + evaluation["updated_alerts"]
            )
        ):
            data_gap_detected_at = doc["ts"]

    tp = sum(actual and predicted for actual, predicted in zip(labels, predictions))
    fp = sum(not actual and predicted for actual, predicted in zip(labels, predictions))
    fn = sum(actual and not predicted for actual, predicted in zip(labels, predictions))
    tn = sum(not actual and not predicted for actual, predicted in zip(labels, predictions))
    recall = round(tp / (tp + fn) * 100, 1) if tp + fn else None
    precision = round(tp / (tp + fp) * 100, 1) if tp + fp else None
    specificity = round(tn / (tn + fp) * 100, 1) if tn + fp else None
    detected_indices = [
        index for index in range(fault_start_index, count) if predictions[index]
    ]
    detected_at = docs[detected_indices[0]]["ts"] if detected_indices else None
    detection_latency = (
        round((detected_at - docs[fault_start_index]["ts"]).total_seconds() / 60, 1)
        if detected_at
        else None
    )
    false_alarm_episodes = sum(
        predicted and (index == 0 or not predictions[index - 1])
        for index, predicted in enumerate(predictions[:fault_start_index])
    )
    normal_hours = (
        duration_minutes / 60
        if scenario_id == "normal"
        else fault_start_index * INTERVAL_MINUTES / 60
    )
    false_alarm_rate = round(false_alarm_episodes / normal_hours, 2) if normal_hours else None
    if scenario_id == "sensor-disconnected":
        detected_at = data_gap_detected_at
        detection_latency = (
            round((detected_at - docs[fault_start_index]["ts"]).total_seconds() / 60, 1)
            if detected_at
            else None
        )
    fault_started_at = (
        docs[fault_start_index]["ts"] if fault_start_index < count else None
    )
    run = {
        "run_id": run_id,
        "machine_id": machine["_id"],
        "machine_code": machine["code"],
        "machine_name": machine.get("name"),
        "scenario_id": scenario["id"],
        "scenario_label": scenario["label"],
        "fault_mode": scenario["fault_mode"],
        "fault_sensor": sensor,
        "fault_sensor_label": scenario["sensor_label"],
        "severity": severity,
        "severity_label": (
            "Tidak berlaku"
            if scenario_id == "normal"
            else SEVERITIES[severity]["label"]
        ),
        "baseline_snapshot": baseline,
        "seed": rng_seed,
        "duration_minutes": duration_minutes,
        "sample_count": count,
        "fault_start": fault_started_at,
        "started_at": start,
        "ended_at": end,
        "fault_started_at": fault_started_at,
        "created_at": now,
        "created_by": actor.get("id"),
        "created_by_name": actor.get("nama_lengkap"),
        "metrics": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
            "precision_pct": precision,
            "recall_pct": recall,
            "specificity_pct": specificity,
            "ai_threshold": 25,
            "detected": detected_at is not None,
            "detection_latency_minutes": detection_latency,
            "false_alarm_episodes": false_alarm_episodes,
            "false_alarms_per_hour": false_alarm_rate,
            "detection_method": (
                "alert kualitas data"
                if scenario_id == "sensor-disconnected"
                else "skor penyimpangan pada data simulasi >=25"
            ),
            "work_orders_created": work_orders().count_documents(
                {"simulation_run_id": run_id}
            ),
        },
    }
    simulation_runs().insert_one(run)
    return run


def repeat_experiment(run_id: str, actor: dict) -> dict[str, Any]:
    previous = simulation_runs().find_one({"run_id": run_id})
    if not previous:
        raise ValueError("Eksperimen yang akan diulang tidak ditemukan.")
    return run_experiment(
        previous["machine_code"],
        previous["scenario_id"],
        int(previous["duration_minutes"]),
        int(previous["seed"]),
        actor,
        severity=previous.get("severity", "high"),
        start_at=previous["started_at"],
        baseline_snapshot=previous["baseline_snapshot"],
    )


def experiment_history(limit: int = EXPERIMENTS_LIMIT) -> list[dict]:
    rows = list(simulation_runs().find({}).sort("created_at", -1).limit(limit))
    for row in rows:
        row["id"] = row.pop("run_id")
        row.pop("baseline_snapshot", None)
        row["start_at_label"] = row["started_at"]
        row["end_at_label"] = row["ended_at"]
    return rows
