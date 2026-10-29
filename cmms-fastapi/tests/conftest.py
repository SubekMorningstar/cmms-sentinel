from __future__ import annotations

import os

TEST_DB = "cmms_ops_test"

os.environ["MONGODB_DB"] = TEST_DB
os.environ["APP_ENV"] = "test"
os.environ["DEMO_TELEMETRY"] = "0"
os.environ["AUTO_SEED"] = "0"
os.environ["SHOW_DEMO_CREDENTIALS"] = "0"

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_client, users
from app.main import app
from app.security import hash_password
from app.utils import utcnow


@pytest.fixture(scope="session")
def client():
    assert settings.mongodb_db.endswith("_test"), "Pengujian hanya boleh memakai database berakhiran _test"
    get_client().drop_database(settings.mongodb_db)
    with TestClient(app) as test_client:
        now = utcnow()
        users().insert_many(
            [
                {
                    "nama_lengkap": "Admin Uji",
                    "email": "admin@test.local",
                    "role": "admin",
                    "active": True,
                    "password_hash": hash_password("AdminUji#2026"),
                    "created_at": now,
                    "updated_at": now,
                    "last_login_at": None,
                },
                {
                    "nama_lengkap": "Teknisi Uji",
                    "email": "teknisi@test.local",
                    "role": "teknisi",
                    "active": True,
                    "password_hash": hash_password("TeknisiUji#2026"),
                    "created_at": now,
                    "updated_at": now,
                    "last_login_at": None,
                },
            ]
        )
        yield test_client
    get_client().drop_database(settings.mongodb_db)
    get_client().close()
