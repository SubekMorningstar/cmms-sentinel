from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name: str = os.getenv("APP_NAME", "CMMS Sentinel")
    app_env: str = os.getenv("APP_ENV", "development")
    app_debug: bool = _bool("APP_DEBUG", False)
    app_version: str = "2.2.0"
    secret_key: str = os.getenv("APP_SECRET_KEY", "")
    session_cookie: str = os.getenv("SESSION_COOKIE", "cmms_sentinel_session")
    session_max_age: int = int(os.getenv("SESSION_MAX_AGE", "28800"))
    session_https_only: bool = _bool("SESSION_HTTPS_ONLY", False)
    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
    mongodb_db: str = os.getenv("MONGODB_DB", "cmms_ops")
    ingest_api_key: str = os.getenv("INGEST_API_KEY", "")
    auto_seed: bool = _bool("AUTO_SEED", True)
    demo_telemetry: bool = _bool(
        "DEMO_TELEMETRY",
        os.getenv("APP_ENV", "development").strip().lower() not in {"production", "prod"},
    )
    show_demo_credentials: bool = _bool("SHOW_DEMO_CREDENTIALS", False)
    seed_admin_email: str = os.getenv("SEED_ADMIN_EMAIL", "admin@cmms.test")
    seed_admin_password: str = os.getenv("SEED_ADMIN_PASSWORD", "Admin#2026!")
    seed_teknisi_email: str = os.getenv("SEED_TEKNISI_EMAIL", "teknisi@cmms.test")
    seed_teknisi_password: str = os.getenv("SEED_TEKNISI_PASSWORD", "Teknisi#2026!")
    timezone: str = os.getenv("APP_TIMEZONE", "Asia/Jakarta")
    dataset_readings_csv: Path = DATA_DIR / "sensor_readings.csv"
    dataset_scenarios_csv: Path = DATA_DIR / "fault_scenarios.csv"
    dataset_metadata: Path = DATA_DIR / "DATASET.md"


settings = Settings()

if not settings.secret_key:
    raise RuntimeError("APP_SECRET_KEY belum diatur pada .env")
if not settings.ingest_api_key:
    raise RuntimeError("INGEST_API_KEY belum diatur pada .env")
