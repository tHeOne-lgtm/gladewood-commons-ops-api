from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import csv_response, diff, ensure_exists, get_or_404, snapshot
from app.db import get_db
from app.models import Activity, Company, Contact, Deal, User, utcnow
from app.schemas import DeleteResult
from app.schemas_crm import ActivityIn, ActivityOut

router = APIRouter(prefix="/api/activities", tags=["crm: activities"])
FIELDS = list(ActivityIn.model_fields) + ["completed_at"]
CSV_FIELDS = ["id"] + FIELDS + ["created_at"]


def _validate(db: Session, item: ActivityIn) -> None:
    ensure_exists(db, Contact, item.contact_id, "Contact")
    ensure_exists(db, Company, item.company_id, "Company")
    ensure_exists(db, Deal, item.deal_id, "Deal")
    if item.assigned_to is not None and db.get(User, item.assigned_to) is None:
        raise HTTPException(status_code=422, detail="assigned_to is not a known user")


def _query(kind, open_only, assigned_to, contact_id, company_id, deal_id, due_before, overdue):
    stmt = select(Activity)
    if kind:
        stmt = stmt.where(Activity.kind == kind)
    if open_only:
        stmt = stmt.where(Activity.completed_at.is_(None))
    for col, val in ((Activity.assigned_to, assigned_to), (Activity.contact_id, contact_id),
                     (Activity.company_id, company_id), (Activity.deal_id, deal_id)):
        if val is not None:
            stmt = stmt.where(col == val)
    if due_before is not None:
        stmt = stmt.where(Activity.due_at <= due_before)
    if overdue:
        stmt = stmt.where(Activity.due_at < utcnow(), Activity.completed_at.is_(None))
    return stmt.order_by(Activity.due_at.asc().nulls_last(), Activity.id.desc())


@router.get("", response_model=list[ActivityOut])
def list_activities(kind: str | None = None, open_only: bool = True, assigned_to: str | None = None,
                    mine: bool = False, contact_id: int | None = None, company_id: int | None = None,
                    deal_id: int | None = None, due_before: datetime | None = None, overdue: bool = False,
                    limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db), user: User = Depends(require_staff)):
    if mine:
        assigned_to = user.id
    return db.scalars(_query(kind, open_only, assigned_to, contact_id, company_id, deal_id, due_before,
                             overdue).limit(limit).offset(offset)).all()


@router.get("/export")
def export_activities(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows = db.scalars(_query(None, False, None, None, None, None, None, False)).all()
    return csv_response("activities.csv", CSV_FIELDS, (snapshot(r, CSV_FIELDS) for r in rows))


@router.get("/{row_id}", response_model=ActivityOut)
def get_activity(row_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return get_or_404(db, Activity, row_id, "Activity")


@router.post("", response_model=ActivityOut, status_code=201)
def create_activity(item: ActivityIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    _validate(db, item)
    row = Activity(**item.model_dump())
    if row.assigned_to is None:
        row.assigned_to = user.id
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="activity.create", entity="activity", entity_id=row.id,
                details=snapshot(row, FIELDS))
    db.commit()
    db.refresh(row)
    return row


@router.put("/{row_id}", response_model=ActivityOut)
def update_activity(row_id: int, item: ActivityIn, db: Session = Depends(get_db),
                    user: User = Depends(require_staff)):
    row = get_or_404(db, Activity, row_id, "Activity")
    _validate(db, item)
    before = snapshot(row, FIELDS)
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    write_audit(db, actor=user, action="activity.update", entity="activity", entity_id=row_id,
                details={"changes": diff(before, snapshot(row, FIELDS))})
    db.commit()
    db.refresh(row)
    return row


@router.post("/{row_id}/complete", response_model=ActivityOut)
def complete_activity(row_id: int, undo: bool = False, db: Session = Depends(get_db),
                      user: User = Depends(require_staff)):
    row = get_or_404(db, Activity, row_id, "Activity")
    row.completed_at = None if undo else (row.completed_at or utcnow())
    write_audit(db, actor=user, action="activity.reopen" if undo else "activity.complete",
                entity="activity", entity_id=row_id)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{row_id}", response_model=DeleteResult)
def delete_activity(row_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Activity, row_id, "Activity")
    write_audit(db, actor=user, action="activity.delete", entity="activity", entity_id=row_id,
                details=snapshot(row, FIELDS))
    db.delete(row)
    db.commit()
    return DeleteResult(deleted=row_id)
