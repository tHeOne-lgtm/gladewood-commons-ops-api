"""Decision log (comparison item 5). Append-only: create and read, never edit or delete."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import ensure_exists, get_or_404
from app.db import get_db
from app.fair_housing import protected_term_hits
from app.models import Contact, Deal, DecisionLog, User, utcnow
from app.schemas_crm import DecisionEntity, DecisionIn, DecisionOut

router = APIRouter(prefix="/api/decisions", tags=["crm: decisions"])
RETENTION_DAYS = 2 * 365 + 1   # Rule 11: at least two years
_MODELS = {"deal": (Deal, "Deal"), "contact": (Contact, "Contact")}


@router.post("", response_model=DecisionOut, status_code=201)
def create_decision(item: DecisionIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    hits = protected_term_hits(item.reason)
    if hits:
        raise HTTPException(status_code=422, detail={
            "message": "The reason must name the written criterion applied and may not mention a protected "
                       "trait, health, or care (Fair Housing Rules 2 and 5).",
            "terms": hits})
    model, what = _MODELS[item.entity]
    ensure_exists(db, model, item.entity_id, what)
    now = utcnow()
    row = DecisionLog(entity=item.entity, entity_id=item.entity_id, criteria_version=item.criteria_version,
                      criteria_met=item.criteria_met, outcome=item.outcome, reason=item.reason,
                      decided_by=user.id, decided_at=now, retain_until=(now + timedelta(days=RETENTION_DAYS)).date())
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="decision.create", entity="decision_log", entity_id=row.id,
                details={"entity": item.entity, "entity_id": item.entity_id, "outcome": item.outcome,
                         "criteria_version": item.criteria_version, "criteria_met": item.criteria_met})
    db.commit()
    return row


@router.get("", response_model=list[DecisionOut])
def list_decisions(entity: DecisionEntity | None = None, entity_id: int | None = None,
                   limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db),
                   _: User = Depends(require_staff)):
    q = select(DecisionLog)
    if entity:
        q = q.where(DecisionLog.entity == entity)
    if entity_id is not None:
        q = q.where(DecisionLog.entity_id == entity_id)
    return db.scalars(q.order_by(DecisionLog.id.desc()).limit(limit)).all()


@router.get("/{decision_id}", response_model=DecisionOut)
def get_decision(decision_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return get_or_404(db, DecisionLog, decision_id, "Decision")
