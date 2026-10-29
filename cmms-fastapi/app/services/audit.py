from __future__ import annotations

from bson import ObjectId
from fastapi import Request

from app.database import audit_logs
from app.utils import utcnow


def audit(
    actor: dict | None,
    action: str,
    entity: str,
    entity_id: str | ObjectId | None = None,
    detail: str | None = None,
    request: Request | None = None,
) -> None:
    ip = ""
    if request is not None and request.client:
        ip = request.client.host
    audit_logs().insert_one(
        {
            "ts": utcnow(),
            "actor_id": actor.get("id") if actor else None,
            "actor_name": actor.get("nama_lengkap") if actor else "Sistem",
            "actor_role": actor.get("role") if actor else "system",
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id) if entity_id else None,
            "detail": detail or "",
            "ip": ip,
        }
    )
