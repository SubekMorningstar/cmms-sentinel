from __future__ import annotations

import math
from datetime import datetime
from statistics import median
from typing import Any

from app.utils import SENSOR_ORDER, sensor_meta, sensor_state, to_local

MODEL_HISTORY_DAYS = 90
MAX_HISTORY_POINTS = MODEL_HISTORY_DAYS * 24 * 60 // 5 + 1
MIN_HEALTHY_SAMPLES = 48
SENSOR_WEIGHTS = {"vibration": 0.30, "temperature": 0.25, "power": 0.20, "sound": 0.25}
SIMILAR_HOUR_WINDOW_MINUTES = 90
RECENT_WINDOW_MINUTES = 30


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _risk_label(score: float | None) -> tuple[str, str]:
    if score is None:
        return "unknown", "Belum cukup riwayat"
    if score < 25:
        return "good", "Pola stabil"
    if score < 60:
        return "warning", "Perlu dipantau"
    return "critical", "Anomali kuat"


def _similar_time_of_day(reading_ts: Any, latest_ts: Any) -> bool:
    if not isinstance(reading_ts, datetime) or not isinstance(latest_ts, datetime):
        return False
    reading_local = to_local(reading_ts)
    latest_local = to_local(latest_ts)
    if reading_local is None or latest_local is None:
        return False
    reading_minutes = reading_local.hour * 60 + reading_local.minute
    latest_minutes = latest_local.hour * 60 + latest_local.minute
    distance = abs(reading_minutes - latest_minutes)
    return min(distance, 1440 - distance) <= SIMILAR_HOUR_WINDOW_MINUTES


def _is_recent(reading_ts: Any, latest_ts: Any) -> bool:
    if not isinstance(reading_ts, datetime) or not isinstance(latest_ts, datetime):
        return reading_ts is None and latest_ts is None
    reading_local = to_local(reading_ts)
    latest_local = to_local(latest_ts)
    if reading_local is None or latest_local is None:
        return False
    age_minutes = (latest_local - reading_local).total_seconds() / 60
    return 0 <= age_minutes <= RECENT_WINDOW_MINUTES


def assess_machine(
    latest: dict | None,
    thresholds: dict[str, dict],
    history: list[dict],
) -> dict[str, Any]:
    """Score sensor deviations from each machine's own healthy baseline."""
    drivers = []
    weighted_risk = 0.0
    weight_total = 0.0
    sample_counts = []
    sensor_risks = []
    baseline_contexts = []

    for sensor in SENSOR_ORDER:
        threshold = thresholds.get(sensor)
        current = _number((latest or {}).get(sensor))
        if not threshold or current is None:
            continue

        healthy_history = []
        time_matched_history = []
        recent_values = [current]
        for reading in history:
            value = _number(reading.get(sensor))
            if value is None:
                continue
            reading_ts = reading.get("ts")
            latest_ts = (latest or {}).get("ts")
            if len(recent_values) < 3 and _is_recent(reading_ts, latest_ts):
                recent_values.append(value)
            if sensor_state(value, threshold) == "normal":
                healthy_history.append(value)
                if _similar_time_of_day(reading_ts, latest_ts):
                    time_matched_history.append(value)

        use_time_matched = len(time_matched_history) >= MIN_HEALTHY_SAMPLES
        baseline = time_matched_history if use_time_matched else healthy_history
        if len(baseline) < MIN_HEALTHY_SAMPLES:
            continue

        center = median(baseline)
        deviations = [abs(value - center) for value in baseline]
        mad_scale = median(deviations) * 1.4826
        iqr_scale = (_percentile(baseline, 0.75) - _percentile(baseline, 0.25)) / 1.349
        threshold_span = abs(
            (_number(threshold.get("critical")) or 0)
            - (_number(threshold.get("warning")) or 0)
        )
        scale_floor = max(threshold_span * 0.05, abs(center) * 0.0001, 0.001)
        scale = max(mad_scale, iqr_scale, scale_floor)
        observed = median(recent_values)
        deviation = abs(observed - center) / scale
        anomaly_risk = min(max((deviation - 2.5) * 20, 0), 100)

        current_state = sensor_state(current, threshold)
        threshold_floor = {"normal": 0, "warning": 60, "critical": 100}.get(current_state, 0)
        risk = round(max(anomaly_risk, threshold_floor), 1)
        weight = SENSOR_WEIGHTS.get(sensor, 0.25)
        weighted_risk += risk * weight
        weight_total += weight
        sensor_risks.append(risk)
        sample_counts.append(len(baseline))
        baseline_contexts.append(use_time_matched)

        if risk > 0:
            meta = sensor_meta(sensor)
            if current_state != "normal":
                state_label = {"warning": "peringatan", "critical": "kritis"}[current_state]
                reason = f"{meta['label']} melewati ambang {state_label}"
            else:
                reason = f"{meta['label']} menyimpang {deviation:.1f}× dari variasi normal"
            drivers.append(
                {
                    "sensor": sensor,
                    "label": meta["label"],
                    "unit": meta["unit"],
                    "value": current,
                    "baseline": round(center, 2),
                    "deviation": round(deviation, 1),
                    "risk": risk,
                    "reason": reason,
                }
            )

    weighted_average = weighted_risk / weight_total if weight_total else None
    score = (
        round(0.6 * max(sensor_risks) + 0.4 * weighted_average, 1)
        if weighted_average is not None
        else None
    )
    state, label = _risk_label(score)
    drivers.sort(key=lambda item: item["risk"], reverse=True)

    if not sample_counts:
        note = (
            "Belum cukup riwayat normal; dibutuhkan minimal "
            f"{MIN_HEALTHY_SAMPLES} sampel sehat per sensor."
        )
        confidence = "Belum tersedia"
        baseline_samples = 0
    else:
        baseline_samples = min(sample_counts)
        if len(sample_counts) == len(SENSOR_ORDER) and baseline_samples >= 500:
            confidence = "Tinggi"
        elif len(sample_counts) >= 2 and baseline_samples >= 120:
            confidence = "Sedang"
        else:
            confidence = "Terbatas"
        note = (
            "Tidak ada penyimpangan bermakna dari baseline normal yang dipelajari."
            if not drivers
            else ""
        )

    return {
        "score": score,
        "state": state,
        "label": label,
        "confidence": confidence,
        "baseline_samples": baseline_samples,
        "trained_sensors": len(sample_counts),
        "history_days": MODEL_HISTORY_DAYS,
        "method": (
            "Baseline jam serupa jika cukup data, median dan MAD robust; "
            "60% sinyal tertinggi + 40% rerata berbobot"
        ),
        "baseline_context": "Jam operasi serupa" if baseline_contexts and all(baseline_contexts) else "Seluruh jam",
        "note": note,
        "drivers": drivers[:3],
    }
