from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Any

from app.database import machines, readings, thresholds as threshold_collection
from app.services.thresholds import evaluate_reading
from app.utils import utcnow

log = logging.getLogger("cmms.telemetry")

SIMULATED_SOURCE = "simulator"
DATASET_SOURCE = "dataset-seed"
DEMO_SOURCES = {SIMULATED_SOURCE, DATASET_SOURCE}
INTERVAL_MINUTES = 5
BACKFILL_HOURS = 24
TICK_SECONDS = 60
REAL_SOURCES = {"iot", "gateway", "edge", "api"}

WAVE_SPEC = {
    "temperature": (0.012, 37.0),
    "vibration": (0.030, 23.0),
    "power": (0.035, 41.0),
    "sound": (0.008, 31.0),
}


def _bucket(moment: datetime) -> datetime:
    moment = moment.replace(second=0, microsecond=0)
    return moment - timedelta(minutes=moment.minute % INTERVAL_MINUTES)


def _anchor_reading(machine_id) -> dict[str, Any] | None:
    return readings().find_one(
        {"machine_id": machine_id, "source": {"$nin": sorted(DEMO_SOURCES)}},
        sort=[("ts", -1)],
    ) or readings().find_one(
        {"machine_id": machine_id, "source": {"$in": [DATASET_SOURCE]}},
        sort=[("ts", -1)],
    )


def _value(base: float, sensor: str, machine_code: str, ts: datetime, seed: int = 0) -> float:
    amplitude, period = WAVE_SPEC.get(sensor, (0.02, 30.0))
    phase = (sum(ord(char) for char in machine_code) % 31) / 31 * math.tau
    phase += (seed % 1_000_003) / 1_000_003 * math.tau
    minutes = ts.timestamp() / 60.0
    slow = math.sin(minutes / period * math.tau + phase)
    fast = math.sin(minutes / (period * 0.37) * math.tau + phase * 1.7)
    return round(max(0.0, base * (1 + amplitude * (slow * 0.65 + fast * 0.35))), 2)


def ensure_telemetry(now: datetime | None = None) -> int:
    now = now or utcnow()
    end = _bucket(now)
    floor = _bucket(now - timedelta(hours=BACKFILL_HOURS))
    active = list(machines().find({"active": True}))
    inserted = 0

    from app.services.simulation import SCENARIOS, control_map

    controls = control_map()
    for machine in active:
        control = controls.get(machine["_id"], {})
        if control.get("status", "running") != "running":
            continue
        if readings().find_one(
            {"machine_id": machine["_id"], "source": {"$in": sorted(REAL_SOURCES)}},
            {"_id": 1},
        ):
            continue
        anchor = _anchor_reading(machine["_id"])
        if not anchor:
            continue
        latest = readings().find_one({"machine_id": machine["_id"]}, sort=[("ts", -1)])
        if not latest:
            continue
        cursor = _bucket(latest["ts"] + timedelta(minutes=INTERVAL_MINUTES))
        if cursor < floor:
            cursor = floor
        if cursor > end:
            continue

        threshold_docs = list(
            threshold_collection().find({"machine_id": machine["_id"], "enabled": True})
        )
        scenario = SCENARIOS.get(control.get("scenario_id"))
        batch: list[dict[str, Any]] = []
        moment = cursor
        while moment <= end:
            scenario_active = bool(
                control.get("status", "running") == "running"
                and scenario
                and control.get("scenario_started_at")
                and control.get("scenario_ends_at")
                and control["scenario_started_at"] <= moment < control["scenario_ends_at"]
            )
            reading = {
                "ts": moment,
                "machine_id": machine["_id"],
                "machine_code": machine.get("code"),
                "temperature": _value(anchor.get("temperature", 0), "temperature", machine.get("code", ""), moment, control.get("seed", 0)),
                "vibration": _value(anchor.get("vibration", 0), "vibration", machine.get("code", ""), moment, control.get("seed", 0)),
                "power": _value(anchor.get("power", 0), "power", machine.get("code", ""), moment, control.get("seed", 0)),
                "sound": _value(anchor.get("sound", 0), "sound", machine.get("code", ""), moment, control.get("seed", 0)),
                "quality": "good",
                "source": SIMULATED_SOURCE,
            }
            if scenario_active and scenario:
                scenario_id = control["scenario_id"]
                has_fault = scenario_id != "normal"
                reading.update(
                    {
                        "scenario_id": scenario_id,
                        "fault_label": has_fault,
                        "severity": control.get("severity", "high"),
                        "seed": control.get("seed", 0),
                    }
                )
                if has_fault:
                    sensor = scenario["sensor"]
                    limit = next(
                        (item for item in threshold_docs if item.get("sensor") == sensor),
                        None,
                    )
                    if limit:
                        from app.services.simulation import SEVERITIES, _fault_value

                        severity = control.get("severity", "high")
                        reading["fault_sensor"] = sensor
                        if scenario_id == "sensor-disconnected":
                            reading.pop(sensor, None)
                            reading["quality"] = "partial"
                            reading["sensor_fault"] = True
                        else:
                            if severity not in SEVERITIES:
                                raise ValueError(f"Tingkat keparahan simulator tidak dikenal: {severity}")
                            reading[sensor] = _fault_value(
                                sensor,
                                float(anchor.get(sensor, 0)),
                                limit,
                                severity,
                            )
            batch.append(reading)
            moment += timedelta(minutes=INTERVAL_MINUTES)

        if not batch:
            continue
        readings().insert_many(batch, ordered=False)
        inserted += len(batch)
        if threshold_docs:
            evaluation_batch = batch if any(
                item.get("scenario_id") or item.get("sensor_fault") for item in batch
            ) else [batch[-1]]
            for item in evaluation_batch:
                evaluate_reading(item, machine, threshold_docs, ts=item["ts"])

    return inserted


async def telemetry_loop() -> None:
    while True:
        try:
            added = await asyncio.to_thread(ensure_telemetry)
            if added:
                log.info("Simulator telemetry menambah %s pembacaan", added)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Simulator telemetry gagal memperbarui data")
        await asyncio.sleep(TICK_SECONDS)
