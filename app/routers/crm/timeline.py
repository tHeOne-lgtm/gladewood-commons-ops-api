"""Chronological view of everything that happened to one record."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import get_db
from app.models import Activity, AuditLog, Deal, DealStageHistory, Note, PipelineStage, User
from app.schemas_crm import TimelineItem

router = APIRouter(prefix="/api/timeline", tags=["crm: timeline"])
ENTITIES = {"contact", "company", "deal", "property", "activity"}


@router.get("", response_model=list[TimelineItem])
def timeline(entity: str, entity_id: int, limit: int = Query(200, ge=1, le=1000),
             db: Session = Depends(get_db), _: User = Depends(require_staff)):
    if entity not in ENTITIES:
        raise HTTPException(status_code=422, detail="Unknown entity")
    items: list[TimelineItem] = []
    for a in db.scalars(select(AuditLog).where(AuditLog.entity == entity,
                                               AuditLog.entity_id == str(entity_id))).all():
        items.append(TimelineItem(at=a.at, type=a.action, summary=a.action.replace(".", " "),
                                  actor=a.actor_email, ref_id=a.id, details=a.details))
    for n in db.scalars(select(Note).where(Note.entity == entity, Note.entity_id == entity_id)).all():
        items.append(TimelineItem(at=n.created_at, type="note", summary=n.body[:200], actor=n.author_email,
                                  ref_id=n.id))
    col = {"contact": Activity.contact_id, "company": Activity.company_id, "deal": Activity.deal_id}.get(entity)
    if col is not None:
        for act in db.scalars(select(Activity).where(col == entity_id)).all():
            done = act.completed_at is not None
            items.append(TimelineItem(at=act.completed_at or act.due_at or act.created_at,
                                      type=f"activity.{act.kind}" + (".done" if done else ""),
                                      summary=act.subject, ref_id=act.id,
                                      details={"priority": act.priority, "completed": done}))
    if entity == "deal":
        names = {s.id: s.name for s in db.scalars(select(PipelineStage)).all()}
        for h in db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id == entity_id)).all():
            items.append(TimelineItem(at=h.at, type="stage",
                                      summary=f"{names.get(h.from_stage_id, 'new')} → {names.get(h.to_stage_id, '?')}",
                                      ref_id=h.id))
    if entity == "contact":
        for d in db.scalars(select(Deal).where(or_(Deal.contact_id == entity_id))).all():
            items.append(TimelineItem(at=d.created_at, type="deal", summary=d.title, ref_id=d.id,
                                      details={"status": d.status, "stage": d.stage.name if d.stage else None}))
    items.sort(key=lambda i: i.at, reverse=True)
    return items[:limit]
