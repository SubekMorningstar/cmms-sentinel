from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.predictive import MIN_HEALTHY_SAMPLES, assess_machine
from app.utils import SENSOR_ORDER

THRESHOLDS = {
    "temperature": {"warning": 80, "critical": 100},
    "vibration": {"warning": 8, "critical": 12},
    "power": {"warning": 30, "critical": 40},
    "sound": {"warning": 85, "critical": 95},
}
BASE_VALUES = {"temperature": 50, "vibration": 2, "power": 10, "sound": 60}


def _history(count: int = 100) -> list[dict]:
    return [
        {
            sensor: BASE_VALUES[sensor] + (index % 3 - 1)
            for sensor in SENSOR_ORDER
        }
        for index in reversed(range(count))
    ]


def test_model_scores_a_deviation_from_machine_healthy_baseline():
    latest = {**BASE_VALUES, "temperature": 60}
    history = _history()
    history[0]["temperature"] = 60
    history[1]["temperature"] = 60

    assessment = assess_machine(latest, THRESHOLDS, history)

    assert assessment["score"] is not None
    assert assessment["score"] >= 25
    assert assessment["state"] in {"warning", "critical"}
    assert assessment["drivers"][0]["sensor"] == "temperature"
    assert assessment["drivers"][0]["baseline"] == 50
    assert "menyimpang" in assessment["drivers"][0]["reason"]


def test_single_transient_deviation_is_smoothed_by_recent_readings():
    latest = {**BASE_VALUES, "temperature": 60}

    assessment = assess_machine(latest, THRESHOLDS, _history())

    assert assessment["score"] == 0
    assert assessment["drivers"] == []


def test_sensor_critical_threshold_cannot_be_diluted_by_other_sensors():
    latest = {**BASE_VALUES, "temperature": THRESHOLDS["temperature"]["critical"]}

    assessment = assess_machine(latest, THRESHOLDS, _history())

    assert assessment["score"] >= 60
    assert assessment["state"] == "critical"
    assert assessment["drivers"][0]["reason"] == "Suhu melewati ambang kritis"


def test_stable_values_score_zero_and_report_baseline_coverage():
    assessment = assess_machine(BASE_VALUES, THRESHOLDS, _history())

    assert assessment["score"] == 0
    assert assessment["state"] == "good"
    assert assessment["trained_sensors"] == len(SENSOR_ORDER)
    assert assessment["baseline_samples"] == 100
    assert assessment["note"]


def test_insufficient_healthy_history_does_not_invent_an_ai_score():
    assessment = assess_machine(BASE_VALUES, THRESHOLDS, _history(MIN_HEALTHY_SAMPLES - 1))

    assert assessment["score"] is None
    assert assessment["state"] == "unknown"
    assert assessment["trained_sensors"] == 0
    assert "minimal 48 sampel sehat" in assessment["note"]


def test_non_finite_samples_are_ignored():
    history = _history()
    history[0]["temperature"] = float("nan")

    assessment = assess_machine(BASE_VALUES, THRESHOLDS, history)

    assert assessment["score"] is not None
    assert assessment["baseline_samples"] == 99


def test_baseline_prefers_samples_from_a_similar_time_of_day():
    latest_ts = datetime(2026, 10, 28, 7, 30, tzinfo=timezone.utc)
    history = []
    for day in range(14):
        for sample in range(4):
            history.append(
                {
                    "ts": latest_ts - timedelta(days=day + 1, minutes=30)
                    + timedelta(minutes=sample * 20),
                    **BASE_VALUES,
                }
            )
            history.append(
                {
                    "ts": latest_ts - timedelta(days=day + 1) + timedelta(hours=8, minutes=sample * 20),
                    **{**BASE_VALUES, "temperature": 75},
                }
            )
    history.sort(key=lambda reading: reading["ts"], reverse=True)

    assessment = assess_machine({**BASE_VALUES, "ts": latest_ts}, THRESHOLDS, history)

    assert assessment["baseline_context"] == "Jam operasi serupa"
    assert assessment["drivers"] == []
