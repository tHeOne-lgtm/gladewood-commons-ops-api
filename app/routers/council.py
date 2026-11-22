"""Advisory Council sessions (Round Table artifact 3e4LdHv2q5t2e1zmrxcSJT) mirrored into the CRM. Create and read;
the verdict never changes after it is written, and Paul's decision is recorded once. Text goes through the
protected-term guard, the same rule the page applies before it convenes a panel."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import ensure_exists, get_or_404
from app.db import get_db
from app.fair_housing import protected_term_hits
from app.models import CouncilSession, Deal, Property, User, utcnow
from app.schemas_council import CouncilDecisionIn, CouncilSessionIn, CouncilSessionOut

router = APIRouter(prefix="/api/council", tags=["council"])


def _guard(*texts: str) -> None:
    hits: list[str] = []
    for t in texts:
        for h in protected_term_hits(t):
            if h not in hits:
                hits.append(h)
    if hits:
        raise HTTPException(status_code=422, detail={
            "message": "Council text may not name a protected trait, health, or care (Fair Housing Rules 2 and 5). "
                       "Write Resident A, not a name or a condition.", "terms": hits})


@router.post("", response_model=CouncilSessionOut, status_code=201)
def create_session(item: CouncilSessionIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    _guard(item.brief, item.verdict_text, item.split, item.human_check, *item.conditions)
    ensure_exists(db, Property, item.property_id, "Property")
    ensure_exists(db, Deal, item.deal_id, "Deal")
    row = CouncilSession(**item.model_dump(exclude={"held_at"}), created_by=user.id)
    if item.held_at is not None:
        row.held_at = item.held_at
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="council.create", entity="council_session", entity_id=row.id,
                details={"mode": item.mode, "door": item.door, "verdict_call": item.verdict_call,
                         "property_id": item.property_id, "deal_id": item.deal_id, "commitment_ref": item.commitment_ref})
    db.commit()
    return row


@router.get("", response_model=list[CouncilSessionOut])
def list_sessions(property_id: int | None = None, deal_id: int | None = None, commitment_ref: str | None = None,
                  due: bool = False, undecided: bool = False, limit: int = Query(200, ge=1, le=1000),
                  db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(CouncilSession)
    if property_id is not None:
        q = q.where(CouncilSession.property_id == property_id)
    if deal_id is not None:
        q = q.where(CouncilSession.deal_id == deal_id)
    if commitment_ref:
        q = q.where(CouncilSession.commitment_ref == commitment_ref)
    if due:
        q = q.where(CouncilSession.review_date.is_not(None), CouncilSession.review_date <= date.today())
    if undecided:
        q = q.where(CouncilSession.decision.is_(None))
    return db.scalars(q.order_by(CouncilSession.held_at.desc(), CouncilSession.id.desc()).limit(limit)).all()


@router.get("/{session_id}", response_model=CouncilSessionOut)
def get_session(session_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return get_or_404(db, CouncilSession, session_id, "Council session")


@router.put("/{session_id}/decision", response_model=CouncilSessionOut)
def record_decision(session_id: int, item: CouncilDecisionIn, db: Session = Depends(get_db),
                    user: User = Depends(require_staff)):
    row = get_or_404(db, CouncilSession, session_id, "Council session")
    if row.decision is not None:
        raise HTTPException(status_code=409, detail="This session already has a decision; open a new session to revisit it")
    _guard(item.decision_reason)
    row.decision = item.decision
    row.decision_reason = item.decision_reason
    row.review_date = item.review_date
    row.decided_at = utcnow()
    row.decided_by = user.id
    write_audit(db, actor=user, action="council.decide", entity="council_session", entity_id=row.id,
                details={"decision": item.decision, "review_date": item.review_date.isoformat() if item.review_date else None})
    db.commit()
    db.refresh(row)
    return row
