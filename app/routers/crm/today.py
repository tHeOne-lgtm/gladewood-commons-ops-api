"""GET /api/today: what needs attention today (comparison item 2, adopted 2026-11-09).

Returns counts for the signed-in staff member and for everyone, plus the member's own
overdue and due-today deals and activities by title. No contact records, so the counts
can feed the Command Center page without putting personal data in it (decision 1).
"""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import get_db
from app.models import Activity, Deal, User
from app.schemas_crm import TodayActivity, TodayCounts, TodayDeal, TodayOut

router = APIRouter(prefix="/api/today", tags=["crm: today"])


def _counts(db: Session, today: date, now: datetime, end: datetime, owner: str | None) -> TodayCounts:
    """Deals are dated by day; activities by the minute, so an activity is overdue once its
    time has passed (same rule as the activities list's `overdue` filter)."""
    deals = select(func.count()).select_from(Deal).where(Deal.status == "open")
    acts = select(func.count()).select_from(Activity).where(Activity.completed_at.is_(None))
    if owner is not None:
        deals = deals.where(Deal.owner_id == owner)
        acts = acts.where(Activity.assigned_to == owner)
    return TodayCounts(
        deals_overdue=db.scalar(deals.where(Deal.next_action_at < today)),
        deals_due_today=db.scalar(deals.where(Deal.next_action_at == today)),
        activities_overdue=db.scalar(acts.where(Activity.due_at < now)),
        activities_due_today=db.scalar(acts.where(Activity.due_at >= now, Activity.due_at < end)),
        open_deals=db.scalar(deals),
    )


@router.get("", response_model=TodayOut)
def today(db: Session = Depends(get_db), user: User = Depends(require_staff)):
    now = datetime.now(timezone.utc)
    today_ = now.date()
    end = datetime.combine(today_, time.min, tzinfo=timezone.utc) + timedelta(days=1)
    deals = db.scalars(select(Deal).where(Deal.status == "open", Deal.owner_id == user.id,
                                          Deal.next_action_at <= today_)
                       .order_by(Deal.next_action_at, Deal.id)).all()
    acts = db.scalars(select(Activity).where(Activity.completed_at.is_(None), Activity.assigned_to == user.id,
                                             Activity.due_at < end)
                      .order_by(Activity.due_at, Activity.id)).all()
    return TodayOut(
        date=today_,
        mine=_counts(db, today_, now, end, user.id),
        all=_counts(db, today_, now, end, None),
        deals=[TodayDeal(id=d.id, title=d.title, pipeline_id=d.pipeline_id,
                         stage_name=d.stage.name if d.stage else None, next_action_at=d.next_action_at,
                         owner_id=d.owner_id) for d in deals],
        activities=[TodayActivity(id=a.id, kind=a.kind, subject=a.subject, due_at=a.due_at, deal_id=a.deal_id,
                                  assigned_to=a.assigned_to) for a in acts],
    )
