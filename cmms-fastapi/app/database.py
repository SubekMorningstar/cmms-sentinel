from __future__ import annotations

import logging
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import CollectionInvalid, PyMongoError

from app.config import settings

log = logging.getLogger(__name__)

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            tz_aware=True,
            appname="cmms-sentinel",
        )
    return _client


def get_db() -> Database:
    return get_client()[settings.mongodb_db]


def users() -> Collection:
    return get_db()["users"]


def machines() -> Collection:
    return get_db()["machines"]


def thresholds() -> Collection:
    return get_db()["thresholds"]


def readings() -> Collection:
    return get_db()["readings"]


def simulation_controls() -> Collection:
    return get_db()["simulation_controls"]


def simulation_runs() -> Collection:
    return get_db()["simulation_runs"]


def alerts() -> Collection:
    return get_db()["alerts"]


def work_orders() -> Collection:
    return get_db()["work_orders"]


def audit_logs() -> Collection:
    return get_db()["audit_logs"]


def counters() -> Collection:
    return get_db()["counters"]


def maintenance_plans() -> Collection:
    return get_db()["maintenance_plans"]


def inventory_items() -> Collection:
    return get_db()["inventory_items"]


def notifications() -> Collection:
    return get_db()["notifications"]


def login_attempts() -> Collection:
    return get_db()["login_attempts"]


def ensure_timeseries_collection() -> None:
    db = get_db()
    if "readings" in db.list_collection_names():
        return
    try:
        db.create_collection(
            "readings",
            timeseries={
                "timeField": "ts",
                "metaField": "machine_id",
                "granularity": "minutes",
            },
        )
    except CollectionInvalid:
        pass


def create_indexes() -> None:
    ensure_timeseries_collection()
    users().create_index("email", unique=True)
    users().create_index([("role", ASCENDING), ("active", ASCENDING)])
    machines().create_index("code", unique=True)
    machines().create_index([("active", ASCENDING), ("criticality", ASCENDING)])
    thresholds().create_index([("machine_id", ASCENDING), ("sensor", ASCENDING)], unique=True)
    simulation_controls().create_index("machine_id", unique=True)
    simulation_runs().create_index([("created_at", DESCENDING)])
    simulation_runs().create_index("run_id", unique=True)
    alerts().create_index([("machine_id", ASCENDING), ("sensor", ASCENDING), ("status", ASCENDING)])
    alerts().create_index([("status", ASCENDING), ("last_seen", DESCENDING)])
    alerts().create_index([("last_seen", DESCENDING)])
    work_orders().create_index("code", unique=True)
    work_orders().create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    work_orders().create_index([("machine_id", ASCENDING), ("created_at", DESCENDING)])
    work_orders().create_index([("assigned_to", ASCENDING), ("status", ASCENDING), ("due_at", ASCENDING)])
    work_orders().create_index("maintenance_occurrence", unique=True, sparse=True)
    maintenance_plans().create_index([("active", ASCENDING), ("next_due_at", ASCENDING)])
    inventory_items().create_index("part_code", unique=True)
    notifications().create_index([("user_id", ASCENDING), ("read_at", ASCENDING), ("created_at", DESCENDING)])
    notifications().create_index([("user_id", ASCENDING), ("event_key", ASCENDING)], unique=True)
    audit_logs().create_index([("ts", DESCENDING)])
    audit_logs().create_index([("entity", ASCENDING), ("entity_id", ASCENDING)])
    counters().create_index("_id")
    login_attempts().create_index("ts", expireAfterSeconds=900)
    login_attempts().create_index([("key", ASCENDING), ("ts", DESCENDING)])


def init_database(auto_seed: bool | None = None) -> None:
    try:
        get_client().admin.command("ping")
        create_indexes()
        should_seed = settings.auto_seed if auto_seed is None else auto_seed
        if should_seed and machines().count_documents({}) == 0:
            log.info("Database kosong, menjalankan seed dataset awal")
            from app.services.dataset import seed_all

            seed_all(reset=False)
    except PyMongoError as exc:
        log.exception("Gagal menyiapkan MongoDB: %s", exc)
        raise


def database_health() -> dict[str, Any]:
    try:
        get_client().admin.command("ping")
        return {"ok": True, "database": settings.mongodb_db}
    except PyMongoError:
        return {"ok": False, "database": settings.mongodb_db}


def close_database() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
