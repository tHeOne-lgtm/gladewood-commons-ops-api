"""Rule 11 screening (decision log 2026-11-07, portal decision 2026-11-20).

Every free-text submission from a resident or case manager goes to the n8n "SYS Rule 11 Referral
Intake" router before it is kept. Outcomes:
  clear        store the text
  flagged      drop the text, keep a marker (date, channel, category); n8n emails Paul itself
  unreachable  hold the text with status pending_screening, write an audit row, email the alert
               address, and retry from the cron until the router answers (Paul, 2026-11-20)

Without RULE11_ROUTER_URL the local word list (app/fair_housing.py) stands in. That is for
development and tests only; production sets the URL.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.config import Settings
from app.email_provider import EmailSendError, send_email
from app.fair_housing import protected_term_hits


@dataclass
class ScreenResult:
    status: str          # clear | flagged | unreachable
    reason: str = ""


def screen(settings: Settings, *, channel: str, category: str, text: str, ref: str, transport=None) -> ScreenResult:
    if not text.strip():
        return ScreenResult("clear")
    if not settings.rule11_router_url:
        hits = protected_term_hits(text)
        return ScreenResult("flagged", ", ".join(hits)) if hits else ScreenResult("clear")
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            r = client.post(settings.rule11_router_url,
                            json={"channel": channel, "category": category, "text": text, "ref": ref,
                                  "submitted_at": datetime.now(timezone.utc).isoformat()},
                            headers={"X-Rule11-Secret": settings.rule11_secret})
        if r.status_code >= 300:
            return ScreenResult("unreachable", f"router returned {r.status_code}")
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        return ScreenResult("unreachable", str(exc)[:200])
    return ScreenResult("flagged", str(data.get("reason") or "")[:200]) if data.get("flagged") else ScreenResult("clear")


def apply_result(db: Session, row, result: ScreenResult, *, channel: str, settings: Settings, transport=None) -> None:
    """Update a maintenance request or comment in place. `row` has description-or-body, status,
    screening_status, screening_attempts, screened_at."""
    text_field = "description" if hasattr(row, "description") else "body"
    attempts = (getattr(row, "screening_attempts", 0) or 0) + 1
    if hasattr(row, "screening_attempts"):
        row.screening_attempts = attempts
    now = datetime.now(timezone.utc)
    marker = {"channel": channel, "category": getattr(row, "category", ""), "ref": f"{row.__tablename__}:{row.id}"}
    if result.status == "clear":
        row.screening_status, row.screened_at = "clear", now
        if hasattr(row, "status") and row.status == "pending_screening":
            row.status = "open"
    elif result.status == "flagged":
        setattr(row, text_field, "")  # the text never stays here; n8n keeps its own log and emails Paul
        row.screening_status, row.screened_at = "flagged", now
        if hasattr(row, "status"):
            row.status = "withheld"
        write_audit(db, actor=None, action="rule11.flagged", entity=row.__tablename__, entity_id=row.id, details=marker)
    else:
        row.screening_status = "unreachable"
        if hasattr(row, "status"):
            row.status = "pending_screening"
        write_audit(db, actor=None, action="rule11.router_unreachable", entity=row.__tablename__, entity_id=row.id,
                    details={**marker, "attempt": attempts, "reason": result.reason})
        if attempts == 1:
            _alert(settings, marker, result.reason, transport=transport)


def _alert(settings: Settings, marker: dict, reason: str, transport=None) -> None:
    if not settings.portal_alert_email:
        return
    body = (f"A portal submission is on hold because the Rule 11 router did not answer.\n\n"
            f"Reference: {marker['ref']}\nChannel: {marker['channel']}\nCategory: {marker['category']}\n"
            f"Router reply: {reason or 'no response'}\n\nThe text is held unscreened and nobody can read it in the "
            f"staff app until the router answers. The cron retries every 15 minutes.")
    try:
        send_email(settings, to=settings.portal_alert_email, subject="Portal submission held: Rule 11 router unreachable",
                   text=body, html="<pre>" + body.replace("<", "&lt;") + "</pre>", transport=transport)
    except EmailSendError:
        pass  # the audit row is the durable record; email is best effort


def retry_held(db: Session, settings: Settings, transport=None) -> dict:
    """Cron: re-screen everything the router could not answer for. Returns counts."""
    from app.models import MaintenanceComment, MaintenanceRequest
    from sqlalchemy import select
    counts = {"retried": 0, "cleared": 0, "flagged": 0, "still_held": 0}
    held = list(db.scalars(select(MaintenanceRequest).where(MaintenanceRequest.screening_status == "unreachable")).all()) + \
        list(db.scalars(select(MaintenanceComment).where(MaintenanceComment.screening_status == "unreachable")).all())
    for row in held:
        text = row.description if hasattr(row, "description") else row.body
        channel = "portal.maintenance" if hasattr(row, "description") else "portal.comment"
        res = screen(settings, channel=channel, category=getattr(row, "category", "comment"), text=text,
                     ref=f"{row.__tablename__}:{row.id}", transport=transport)
        apply_result(db, row, res, channel=channel, settings=settings)
        counts["retried"] += 1
        counts["cleared" if res.status == "clear" else "flagged" if res.status == "flagged" else "still_held"] += 1
    db.commit()
    return counts
