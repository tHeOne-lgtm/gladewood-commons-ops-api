"""Consent lookups for other modules (n8n drafts, the portal) before any message goes out."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Consent


def active_consent(db: Session, contact_id: int, consent_type: str) -> Consent | None:
    return db.scalar(select(Consent).where(Consent.contact_id == contact_id,
                                           Consent.consent_type == consent_type,
                                           Consent.withdrawn_at.is_(None)))


def has_consent(db: Session, contact_id: int, consent_type: str) -> bool:
    return active_consent(db, contact_id, consent_type) is not None
