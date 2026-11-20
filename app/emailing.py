"""Email rendering, compliance footer, consent gate, 1:1 send, unsubscribe tokens, and provider
events (Phase 2c, items 9 and 10).

Rules baked in:
- Every message carries the postal address, the Equal Housing Opportunity line, and an unsubscribe
  link (CAN-SPAM; Fair Housing advertising rule from docs/BIGIN_TOP10_PLAN.md section 7).
- Marketing sends need an active email consent. Transactional sends only need the contact not to
  have unsubscribed or bounced.
- Templates and ad hoc bodies are refused when they contain protected-trait terms.
"""
import hashlib
import hmac
import html as html_lib
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.config import Settings
from app.consents import active_consent
from app.email_provider import EmailSendError, send_email
from app.fair_housing import protected_term_hits
from app.models import Consent, Contact, Deal, Email, EmailTemplate, utcnow

MERGE_FIELDS = ("first_name", "display_name", "email", "company_name", "deal_title", "stage_name",
                "next_action_at", "room_preference", "move_in_target", "sender_name", "unsubscribe_url")
_TAG = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
EHO_LINE = "Equal Housing Opportunity."


def unknown_fields(*texts: str) -> list[str]:
    bad: list[str] = []
    for t in texts:
        for m in _TAG.finditer(t or ""):
            if m.group(1) not in MERGE_FIELDS and m.group(1) not in bad:
                bad.append(m.group(1))
    return bad


def lint(subject: str, body: str) -> list[str]:
    """Protected-trait terms in a template or message; the API refuses to save or send when non-empty."""
    return protected_term_hits(f"{subject}\n{body}")


def unsubscribe_token(settings: Settings, contact_id: int) -> str:
    secret = settings.email_unsubscribe_secret or settings.supabase_jwt_secret or "dev"
    mac = hmac.new(secret.encode(), str(contact_id).encode(), hashlib.sha256).hexdigest()[:32]
    return f"{contact_id}.{mac}"


def parse_unsubscribe_token(settings: Settings, token: str) -> int | None:
    try:
        cid_s, mac = token.split(".", 1)
        cid = int(cid_s)
    except ValueError:
        return None
    return cid if hmac.compare_digest(unsubscribe_token(settings, cid), f"{cid}.{mac}") else None


def unsubscribe_url(settings: Settings, contact_id: int) -> str:
    base = settings.public_base_url.rstrip("/") or "http://localhost:8000"
    return f"{base}/api/email/unsubscribe/{unsubscribe_token(settings, contact_id)}"


def merge_context(settings: Settings, contact: Contact, deal: Deal | None, sender_name: str) -> dict[str, str]:
    stage = deal.stage.name if deal and deal.stage else ""
    extra = (deal.extra or {}) if deal else {}
    return {
        "first_name": contact.first_name or contact.display_name.split(" ")[0] or "there",
        "display_name": contact.display_name,
        "email": contact.email or "",
        "company_name": contact.company.name if contact.company else "",
        "deal_title": deal.title if deal else "",
        "stage_name": stage,
        "next_action_at": deal.next_action_at.isoformat() if deal and deal.next_action_at else "",
        "room_preference": str(extra.get("room_preference") or ""),
        "move_in_target": str(extra.get("move_in_target") or ""),
        "sender_name": sender_name,
        "unsubscribe_url": unsubscribe_url(settings, contact.id),
    }


def render_text(template: str, ctx: dict[str, str]) -> str:
    return _TAG.sub(lambda m: ctx.get(m.group(1), ""), template or "")


def render_html(template_html: str, body_text: str, ctx: dict[str, str]) -> str:
    """Use the HTML body when the template has one, else build simple HTML from the text."""
    if template_html.strip():
        return _TAG.sub(lambda m: html_lib.escape(ctx.get(m.group(1), "")), template_html)
    paras = [html_lib.escape(p).replace("\n", "<br>") for p in render_text(body_text, ctx).split("\n\n")]
    return "".join(f"<p>{p}</p>" for p in paras if p)


def footer_text(settings: Settings, unsub: str) -> str:
    addr = settings.email_postal_address or "(postal address not set)"
    return f"\n\n--\nGladewood Commons, LLC, {addr}\n{EHO_LINE}\nUnsubscribe: {unsub}\n"


def footer_html(settings: Settings, unsub: str) -> str:
    addr = html_lib.escape(settings.email_postal_address or "(postal address not set)")
    return (f'<hr style="border:0;border-top:1px solid #ddd;margin:24px 0"><p style="color:#666;font-size:12px">'
            f"Gladewood Commons, LLC, {addr}<br>{EHO_LINE}<br>"
            f'<a href="{html_lib.escape(unsub)}">Unsubscribe</a></p>')


def compose(settings: Settings, *, subject: str, body_text: str, body_html: str, ctx: dict[str, str]) -> tuple[str, str, str]:
    unsub = ctx["unsubscribe_url"]
    subj = render_text(subject, ctx).replace("\n", " ").strip()
    text = render_text(body_text, ctx).rstrip() + footer_text(settings, unsub)
    html = "<!doctype html><html><body style=\"font-family:system-ui,sans-serif;line-height:1.5;color:#222\">" \
           + render_html(body_html, body_text, ctx) + footer_html(settings, unsub) + "</body></html>"
    return subj, text, html


def skip_reason(db: Session, contact: Contact, *, marketing: bool) -> str | None:
    if not contact.email:
        return "no_email"
    if contact.status != "active":
        return "archived"
    if (contact.extra or {}).get("email_bounced_at"):
        return "bounced"
    withdrawn = db.scalar(select(Consent).where(Consent.contact_id == contact.id, Consent.consent_type == "email",
                                                Consent.withdrawn_at.is_not(None)))
    active = active_consent(db, contact.id, "email")
    if withdrawn is not None and active is None:
        return "unsubscribed"
    if marketing and active is None:
        return "no_consent"
    return None


def send_to_contact(db: Session, settings: Settings, *, contact: Contact, subject: str, body_text: str,
                    body_html: str = "", deal: Deal | None = None, template: EmailTemplate | None = None,
                    sent_by: str | None, sender_name: str = "Paul", marketing: bool, campaign_id: int | None = None,
                    transport=None) -> Email:
    """Render, gate, send, and log. A gated or failed send still returns a row (status skipped or failed)."""
    reason = skip_reason(db, contact, marketing=marketing)
    ctx = merge_context(settings, contact, deal, sender_name)
    subj, text, html = compose(settings, subject=subject, body_text=body_text, body_html=body_html, ctx=ctx)
    row = Email(contact_id=contact.id, deal_id=deal.id if deal else None, campaign_id=campaign_id,
                template_id=template.id if template else None, to_email=contact.email or "", subject=subj,
                body_text=text, provider=settings.email_provider, sent_by=sent_by)
    db.add(row)
    db.flush()
    if reason:
        row.status, row.skip_reason = "skipped", reason
        return row
    headers = {"List-Unsubscribe": f"<{ctx['unsubscribe_url']}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    try:
        row.provider_message_id = send_email(settings, to=contact.email, subject=subj, text=text, html=html,
                                             headers=headers, transport=transport)
        row.status, row.sent_at = "sent", utcnow()
    except EmailSendError as exc:
        row.status, row.error = "failed", str(exc)[:1000]
    write_audit(db, actor=None, action="email.send", entity="contact", entity_id=contact.id,
                details={"email_id": row.id, "status": row.status, "subject": subj[:120], "campaign_id": campaign_id,
                         "sent_by": sent_by})
    return row


def unsubscribe_contact(db: Session, contact_id: int, source: str = "link") -> bool:
    contact = db.get(Contact, contact_id)
    if contact is None:
        return False
    active = active_consent(db, contact_id, "email")
    if active is not None:
        active.withdrawn_at = utcnow()
        active.withdrawn_by = source
    elif db.scalar(select(Consent).where(Consent.contact_id == contact_id, Consent.consent_type == "email")) is None:
        db.add(Consent(contact_id=contact_id, consent_type="email", source="form", given_at=utcnow(),
                       withdrawn_at=utcnow(), withdrawn_by=source))
    write_audit(db, actor=None, action="consent.withdraw", entity="contact", entity_id=contact_id,
                details={"consent_type": "email", "source": source})
    return True


def apply_provider_event(db: Session, event_type: str, provider_message_id: str, at: datetime | None = None) -> Email | None:
    """Update the email row (and the contact for bounces and complaints). Unknown ids are ignored."""
    row = db.scalar(select(Email).where(Email.provider_message_id == provider_message_id))
    if row is None:
        return None
    at = at or datetime.now(timezone.utc)
    kind = event_type.removeprefix("email.")
    if kind == "delivered":
        row.status, row.delivered_at = "delivered", row.delivered_at or at
    elif kind == "opened":
        row.opened_at = row.opened_at or at
    elif kind == "clicked":
        row.clicked_at = row.clicked_at or at
        row.opened_at = row.opened_at or at
    elif kind in ("bounced", "complained"):
        row.status, row.bounced_at = kind, row.bounced_at or at
        if row.contact_id:
            contact = db.get(Contact, row.contact_id)
            if contact is not None:
                contact.extra = {**(contact.extra or {}), "email_bounced_at": at.isoformat()} if kind == "bounced" else contact.extra
                if kind == "complained":
                    unsubscribe_contact(db, contact.id, source="complaint")
    elif kind == "delivery_delayed":
        pass
    return row
