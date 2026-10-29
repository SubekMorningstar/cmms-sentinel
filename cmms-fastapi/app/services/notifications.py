from __future__ import annotations

from datetime import datetime

from app.database import notifications, users
from app.utils import utcnow


def notify_user(
    user_id: str,
    *,
    event_key: str,
    title: str,
    message: str,
    href: str,
    created_at: datetime | None = None,
) -> None:
    notifications().update_one(
        {"user_id": user_id, "event_key": event_key},
        {
            "$setOnInsert": {
                "user_id": user_id,
                "event_key": event_key,
                "title": title,
                "message": message,
                "href": href,
                "created_at": created_at or utcnow(),
                "read_at": None,
            }
        },
        upsert=True,
    )


def notify_role(
    role: str,
    *,
    event_key: str,
    title: str,
    message: str,
    href: str,
    created_at: datetime | None = None,
) -> None:
    for user in users().find({"role": role, "active": True}, {"_id": 1}):
        notify_user(
            str(user["_id"]),
            event_key=event_key,
            title=title,
            message=message,
            href=href,
            created_at=created_at,
        )
