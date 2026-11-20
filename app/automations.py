"""Hard-coded automations (Phase 2b, item 6). Each rule scans current state and records a row in
automation_runs per record it acts on, so running every 15 minutes never duplicates work.

Rules:
  inquiry_callback        new resident inquiry with no open activity -> call-back task due in 24 h
  tour_event              deal in a "Tour scheduled" stage with no event -> event on the next action date
  stale_escalation        open deal with next action 5+ days overdue -> escalation flag + high-priority task
  application_review      resident deal at "Income verified" with no review task -> review task due in 2 days
  partner_checkin         partner deal untouched for 30 days -> check-in task (at most once per 30 days)
"""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.models import Activity, AutomationRun, Deal, Pipeline
from app.schemas_crm import AutomationAction, AutomationReport

RULES = ["inquiry_callback", "tour_event", "stale_escalation", "application_review", "partner_checkin"]


def _ran(db: Session, rule: str, deal_id: int, since: datetime | None = None) -> bool:
    q = select(AutomationRun.id).where(AutomationRun.rule == rule, AutomationRun.entity == "deal",
                                       AutomationRun.entity_id == deal_id)
    if since is not None:
        q = q.where(AutomationRun.ran_at >= since)
    return db.scalar(q) is not None


def _mark(db: Session, rule: str, deal: Deal, details: dict) -> None:
    db.add(AutomationRun(rule=rule, entity="deal", entity_id=deal.id, details=details))
    write_audit(db, actor=None, action=f"automation.{rule}", entity="deal", entity_id=deal.id, details=details)


def _task(db: Session, deal: Deal, subject: str, due: datetime, kind: str = "task", priority: str = "normal") -> Activity:
    a = Activity(kind=kind, subject=subject, due_at=due, priority=priority, contact_id=deal.contact_id,
                 company_id=deal.company_id, deal_id=deal.id, assigned_to=deal.owner_id)
    db.add(a)
    db.flush()
    return a


def _open_deals(db: Session, slug: str | None = None):
    q = select(Deal).where(Deal.status == "open")
    if slug:
        q = q.join(Pipeline, Pipeline.id == Deal.pipeline_id).where(Pipeline.slug == slug)
    return db.scalars(q.order_by(Deal.id)).all()


def _has_activity(db: Session, deal_id: int, kind: str | None = None, open_only: bool = True, subject_like: str | None = None) -> bool:
    q = select(Activity.id).where(Activity.deal_id == deal_id)
    if kind:
        q = q.where(Activity.kind == kind)
    if open_only:
        q = q.where(Activity.completed_at.is_(None))
    if subject_like:
        q = q.where(Activity.subject.ilike(f"%{subject_like}%"))
    return db.scalar(q) is not None


def run_automations(db: Session, *, dry_run: bool = False, now: datetime | None = None) -> AutomationReport:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    actions: list[AutomationAction] = []

    def act(rule: str, deal: Deal, action: str, detail: str = ""):
        actions.append(AutomationAction(rule=rule, entity="deal", entity_id=deal.id, action=action, detail=detail))

    # 1. inquiry_callback
    for d in _open_deals(db, "resident-inquiry"):
        if d.stage.name != "Inquiry" or _ran(db, "inquiry_callback", d.id) or _has_activity(db, d.id):
            continue
        act("inquiry_callback", d, "create_task", "Call back new inquiry, due in 24 h")
        if not dry_run:
            _task(db, d, "Call back new inquiry", now + timedelta(hours=24))
            _mark(db, "inquiry_callback", d, {"task": "Call back new inquiry"})

    # 2. tour_event
    for d in _open_deals(db):
        if d.stage.name != "Tour scheduled" or _ran(db, "tour_event", d.id) or _has_activity(db, d.id, kind="event"):
            continue
        when = datetime.combine(d.next_action_at or today, time(hour=15), tzinfo=timezone.utc)
        act("tour_event", d, "create_event", f"Tour on {when.date()}")
        if not dry_run:
            _task(db, d, f"Tour: {d.title}", when, kind="event")
            _mark(db, "tour_event", d, {"event_on": when.date().isoformat()})

    # 3. stale_escalation
    for d in _open_deals(db):
        flagged = bool((d.extra or {}).get("escalation_flag"))
        overdue_days = (today - d.next_action_at).days if d.next_action_at else 0
        if overdue_days >= 5:
            since = datetime.combine(d.next_action_at, time.min, tzinfo=timezone.utc)
            if _ran(db, "stale_escalation", d.id, since=since):
                continue
            act("stale_escalation", d, "escalate", f"{overdue_days} days past next action")
            if not dry_run:
                d.extra = {**(d.extra or {}), "escalation_flag": True}
                _task(db, d, f"Escalation: no action in {overdue_days} days", now + timedelta(hours=4), priority="high")
                _mark(db, "stale_escalation", d, {"overdue_days": overdue_days})
        elif flagged and overdue_days <= 0:
            act("stale_escalation", d, "clear_flag", "next action is current again")
            if not dry_run:
                d.extra = {**(d.extra or {}), "escalation_flag": False}

    # 4. application_review
    for d in _open_deals(db, "resident-inquiry"):
        if d.stage.name != "Income verified" or _ran(db, "application_review", d.id) or _has_activity(db, d.id, subject_like="Review application"):
            continue
        act("application_review", d, "create_task", "Review application, due in 2 days")
        if not dry_run:
            _task(db, d, f"Review application: {d.title}", now + timedelta(days=2))
            _mark(db, "application_review", d, {})

    # 5. partner_checkin
    cutoff = now - timedelta(days=30)
    for d in _open_deals(db, "referral-partner"):
        updated = d.updated_at if d.updated_at.tzinfo else d.updated_at.replace(tzinfo=timezone.utc)
        recent_activity = db.scalar(select(Activity.id).where(Activity.deal_id == d.id, Activity.updated_at >= cutoff))
        if updated >= cutoff or recent_activity or _ran(db, "partner_checkin", d.id, since=cutoff) or _has_activity(db, d.id, subject_like="Check in"):
            continue
        act("partner_checkin", d, "create_task", "Partner quiet for 30 days")
        if not dry_run:
            _task(db, d, f"Check in with partner: {d.title}", now + timedelta(days=2))
            _mark(db, "partner_checkin", d, {"last_update": updated.isoformat()})

    if dry_run:
        db.rollback()
    else:
        db.commit()
    counts: dict[str, int] = {r: 0 for r in RULES}
    for a in actions:
        counts[a.rule] += 1
    return AutomationReport(dry_run=dry_run, ran_at=now, actions=actions, counts=counts)


