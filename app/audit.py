"""Append-only audit log helper."""
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def write_audit(
    db: Session,
    *,
    actor: User | None,
    action: str,
    entity: str,
    entity_id: Any = None,
    details: dict | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        entity=entity,
        entity_id=None if entity_id is None else str(entity_id),
        details=details,
    )
    db.add(row)
    return row
