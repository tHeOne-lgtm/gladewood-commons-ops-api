"""Daily digest (item 5): one plain email per staff member with their due and overdue items.
Counts and subjects only; no resident details beyond a deal title."""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.config import Settings
from app.email_provider import EmailSendError, send_email
from app.models import Activity, Deal, User

STAFF_ROLES = ("admin", "staff")


def digest_for(db: Session, user: User, now: datetime | None = None) -> tuple[str, str] | None:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    end = datetime.combine(today, time.min, tzinfo=timezone.utc) + timedelta(days=1)
    deals = db.scalars(select(Deal).where(Deal.status == "open", Deal.owner_id == user.id, Deal.next_action_at <= today)
                       .order_by(Deal.next_action_at, Deal.id)).all()
    acts = db.scalars(select(Activity).where(Activity.completed_at.is_(None), Activity.assigned_to == user.id,
                                             Activity.due_at < end).order_by(Activity.due_at, Activity.id)).all()
    if not deals and not acts:
        return None
    lines = [f"Your Gladewood list for {today.isoformat()}", ""]
    if acts:
        lines.append(f"Activities due or overdue ({len(acts)}):")
        start = datetime.combine(today, time.min, tzinfo=timezone.utc)
        for a in acts[:30]:
            when = a.due_at.date().isoformat() if a.due_at else "undated"
            due = a.due_at if a.due_at is None or a.due_at.tzinfo else a.due_at.replace(tzinfo=timezone.utc)
            flag = " OVERDUE" if due and due < start else ""
            lines.append(f"- [{a.kind}] {a.subject} (due {when}{flag})")
        lines.append("")
    if deals:
        lines.append(f"Deals needing a next action ({len(deals)}):")
        for d in deals[:30]:
            lines.append(f"- {d.title} ({d.stage.name if d.stage else '?'}; next action {d.next_action_at})")
        lines.append("")
    lines.append("Open the staff app Today view to work the list.")
    subject = f"Today: {len(acts)} activit{'y' if len(acts) == 1 else 'ies'}, {len(deals)} deal{'' if len(deals) == 1 else 's'} need action"
    return subject, "\n".join(lines)


def send_digest(db: Session, settings: Settings, now: datetime | None = None, transport=None) -> dict:
    sent, skipped, failed = [], [], []
    for u in db.scalars(select(User).where(User.role.in_(STAFF_ROLES))).all():
        if not u.email:
            skipped.append(u.id)
            continue
        made = digest_for(db, u, now)
        if made is None:
            skipped.append(u.id)
            continue
        subject, text = made
        html = "<pre style=\"font-family:system-ui,sans-serif;white-space:pre-wrap\">" + text.replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
        try:
            send_email(settings, to=u.email, subject=subject, text=text, html=html, transport=transport)
            sent.append(u.id)
        except EmailSendError as exc:
            failed.append({"user": u.id, "error": str(exc)[:200]})
    write_audit(db, actor=None, action="digest.send", entity="system", entity_id=None,
                details={"sent": len(sent), "skipped": len(skipped), "failed": len(failed)})
    db.commit()
    return {"sent": sent, "skipped": skipped, "failed": failed}
