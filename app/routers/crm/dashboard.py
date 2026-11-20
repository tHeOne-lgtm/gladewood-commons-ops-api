"""One screen (item 10): inquiries by source, resident funnel, conversion, time in stage, overdue
follow-ups, partners gone quiet, channel volume, demand target."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import get_db
from app.models import Activity, Company, Deal, DealStageHistory, Email, Message, Pipeline, User
from app.routers.financials import read_financials
from app.schemas_crm import DashboardDeal, DashboardOut, FunnelStage, SourceCount

router = APIRouter(prefix="/api/dashboard", tags=["crm: dashboard"])
DEPOSIT_STAGES = {"Deposit received", "Confirmed"}


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("", response_model=DashboardOut)
def dashboard(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), _: User = Depends(require_staff)):
    now = datetime.now(timezone.utc)
    today = now.date()
    since = now - timedelta(days=days)
    pipelines = {p.slug: p for p in db.scalars(select(Pipeline)).all()}
    slug_of = {p.id: p.slug for p in pipelines.values()}
    resident = pipelines.get("resident-inquiry")
    partner = pipelines.get("referral-partner")

    # inquiries by source and conversion (resident deals created in the window)
    by_source: Counter = Counter()
    created = won = lost = 0
    funnel: list[FunnelStage] = []
    demand = {"target": 6, "deposits": 0, "income_verified": 0, "moved_in": 0}
    try:
        demand["target"] = int(read_financials(db).get("demand_target") or 6)
    except ValueError:
        pass
    if resident is not None:
        recent = db.scalars(select(Deal).where(Deal.pipeline_id == resident.id, Deal.created_at >= since)).all()
        for d in recent:
            created += 1
            won += d.status == "won"
            lost += d.status == "lost"
            src = ((d.contact.source if d.contact else "") or (d.extra or {}).get("source") or "other").strip().lower()
            by_source[src] += 1
        open_rows = db.scalars(select(Deal).where(Deal.pipeline_id == resident.id, Deal.status == "open")).all()
        entered: dict[int, datetime] = {}
        for h in db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id.in_([d.id for d in open_rows] or [0]))).all():
            at = _aware(h.at)
            if at and (h.deal_id not in entered or at > entered[h.deal_id]):
                entered[h.deal_id] = at
        days_by_stage: dict[int, list[float]] = defaultdict(list)
        open_by_stage: Counter = Counter()
        for d in open_rows:
            open_by_stage[d.stage_id] += 1
            start = entered.get(d.id) or _aware(d.created_at) or now
            days_by_stage[d.stage_id].append((now - start).total_seconds() / 86400)
            if d.stage and d.stage.name in DEPOSIT_STAGES:
                demand["deposits"] += 1
            if d.stage and d.stage.name == "Income verified":
                demand["income_verified"] += 1
        reached = dict(db.execute(
            select(DealStageHistory.to_stage_id, func.count(func.distinct(DealStageHistory.deal_id)))
            .where(DealStageHistory.at >= since, DealStageHistory.to_stage_id.in_([s.id for s in resident.stages]))
            .group_by(DealStageHistory.to_stage_id)).all())
        for s in resident.stages:
            ds = days_by_stage.get(s.id, [])
            funnel.append(FunnelStage(stage=s.name, reached=int(reached.get(s.id, 0)), open_now=open_by_stage.get(s.id, 0),
                                      median_days_open=round(median(ds), 1) if ds else None))
        demand["moved_in"] = won

    # overdue deals and activities (all pipelines)
    overdue_q = select(Deal).where(Deal.status == "open", Deal.next_action_at < today).order_by(Deal.next_action_at, Deal.id)
    overdue_rows = db.scalars(overdue_q).all()
    overdue_list = [DashboardDeal(id=d.id, title=d.title, pipeline=slug_of.get(d.pipeline_id, ""), stage=d.stage.name if d.stage else None,
                                  next_action_at=d.next_action_at, days=(today - d.next_action_at).days) for d in overdue_rows[:10]]
    overdue_acts = db.scalar(select(func.count()).select_from(Activity).where(Activity.completed_at.is_(None), Activity.due_at < now)) or 0

    # partners gone quiet (30 days without an update on the partner deal)
    quiet_rows: list[Deal] = []
    if partner is not None:
        cutoff = now - timedelta(days=30)
        quiet_rows = [d for d in db.scalars(select(Deal).where(Deal.pipeline_id == partner.id, Deal.status == "open")).all()
                      if (_aware(d.updated_at) or now) < cutoff]
        quiet_rows.sort(key=lambda d: _aware(d.updated_at) or now)
    quiet_list = []
    for d in quiet_rows[:10]:
        co = db.get(Company, d.company_id) if d.company_id else None
        quiet_list.append(DashboardDeal(id=d.id, title=co.name if co else d.title, pipeline="referral-partner",
                                        stage=d.stage.name if d.stage else None, next_action_at=d.next_action_at,
                                        days=(now - (_aware(d.updated_at) or now)).days))

    channels = {
        "whatsapp_in": db.scalar(select(func.count()).select_from(Message).where(Message.direction == "in", Message.created_at >= since)) or 0,
        "whatsapp_out": db.scalar(select(func.count()).select_from(Message).where(Message.direction == "out", Message.created_at >= since)) or 0,
        "emails_sent": db.scalar(select(func.count()).select_from(Email).where(Email.status.in_(["sent", "delivered"]), Email.created_at >= since)) or 0,
        "emails_opened": db.scalar(select(func.count()).select_from(Email).where(Email.opened_at.is_not(None), Email.created_at >= since)) or 0,
        "emails_bounced": db.scalar(select(func.count()).select_from(Email).where(Email.status == "bounced", Email.created_at >= since)) or 0,
    }
    return DashboardOut(
        days=days, since=since, inquiries_total=created,
        inquiries_by_source=[SourceCount(source=s, count=n) for s, n in by_source.most_common()],
        funnel=funnel,
        conversion={"inquiries": created, "moved_in": won, "closed_no_move_in": lost,
                    "rate": round(won / created, 3) if created else 0.0},
        overdue_deals=len(overdue_rows), overdue_deal_list=overdue_list, overdue_activities=int(overdue_acts),
        quiet_partners=len(quiet_rows), quiet_partner_list=quiet_list, channels=channels, demand=demand,
    )
