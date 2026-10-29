from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.dataset import DATASET_DAYS, INTERVAL_MINUTES, MACHINE_SPECS, _generate_rows
from app.services.predictive import MAX_HISTORY_POINTS, MODEL_HISTORY_DAYS


def test_synthetic_history_generates_one_five_sensor_set_per_interval():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    rows = _generate_rows(start, end, seed_base=5200)

    assert len(rows) == len(MACHINE_SPECS) * (24 * 60 // INTERVAL_MINUTES + 1)
    assert rows[0]["ts"] == start
    assert rows[-1]["ts"] == end
    assert {row["machine_code"] for row in rows} == {item["code"] for item in MACHINE_SPECS}
    assert all({"temperature", "vibration", "power", "sound"} <= row.keys() for row in rows)


def test_dataset_and_anomaly_model_cover_ninety_days():
    assert DATASET_DAYS == MODEL_HISTORY_DAYS == 90
    assert MAX_HISTORY_POINTS == 90 * 24 * 60 // INTERVAL_MINUTES + 1
