from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import analytics
from app.utils import SENSOR_ORDER


def test_fleet_trend_averages_all_four_sensors_per_15_minutes(monkeypatch):
    now = datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc)
    first = now - timedelta(minutes=10)
    second = now - timedelta(minutes=30)

    class Readings:
        def distinct(self, field, query):
            assert field == "machine_id"
            assert query == {"source": {"$in": ["api", "edge", "gateway", "iot"]}}
            return []

        def find(self, query, projection):
            assert query == {"ts": {"$gte": now - timedelta(hours=24)}}
            assert {"temperature", "vibration", "power", "sound", "source"} <= projection.keys()
            return iter(
                [
                    {
                        "ts": first,
                        "temperature": 40,
                        "vibration": 2,
                        "power": 12,
                        "sound": 65,
                        "source": "gateway",
                    },
                    {
                        "ts": second,
                        "temperature": 50,
                        "vibration": 4,
                        "power": 14,
                        "sound": 75,
                        "source": "dataset-seed",
                    },
                ]
            )

    monkeypatch.setattr(analytics, "utcnow", lambda: now)
    monkeypatch.setattr(analytics, "readings", Readings)

    trend = analytics.fleet_trend()
    first_bucket = analytics.to_local(first).replace(minute=15, second=0, microsecond=0)
    second_bucket = analytics.to_local(second).replace(minute=0, second=0, microsecond=0)

    assert trend == {
        "labels": [second_bucket.strftime("%H:%M"), first_bucket.strftime("%H:%M")],
        "temperature": [50.0, 40.0],
        "vibration": [4.0, 2.0],
        "power": [14.0, 12.0],
        "sound": [75.0, 65.0],
        "sources": ["dataset-seed", "gateway"],
        "has_readings": True,
        "range_start": now - timedelta(hours=24),
        "range_end": now,
    }


def test_fleet_trend_excludes_demo_rows_for_machines_with_gateway_data(monkeypatch):
    now = datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc)
    live_machine_id = "machine-live"

    class Readings:
        def distinct(self, field, query):
            assert field == "machine_id"
            return [live_machine_id]

        def find(self, query, projection):
            assert query == {
                "ts": {"$gte": now - timedelta(hours=24)},
                "$or": [
                    {
                        "machine_id": {"$in": [live_machine_id]},
                        "source": {"$nin": ["dataset-seed", "simulator"]},
                    },
                    {"machine_id": {"$nin": [live_machine_id]}},
                ],
            }
            return iter([])

    monkeypatch.setattr(analytics, "utcnow", lambda: now)
    monkeypatch.setattr(analytics, "readings", Readings)

    trend = analytics.fleet_trend()

    assert trend["sources"] == []
    assert trend["has_readings"] is False


def test_machine_model_uses_gateway_latest_and_excludes_demo_history(monkeypatch):
    now = datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc)
    machine = {"_id": "machine-live"}
    thresholds = {
        sensor: {"warning": 100, "critical": 200}
        for sensor in SENSOR_ORDER
    }
    latest_gateway = {
        "ts": now,
        "source": "gateway",
        "temperature": 50,
        "vibration": 2,
        "power": 10,
        "sound": 60,
    }
    history_queries = []

    class Cursor:
        def __init__(self, docs):
            self.docs = iter(docs)

        def sort(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.docs)

    class Readings:
        def find(self, query, _projection):
            if "ts" not in query:
                assert query == {
                    "machine_id": machine["_id"],
                    "source": {"$nin": ["dataset-seed", "simulator"]},
                }
                return Cursor([latest_gateway])
            history_queries.append(query)
            return Cursor([])

    monkeypatch.setattr(analytics, "readings", Readings)
    monkeypatch.setattr(analytics, "utcnow", lambda: now)

    snapshot = analytics.machine_snapshot(
        machine,
        {"source": "simulator"},
        thresholds,
        live_source=True,
    )

    assert snapshot["latest"]["source"] == "gateway"
    assert history_queries[0]["source"] == {"$nin": ["dataset-seed", "simulator"]}
