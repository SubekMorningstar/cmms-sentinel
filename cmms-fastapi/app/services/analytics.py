from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId

from app.database import (
    alerts,
    machines,
    readings,
    simulation_controls,
    thresholds as threshold_collection,
    work_orders,
)
from app.services.predictive import MAX_HISTORY_POINTS, MODEL_HISTORY_DAYS, assess_machine
from app.services.telemetry import (
    DATASET_SOURCE,
    DEMO_SOURCES,
    REAL_SOURCES,
    SIMULATED_SOURCE,
)
from app.utils import (
    SENSOR_ORDER,
    SOURCE_LABEL,
    health_state,
    sensor_meta,
    sensor_score,
    sensor_state,
    to_local,
    utcnow,
)

OFFLINE_AFTER_MINUTES = 15
HEALTH_WEIGHTS = {"vibration": 0.30, "temperature": 0.25, "power": 0.20, "sound": 0.25}


def _latest_reading(query: dict, projection: dict) -> dict | None:
    cursor = readings().find(query, projection).sort("ts", -1).limit(1)
    return next(cursor, None)


def shift_label(now: datetime | None = None) -> str:
    local = to_local(now or utcnow())
    hour = local.hour
    if 6 <= hour < 14:
        return "Shift 1"
    if 14 <= hour < 22:
        return "Shift 2"
    return "Shift 3"


def machine_by_code(code: str) -> dict | None:
    return machines().find_one({"code": code})


def thresholds_by_machine(machine_ids: list[ObjectId] | None = None) -> dict[ObjectId, dict[str, dict]]:
    query: dict[str, Any] = {"enabled": True}
    if machine_ids is not None:
        query["machine_id"] = {"$in": machine_ids}
    result: dict[ObjectId, dict[str, dict]] = defaultdict(dict)
    for doc in threshold_collection().find(query):
        result[doc["machine_id"]][doc["sensor"]] = doc
    return dict(result)


def latest_readings_map(machine_ids: list[ObjectId] | None = None) -> dict[ObjectId, dict]:
    docs = list(machines().find({"active": True}, {"_id": 1})) if machine_ids is None else [
        {"_id": mid} for mid in machine_ids
    ]
    latest: dict[ObjectId, dict] = {}
    for item in docs:
        doc = _latest_reading({"machine_id": item["_id"]}, {"_id": 0})
        if doc:
            latest[item["_id"]] = doc
    return latest


def open_alert_counts() -> dict[ObjectId, int]:
    counts: dict[ObjectId, int] = defaultdict(int)
    for row in alerts().aggregate(
        [
            {"$match": {"status": {"$in": ["open", "acknowledged"]}}},
            {"$group": {"_id": "$machine_id", "count": {"$sum": 1}}},
        ]
    ):
        counts[row["_id"]] = row["count"]
    return dict(counts)


def open_wo_counts() -> dict[ObjectId, int]:
    counts: dict[ObjectId, int] = defaultdict(int)
    for row in work_orders().aggregate(
        [
            {"$match": {"status": {"$in": ["pending", "in_progress"]}}},
            {"$group": {"_id": "$machine_id", "count": {"$sum": 1}}},
        ]
    ):
        counts[row["_id"]] = row["count"]
    return dict(counts)


def machine_snapshot(
    machine: dict,
    latest: dict | None,
    machine_thresholds: dict[str, dict],
    alert_count: int = 0,
    wo_count: int = 0,
    live_source: bool | None = None,
    simulation_control: dict | None = None,
) -> dict:
    predictive = {
        "score": None,
        "state": "unknown",
        "label": "Belum cukup riwayat",
        "confidence": "Belum tersedia",
        "baseline_samples": 0,
        "trained_sensors": 0,
        "history_days": MODEL_HISTORY_DAYS,
        "method": (
            "Baseline jam serupa jika cukup data, median dan MAD robust; "
            "60% sinyal tertinggi + 40% rerata berbobot"
        ),
        "baseline_context": "Belum tersedia",
        "note": "Belum cukup riwayat normal untuk membangun baseline.",
        "drivers": [],
    }
    if live_source is None:
        live_source = bool(
            readings().find_one(
                {"machine_id": machine["_id"], "source": {"$in": sorted(REAL_SOURCES)}},
                {"_id": 1},
            )
        )
    if live_source:
        latest = _latest_reading(
            {"machine_id": machine["_id"], "source": {"$nin": sorted(DEMO_SOURCES)}},
            {"_id": 0},
        )
    if latest and latest.get("ts") and machine_thresholds:
        history_start = latest["ts"] - timedelta(days=MODEL_HISTORY_DAYS)
        history_query = {
            "machine_id": machine["_id"],
            "ts": {"$gte": history_start, "$lt": latest["ts"]},
            "simulation_run_id": {"$exists": False},
            "fault_label": {"$ne": True},
        }
        if live_source:
            history_query["source"] = {"$nin": sorted(DEMO_SOURCES)}
        history = list(
            readings()
            .find(
                history_query,
                {"_id": 0, "ts": 1, **{sensor: 1 for sensor in SENSOR_ORDER}},
            )
            .sort("ts", -1)
            .limit(MAX_HISTORY_POINTS)
        )
        predictive = assess_machine(latest, machine_thresholds, history)

    sensor_data: dict[str, dict] = {}
    weighted = 0.0
    weight_total = 0.0
    for sensor in SENSOR_ORDER:
        threshold = machine_thresholds.get(sensor)
        value = latest.get(sensor) if latest else None
        meta = sensor_meta(sensor)
        if threshold and value is not None:
            state = sensor_state(float(value), threshold)
            score = sensor_score(float(value), threshold)
            weight = HEALTH_WEIGHTS.get(sensor, 0.25)
            weighted += score * weight
            weight_total += weight
        else:
            state = "unknown"
            score = None
            threshold = threshold or {}
        sensor_data[sensor] = {
            "value": value,
            "state": state,
            "score": score,
            "threshold": threshold,
            "unit": meta["unit"],
            "label": meta["label"],
        }
    score = round(weighted / weight_total, 1) if weight_total else None
    health = health_state(score)
    last_ts = latest.get("ts") if latest else None
    online = bool(last_ts and (utcnow() - last_ts) <= timedelta(minutes=OFFLINE_AFTER_MINUTES))
    source = latest.get("source") if latest else None
    active_scenario_id = None
    if (
        simulation_control
        and simulation_control.get("status", "running") == "running"
        and simulation_control.get("scenario_ends_at")
        and simulation_control["scenario_ends_at"] > utcnow()
    ):
        active_scenario_id = simulation_control.get("scenario_id")
    scenario_label = None
    if active_scenario_id:
        from app.services.simulation import SCENARIOS

        scenario_label = SCENARIOS.get(active_scenario_id, {}).get("label")
    return {
        "machine": machine,
        "id": str(machine["_id"]),
        "latest": latest,
        "last_ts": last_ts,
        "online": online,
        "score": score,
        "health": health,
        "predictive": predictive,
        "sensors": sensor_data,
        "alert_count": alert_count,
        "wo_count": wo_count,
        "source": source,
        "source_label": SOURCE_LABEL.get(source, source or "Sumber tidak diketahui"),
        "is_synthetic": source in DEMO_SOURCES,
        "scenario_id": active_scenario_id,
        "scenario_label": scenario_label,
    }


def fleet_snapshots(include_archived: bool = False) -> list[dict]:
    query = {} if include_archived else {"active": True}
    machine_docs = list(machines().find(query).sort("code", 1))
    if not machine_docs:
        return []
    ids = [doc["_id"] for doc in machine_docs]
    threshold_map = thresholds_by_machine(ids)
    latest_map = latest_readings_map(ids)
    live_machine_ids = set(
        readings().distinct("machine_id", {"source": {"$in": sorted(REAL_SOURCES)}})
    )
    alert_map = open_alert_counts()
    wo_map = open_wo_counts()
    control_map = {
        row["machine_id"]: row for row in simulation_controls().find({})
    }
    result = [
        machine_snapshot(
            machine,
            latest_map.get(machine["_id"]),
            threshold_map.get(machine["_id"], {}),
            alert_map.get(machine["_id"], 0),
            wo_map.get(machine["_id"], 0),
            machine["_id"] in live_machine_ids,
            control_map.get(machine["_id"]),
        )
        for machine in machine_docs
    ]
    return result


def fleet_kpis(snapshots: list[dict] | None = None, period_days: int = 14) -> dict[str, Any]:
    snapshots = snapshots if snapshots is not None else fleet_snapshots()
    scored = [item["score"] for item in snapshots if item["score"] is not None]
    avg_health = round(sum(scored) / len(scored), 1) if scored else None
    state_counts = defaultdict(int)
    for item in snapshots:
        state_counts[item["health"]["key"]] += 1
    now = utcnow()
    start = now - timedelta(days=period_days)
    active_alert_filter = {"status": {"$in": ["open", "acknowledged"]}}
    active_alerts = alerts().count_documents(active_alert_filter)
    critical_alerts = alerts().count_documents({**active_alert_filter, "level": "critical"})
    resolved_alerts_24h = alerts().count_documents(
        {"status": "resolved", "resolved_at": {"$gte": now - timedelta(hours=24)}}
    )
    open_wos = work_orders().count_documents({"status": {"$in": ["pending", "in_progress"]}})
    overdue_wos = work_orders().count_documents(
        {"status": {"$in": ["pending", "in_progress"]}, "due_at": {"$lt": now}}
    )
    resolved = list(
        work_orders().find(
            {"status": "resolved", "resolved_at": {"$gte": start}},
        )
    )
    corrective = [doc for doc in resolved if doc.get("type") == "corrective"]
    mttr_values = [_repair_minutes(doc) for doc in corrective if _repair_minutes(doc) is not None]
    mttr = round(sum(mttr_values) / len(mttr_values), 1) if mttr_values else None
    downtime_minutes = sum(max(int(doc.get("downtime_minutes") or 0), 0) for doc in resolved)
    machine_count = max(len([s for s in snapshots if s["machine"].get("active", True)]), 1)
    period_minutes = period_days * 24 * 60 * machine_count
    availability = round(max(0.0, (period_minutes - downtime_minutes) / period_minutes * 100), 2)
    latest_ts = max((s["last_ts"] for s in snapshots if s["last_ts"]), default=None)
    online_count = sum(1 for item in snapshots if item["online"])
    points_24h = readings().count_documents({"ts": {"$gte": now - timedelta(hours=24)}})
    return {
        "avg_health": avg_health,
        "health": health_state(avg_health),
        "states": {
            "good": state_counts.get("good", 0),
            "warning": state_counts.get("warning", 0),
            "critical": state_counts.get("critical", 0),
            "unknown": state_counts.get("unknown", 0),
        },
        "active_alerts": active_alerts,
        "critical_alerts": critical_alerts,
        "resolved_alerts_24h": resolved_alerts_24h,
        "open_wos": open_wos,
        "overdue_wos": overdue_wos,
        "mttr": mttr,
        "availability": availability,
        "online": online_count,
        "machines": len(snapshots),
        "latest_ts": latest_ts,
        "points_24h": points_24h,
        "shift": shift_label(),
        "period_days": period_days,
    }


def _repair_minutes(doc: dict) -> float | None:
    started = doc.get("started_at")
    resolved = doc.get("resolved_at")
    if started and resolved:
        return max((resolved - started).total_seconds() / 60, 0)
    downtime = doc.get("downtime_minutes")
    return float(downtime) if downtime is not None else None


def fleet_trend(hours: int = 24) -> dict[str, Any]:
    now = utcnow()
    start = now - timedelta(hours=hours)
    bucket_minutes = 15
    live_machine_ids = readings().distinct(
        "machine_id",
        {"source": {"$in": sorted(REAL_SOURCES)}},
    )
    query = {"ts": {"$gte": start}}
    if live_machine_ids:
        query["$or"] = [
            {
                "machine_id": {"$in": live_machine_ids},
                "source": {"$nin": sorted(DEMO_SOURCES)},
            },
            {"machine_id": {"$nin": live_machine_ids}},
        ]
    docs = readings().find(
        query,
        {
            "ts": 1,
            "temperature": 1,
            "vibration": 1,
            "power": 1,
            "sound": 1,
            "source": 1,
            "_id": 0,
        },
    )
    buckets: dict[datetime, dict[str, list[float]]] = defaultdict(
        lambda: {sensor: [] for sensor in SENSOR_ORDER}
    )
    sources = set()
    for doc in docs:
        ts = doc.get("ts")
        if not ts:
            continue
        if doc.get("source"):
            sources.add(doc["source"])
        local = to_local(ts)
        key = local.replace(
            minute=local.minute - local.minute % bucket_minutes,
            second=0,
            microsecond=0,
        )
        for sensor in SENSOR_ORDER:
            if doc.get(sensor) is not None:
                buckets[key][sensor].append(float(doc[sensor]))
    ordered = sorted(buckets.items())
    trend = {"labels": [key.strftime("%H:%M") for key, _ in ordered]}
    for sensor in SENSOR_ORDER:
        trend[sensor] = [
            round(sum(values[sensor]) / len(values[sensor]), 2) if values[sensor] else None
            for _, values in ordered
        ]
    trend["sources"] = sorted(sources)
    trend["has_readings"] = bool(ordered)
    trend["range_start"] = start
    trend["range_end"] = now
    return trend


def alert_breakdown() -> dict[str, Any]:
    rows = alerts().aggregate(
        [
            {"$match": {"status": {"$in": ["open", "acknowledged"]}}},
            {"$group": {"_id": {"sensor": "$sensor", "level": "$level"}, "count": {"$sum": 1}}},
        ]
    )
    result = {sensor: {"warning": 0, "critical": 0} for sensor in SENSOR_ORDER}
    for row in rows:
        sensor = row["_id"].get("sensor")
        level = row["_id"].get("level")
        if sensor in result and level in result[sensor]:
            result[sensor][level] = row["count"]
    return result


def wo_breakdown() -> dict[str, int]:
    result = {"pending": 0, "in_progress": 0, "resolved": 0, "cancelled": 0}
    for row in work_orders().aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}]):
        if row["_id"] in result:
            result[row["_id"]] = row["count"]
    return result


def active_alerts(limit: int = 6) -> list[dict]:
    docs = list(alerts().find({"status": {"$in": ["open", "acknowledged"]}}).sort("last_seen", -1).limit(limit))
    for doc in docs:
        doc["id"] = str(doc.pop("_id"))
    return docs


def active_work_orders(limit: int = 6) -> list[dict]:
    docs = list(
        work_orders()
        .find({"status": {"$in": ["pending", "in_progress"]}})
        .sort([("priority", 1), ("due_at", 1)])
        .limit(limit)
    )
    for doc in docs:
        doc["id"] = str(doc.pop("_id"))
    return docs


def monitoring_payload(machine: dict, hours: int = 24, max_points: int = 360) -> dict[str, Any]:
    threshold_docs = list(threshold_collection().find({"machine_id": machine["_id"]}))
    threshold_map = {doc["sensor"]: doc for doc in threshold_docs}
    latest = _latest_reading({"machine_id": machine["_id"]}, {"_id": 0})
    alert_count = alerts().count_documents(
        {"machine_id": machine["_id"], "status": {"$in": ["open", "acknowledged"]}}
    )
    wo_count = work_orders().count_documents(
        {"machine_id": machine["_id"], "status": {"$in": ["pending", "in_progress"]}}
    )
    snapshot = machine_snapshot(machine, latest, threshold_map, alert_count, wo_count)

    range_end = utcnow()
    start = range_end - timedelta(hours=hours)
    docs = list(
        readings()
        .find(
            {"machine_id": machine["_id"], "ts": {"$gte": start}},
            {
                "ts": 1,
                "temperature": 1,
                "vibration": 1,
                "power": 1,
                "sound": 1,
                "source": 1,
                "scenario_id": 1,
                "_id": 0,
            },
        )
        .sort("ts", 1)
    )
    sources = sorted({item.get("source") for item in docs if item.get("source")})
    first_ts = docs[0]["ts"] if docs else None
    if len(docs) > max_points:
        bucket_size = math.ceil(len(docs) / max_points)
        sampled: list[dict] = []
        for index in range(0, len(docs), bucket_size):
            chunk = docs[index : index + bucket_size]
            row = {"ts": chunk[-1]["ts"]}
            for sensor in SENSOR_ORDER:
                values = [float(item[sensor]) for item in chunk if item.get(sensor) is not None]
                row[sensor] = round(sum(values) / len(values), 2) if values else None
            sampled.append(row)
        docs = sampled

    timestamps = [int(doc["ts"].timestamp() * 1000) for doc in docs]
    series = {
        sensor: [doc.get(sensor) for doc in docs]
        for sensor in SENSOR_ORDER
    }
    thresholds_payload = {
        sensor: {
            "warning": doc.get("warning"),
            "critical": doc.get("critical"),
            "unit": sensor_meta(sensor)["unit"],
            "direction": doc.get("direction", "above"),
        }
        for sensor, doc in threshold_map.items()
    }
    recent_docs = list(
        readings()
        .find({"machine_id": machine["_id"]}, {"_id": 0})
        .sort("ts", -1)
        .limit(8)
    )
    recent = []
    for doc in recent_docs:
        states = {
            sensor: sensor_state(float(doc[sensor]), threshold_map[sensor])
            if doc.get(sensor) is not None and sensor in threshold_map
            else "unknown"
            for sensor in SENSOR_ORDER
        }
        recent.append({"ts": doc.get("ts"), "values": doc, "states": states})
    alert_docs = list(
        alerts().find({"machine_id": machine["_id"]}).sort("last_seen", -1).limit(6)
    )
    for item in alert_docs:
        item["id"] = str(item.pop("_id"))
    wo_docs = list(
        work_orders()
        .find({"machine_id": machine["_id"]})
        .sort("created_at", -1)
        .limit(5)
    )
    for item in wo_docs:
        item["id"] = str(item.pop("_id"))
    return {
        "snapshot": snapshot,
        "thresholds": thresholds_payload,
        "threshold_docs": threshold_docs,
        "series": {"timestamps": timestamps, **series},
        "recent": recent,
        "alerts": alert_docs,
        "work_orders": wo_docs,
        "hours": hours,
        "range_start": first_ts or start,
        "range_end": docs[-1]["ts"] if docs else range_end,
        "sources": sources,
    }


def dashboard_payload() -> dict[str, Any]:
    snapshots = fleet_snapshots()
    kpis = fleet_kpis(snapshots)
    trend = fleet_trend(24)
    sources = trend.pop("sources", [])
    has_readings = trend.pop("has_readings", False)
    range_start = trend.pop("range_start", None)
    range_end = trend.pop("range_end", None)
    live_sources = REAL_SOURCES
    source_labels = []
    if DATASET_SOURCE in sources:
        source_labels.append("dataset CSV")
    if SIMULATED_SOURCE in sources:
        source_labels.append("simulator")
    if live_sources.intersection(sources):
        source_labels.append("gateway IoT")
    if source_labels:
        synthetic = DATASET_SOURCE in sources or SIMULATED_SOURCE in sources
        prefix = "Data simulasi · " if synthetic else ""
        trend_source = prefix + " dan ".join(source_labels)
    elif has_readings:
        trend_source = "telemetry tersimpan (sumber belum dilabeli)"
    else:
        trend_source = "belum ada pembacaan"
    active_filter = {"status": {"$in": ["open", "acknowledged"]}}
    chart_data_sources = {
        "trend": bool(DEMO_SOURCES.intersection(sources)),
        "health": any(snapshot["is_synthetic"] for snapshot in snapshots),
        "alerts": bool(
            alerts().find_one(
                {**active_filter, "source": {"$in": sorted(DEMO_SOURCES)}},
                {"_id": 1},
            )
        ),
        "work_orders": bool(
            work_orders().find_one(
                {"simulation_run_id": {"$exists": True}},
                {"_id": 1},
            )
        ),
    }
    return {
        "snapshots": snapshots,
        "kpis": kpis,
        "trend": trend,
        "trend_source": trend_source,
        "trend_range_start": range_start,
        "trend_range_end": range_end,
        "chart_data_sources": chart_data_sources,
        "alerts": active_alerts(4),
        "work_orders": active_work_orders(6),
        "alert_breakdown": alert_breakdown(),
        "wo_breakdown": wo_breakdown(),
    }


def wo_trend(days: int = 14) -> dict[str, Any]:
    now = utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    docs = list(
        work_orders().find(
            {
                "$or": [
                    {"created_at": {"$gte": start}},
                    {"resolved_at": {"$gte": start}},
                ]
            },
            {"created_at": 1, "resolved_at": 1, "_id": 0},
        )
    )
    local_start = to_local(start).replace(hour=0, minute=0, second=0, microsecond=0)
    buckets = {
        (local_start + timedelta(days=index)).date(): {"created": 0, "resolved": 0}
        for index in range(days)
    }
    for doc in docs:
        if doc.get("created_at"):
            day = to_local(doc["created_at"]).date()
            if day in buckets:
                buckets[day]["created"] += 1
        if doc.get("resolved_at"):
            day = to_local(doc["resolved_at"]).date()
            if day in buckets:
                buckets[day]["resolved"] += 1
    ordered = sorted(buckets.items())
    return {
        "labels": [day.strftime("%d/%m") for day, _ in ordered],
        "created": [value["created"] for _, value in ordered],
        "resolved": [value["resolved"] for _, value in ordered],
    }


def report_payload(days: int = 14) -> dict[str, Any]:
    now = utcnow()
    start = now - timedelta(days=days)
    snapshots = fleet_snapshots()
    source_rows = list(
        readings().aggregate(
            [
                {"$match": {"ts": {"$gte": start, "$lte": now}}},
                {
                    "$group": {
                        "_id": "$source",
                        "count": {"$sum": 1},
                        "first_ts": {"$min": "$ts"},
                        "last_ts": {"$max": "$ts"},
                    }
                },
                {"$sort": {"_id": 1}},
            ]
        )
    )
    source_breakdown = [
        {
            "source": row.get("_id") or "unknown",
            "label": SOURCE_LABEL.get(row.get("_id"), row.get("_id") or "Tidak diketahui"),
            "count": row["count"],
            "first_ts": row["first_ts"],
            "last_ts": row["last_ts"],
            "is_synthetic": row.get("_id") in DEMO_SOURCES,
        }
        for row in source_rows
    ]
    synthetic_work_order_query = {
        "simulation_run_id": {"$exists": True},
        "$or": [
            {"created_at": {"$gte": start, "$lte": now}},
            {"resolved_at": {"$gte": start, "$lte": now}},
        ],
    }
    chart_data_sources = {
        "work_orders": bool(
            work_orders().find_one(synthetic_work_order_query, {"_id": 1})
        ),
        "health": any(snapshot["is_synthetic"] for snapshot in snapshots),
    }
    resolved = list(work_orders().find({"status": "resolved", "resolved_at": {"$gte": start}}))
    opened = list(work_orders().find({"created_at": {"$gte": start}}))
    failure_docs = [doc for doc in resolved if doc.get("type") == "corrective"]
    mttr_values = [value for doc in failure_docs if (value := _repair_minutes(doc)) is not None]
    mttr = round(sum(mttr_values) / len(mttr_values), 1) if mttr_values else None
    machine_count = max(len(snapshots), 1)
    operating_minutes = days * 24 * 60 * machine_count
    downtime_minutes = sum(max(int(doc.get("downtime_minutes") or 0), 0) for doc in resolved)
    availability = round(max(0.0, (operating_minutes - downtime_minutes) / operating_minutes * 100), 2)
    failures = len(failure_docs)
    mtbf = round((operating_minutes - downtime_minutes) / failures / 60, 1) if failures else None
    with_due = [doc for doc in resolved if doc.get("due_at") and doc.get("resolved_at")]
    on_time = [doc for doc in with_due if doc["resolved_at"] <= doc["due_at"]]
    compliance = round(len(on_time) / len(with_due) * 100, 1) if with_due else None
    per_machine = []
    for snapshot in snapshots:
        machine = snapshot["machine"]
        machine_resolved = [doc for doc in resolved if doc.get("machine_id") == machine["_id"]]
        machine_failures = [doc for doc in machine_resolved if doc.get("type") == "corrective"]
        values = [value for doc in machine_resolved if (value := _repair_minutes(doc)) is not None]
        downtime = sum(max(int(doc.get("downtime_minutes") or 0), 0) for doc in machine_resolved)
        machine_operating = days * 24 * 60
        per_machine.append(
            {
                "machine": machine,
                "id": str(machine["_id"]),
                "failures": len(machine_failures),
                "resolved": len(machine_resolved),
                "downtime": downtime,
                "mttr": round(sum(values) / len(values), 1) if values else None,
                "availability": round(
                    max(0.0, (machine_operating - downtime) / machine_operating * 100), 2
                ),
                "health": snapshot["health"],
                "score": snapshot["score"],
                "open_wos": snapshot["wo_count"],
                "active_alerts": snapshot["alert_count"],
                "source": snapshot["source"],
                "source_label": snapshot["source_label"],
                "is_synthetic": snapshot["is_synthetic"],
                "scenario_label": snapshot["scenario_label"],
            }
        )
    status_counts = {key: 0 for key in ["pending", "in_progress", "resolved", "cancelled"]}
    for doc in opened:
        status = doc.get("status", "pending")
        if status in status_counts:
            status_counts[status] += 1
    return {
        "days": days,
        "kpis": {
            "mttr": mttr,
            "mtbf": mtbf,
            "availability": availability,
            "compliance": compliance,
            "downtime": downtime_minutes,
            "failures": failures,
            "resolved": len(resolved),
            "opened": len(opened),
            "backlog": work_orders().count_documents({"status": {"$in": ["pending", "in_progress"]}}),
        },
        "per_machine": per_machine,
        "wo_trend": wo_trend(days),
        "wo_breakdown": status_counts,
        "alert_breakdown": alert_breakdown(),
        "snapshots": snapshots,
        "source_breakdown": source_breakdown,
        "chart_data_sources": chart_data_sources,
        "range_start": start,
        "range_end": now,
    }


def dataset_stats() -> dict[str, Any]:
    first = next(
        readings().find({}, {"ts": 1, "_id": 0}).sort("ts", 1).limit(1), None
    )
    last = _latest_reading({}, {"ts": 1, "_id": 0})
    return {
        "readings": readings().count_documents({}),
        "machines": machines().count_documents({}),
        "alerts": alerts().count_documents({}),
        "work_orders": work_orders().count_documents({}),
        "first_ts": first.get("ts") if first else None,
        "last_ts": last.get("ts") if last else None,
        "latest_reading": _latest_reading({}, {"_id": 0}),
    }
