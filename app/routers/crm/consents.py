"""Consents (comparison item 5): record, list, withdraw. Never deleted."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.consents import active_consent
from app.crm_common import ensure_exists, get_or_404
from app.db import get_db
from app.models import Consent, Contact, User, utcnow
from app.schemas_crm import ConsentIn, ConsentOut, ConsentType

router = APIRouter(prefix="/api/consents", tags=["crm: consents"])


def _out(row: Consent) -> ConsentOut:
    o = ConsentOut.model_validate(row)
    o.active = row.withdrawn_at is None
    return o


@router.post("", response_model=ConsentOut, status_code=201)
def record_consent(item: ConsentIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    ensure_exists(db, Contact, item.contact_id, "Contact")
    if active_consent(db, item.contact_id, item.consent_type) is not None:
        raise HTTPException(status_code=409, detail=f"An active {item.consent_type} consent already exists "
                                                    "for this contact; withdraw it first to record a new one")
    row = Consent(contact_id=item.contact_id, consent_type=item.consent_type, source=item.source,
                  given_at=item.given_at or utcnow(), recorded_by=user.id)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="consent.record", entity="consent", entity_id=row.id,
                details={"contact_id": row.contact_id, "consent_type": row.consent_type, "source": row.source})
    db.commit()
    return _out(row)


@router.get("", response_model=list[ConsentOut])
def list_consents(contact_id: int | None = None, consent_type: ConsentType | None = None,
                  active_only: bool = False, limit: int = Query(200, ge=1, le=1000),
                  db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(Consent)
    if contact_id is not None:
        q = q.where(Consent.contact_id == contact_id)
    if consent_type:
        q = q.where(Consent.consent_type == consent_type)
    if active_only:
        q = q.where(Consent.withdrawn_at.is_(None))
    return [_out(r) for r in db.scalars(q.order_by(Consent.id.desc()).limit(limit)).all()]


@router.post("/{consent_id}/withdraw", response_model=ConsentOut)
def withdraw_consent(consent_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Consent, consent_id, "Consent")
    if row.withdrawn_at is not None:
        raise HTTPException(status_code=409, detail="This consent was already withdrawn")
    row.withdrawn_at = utcnow()
    row.withdrawn_by = user.id
    write_audit(db, actor=user, action="consent.withdraw", entity="consent", entity_id=row.id,
                details={"contact_id": row.contact_id, "consent_type": row.consent_type})
    db.commit()
    return _out(row)
