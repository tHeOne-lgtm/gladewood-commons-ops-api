"""Chronological view of everything that happened to one record."""
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import get_db
from app.models import Activity, AuditLog, Deal, DealStageHistory, Email, Message, Note, PipelineStage, User
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
        for e in db.scalars(select(Email).where(Email.deal_id == entity_id)).all():
            items.append(TimelineItem(at=e.sent_at or e.created_at, type="email.out", summary=e.subject[:200], actor=e.sent_by,
                                      ref_id=e.id, details={"status": e.status, "skip_reason": e.skip_reason}))
        names = {s.id: s.name for s in db.scalars(select(PipelineStage)).all()}
        for h in db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id == entity_id)).all():
            items.append(TimelineItem(at=h.at, type="stage",
                                      summary=f"{names.get(h.from_stage_id, 'new')} → {names.get(h.to_stage_id, '?')}",
                                      ref_id=h.id))
    if entity == "contact":
        for m in db.scalars(select(Message).where(Message.contact_id == entity_id)).all():
            items.append(TimelineItem(at=m.created_at, type=f"message.{m.direction}", summary=m.body[:200] or f"({m.media_count} media)",
                                      ref_id=m.id, details={"status": m.status, "channel": m.channel}))
        for e in db.scalars(select(Email).where(Email.contact_id == entity_id)).all():
            items.append(TimelineItem(at=e.sent_at or e.created_at, type="email.out", summary=e.subject[:200], actor=e.sent_by,
                                      ref_id=e.id, details={"status": e.status, "skip_reason": e.skip_reason,
                                                            "campaign_id": e.campaign_id, "opened": e.opened_at is not None}))
        for d in db.scalars(select(Deal).where(or_(Deal.contact_id == entity_id))).all():
            items.append(TimelineItem(at=d.created_at, type="deal", summary=d.title, ref_id=d.id,
                                      details={"status": d.status, "stage": d.stage.name if d.stage else None}))
    items.sort(key=lambda i: i.at if i.at.tzinfo else i.at.replace(tzinfo=timezone.utc), reverse=True)
    return items[:limit]
