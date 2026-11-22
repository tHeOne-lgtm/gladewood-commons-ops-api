"""Outbound queue with an admin's approval and four dispatch gates (Atlas gap 2, built 2026-11-22).

A row is created as a draft by staff, or by an agent through the integration key. It never moves
until an admin approves it (the Staged Path rule: Paul approves every send). The 15-minute cron then
runs the gates, in this order, on every approved row whose time has come:

  1. lint          the deterministic scan runs again on the text as it is now; a failure holds the row
  2. kill switch   OUTBOX_PAUSED or the admin flag `outbox_paused`: nothing moves, rows stay approved
  3. schedule      send_after has to have passed; SMS and WhatsApp also wait for the local texting hours
  4. shadow        OUTBOX_SHADOW or the admin flag `outbox_shadow`: the row is marked shadowed, nothing leaves

Then the consent and address checks, and the send: email through app.emailing (footer, unsubscribe
link, consent gate, an `emails` row), SMS and WhatsApp through Twilio (a `messages` row with the
status callback for the delivery receipt). The queue row links to that row, so its delivery status is
the provider's. Audit rows carry ids, channel, status and reason, never the text.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.config import Settings
from app.consents import active_consent
from app.emailing import send_to_contact, skip_reason
from app.models import Consent, Contact, Deal, Email, Message, OutboxItem, SystemFlag, User, utcnow
from app.outbox_lint import TEXT_CHANNELS, LintResult, lint_text
from app.twilio import normalize_phone, send_sms, send_whatsapp

CHANNELS = ("email", "sms", "whatsapp")
OPEN_STATUSES = ("draft", "approved", "held")
FLAG_PAUSED = "outbox_paused"
FLAG_SHADOW = "outbox_shadow"
DISPATCH_BATCH = 50


class OutboxError(ValueError):
    """A state or validation problem the router answers with 409 or 422."""
    def __init__(self, status_code: int, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


# ---------- flags ----------

def flag(db: Session, key: str) -> str:
    row = db.get(SystemFlag, key)
    return (row.value if row else "") or ""


def set_flag(db: Session, key: str, value: str, actor: User | None) -> SystemFlag:
    row = db.get(SystemFlag, key)
    if row is None:
        row = SystemFlag(key=key)
        db.add(row)
    row.value, row.updated_by = value, actor.id if actor else None
    write_audit(db, actor=actor, action="flag.set", entity="system_flag", entity_id=key, details={"value": value})
    return row


def is_paused(db: Session, settings: Settings) -> bool:
    return bool(settings.outbox_paused) or flag(db, FLAG_PAUSED) == "true"


def is_shadow(db: Session, settings: Settings) -> bool:
    return bool(settings.outbox_shadow) or flag(db, FLAG_SHADOW) == "true"


def text_hours_open(settings: Settings, now: datetime | None = None) -> bool:
    """SMS and WhatsApp go out only inside the local window (default 8 AM to 9 PM in Chattanooga's zone)."""
    now = now or datetime.now(timezone.utc)
    try:
        start_s, end_s = settings.outbox_text_hours.split("-", 1)
        start, end = int(start_s), int(end_s)
        local = now.astimezone(ZoneInfo(settings.outbox_timezone))
    except (ValueError, KeyError):
        return False
    return start <= local.hour < end


# ---------- rows ----------

def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _log(row: OutboxItem, gate: str, result: str, detail: str = "", at: datetime | None = None) -> None:
    entry = {"at": (at or utcnow()).isoformat(), "gate": gate, "result": result}
    if detail:
        entry["detail"] = detail[:200]
    row.gate_log = [*(row.gate_log or []), entry][-40:]


def run_lint(settings: Settings, row: OutboxItem) -> LintResult:
    r = lint_text(row.channel, row.subject, row.body, settings.outbox_allowed_prices)
    row.lint = r.as_dict()
    return r


def thread_key_for(channel: str, contact: Contact, in_reply_to_email_id: int | None) -> str:
    if channel in TEXT_CHANNELS:
        return normalize_phone(contact.phone) or f"contact:{contact.id}"
    if in_reply_to_email_id:
        return f"email:{in_reply_to_email_id}"
    return f"contact:{contact.id}"


def create_item(db: Session, settings: Settings, *, channel: str, contact: Contact, deal: Deal | None, subject: str,
                body: str, marketing: bool, send_after: datetime | None, allow_outside_window: bool,
                in_reply_to_email_id: int | None, created_by: str, actor: User | None) -> OutboxItem:
    if channel not in CHANNELS:
        raise OutboxError(422, "channel must be email, sms or whatsapp")
    if in_reply_to_email_id is not None:
        prior = db.get(Email, in_reply_to_email_id)
        if prior is None:
            raise OutboxError(422, f"Email {in_reply_to_email_id} does not exist")
        if prior.contact_id != contact.id:
            raise OutboxError(422, "in_reply_to_email_id belongs to another contact")
    row = OutboxItem(channel=channel, contact_id=contact.id, deal_id=deal.id if deal else None, subject=subject or "",
                     body=body, marketing=marketing, send_after=send_after, allow_outside_window=allow_outside_window,
                     in_reply_to_email_id=in_reply_to_email_id, thread_key=thread_key_for(channel, contact, in_reply_to_email_id),
                     status="draft", created_by=created_by, gate_log=[])
    lr = run_lint(settings, row)
    db.add(row)
    db.flush()
    _log(row, "lint", "pass" if lr.ok else "fail", "; ".join(lr.failures))
    write_audit(db, actor=actor, action="outbox.create", entity="outbox", entity_id=row.id,
                details={"channel": channel, "contact_id": contact.id, "deal_id": row.deal_id, "created_by": created_by,
                         "lint_ok": lr.ok, "words": lr.words})
    return row


def update_item(db: Session, settings: Settings, row: OutboxItem, actor: User, **changes) -> OutboxItem:
    """Edit the text or timing of a draft or held row. The row goes back to draft and needs approval again."""
    if row.status not in ("draft", "held"):
        raise OutboxError(409, f"Row is {row.status}; only a draft or held row can be edited")
    for k, v in changes.items():
        if v is not None:
            setattr(row, k, v)
    row.status, row.hold_reason, row.approved_by, row.approved_at = "draft", None, None, None
    lr = run_lint(settings, row)
    _log(row, "lint", "pass" if lr.ok else "fail", "; ".join(lr.failures))
    write_audit(db, actor=actor, action="outbox.update", entity="outbox", entity_id=row.id,
                details={"fields": sorted(k for k, v in changes.items() if v is not None), "lint_ok": lr.ok})
    return row


def preflight(db: Session, row: OutboxItem, now: datetime | None = None) -> str | None:
    """The consent and address checks, as a hold reason or None. Run at approval (early feedback) and again
    at dispatch (the facts may have changed in between)."""
    contact = db.get(Contact, row.contact_id)
    if contact is None:
        return "no_contact"
    if contact.status != "active":
        return "archived"
    if row.channel == "email":
        return skip_reason(db, contact, marketing=row.marketing)
    phone = normalize_phone(contact.phone)
    if not phone:
        return "no_phone"
    consent = active_consent(db, contact.id, row.channel)
    if consent is None and db.scalar(select(Consent).where(Consent.contact_id == contact.id,
                                                            Consent.consent_type == row.channel)) is not None:
        return "stopped"
    if row.marketing and consent is None:
        return "no_consent"
    if row.channel == "whatsapp" and not row.allow_outside_window and not _window_open(db, phone, now):
        return "window_closed"
    return None


def _window_open(db: Session, phone: str, now: datetime | None = None) -> bool:
    from app.routers.crm.messages import WINDOW
    now = now or datetime.now(timezone.utc)
    last_in = db.scalar(select(Message.created_at).where(Message.phone == phone, Message.direction == "in")
                        .order_by(Message.created_at.desc()))
    last_in = _aware(last_in)
    return last_in is not None and now - last_in < WINDOW


def approve_item(db: Session, settings: Settings, row: OutboxItem, actor: User) -> OutboxItem:
    if row.status not in ("draft", "held"):
        raise OutboxError(409, f"Row is {row.status}")
    lr = run_lint(settings, row)
    if not lr.ok:
        raise OutboxError(422, {"lint": lr.failures})
    reason = preflight(db, row)
    if reason:
        raise OutboxError(409, {"hold_reason": reason})
    if row.channel == "sms" and not settings.twilio_sms_from:
        raise OutboxError(503, "TWILIO_SMS_FROM is not set; SMS cannot be sent from the queue yet")
    row.status, row.hold_reason, row.approved_by, row.approved_at = "approved", None, actor.id, utcnow()
    _log(row, "approval", "approved", actor.id)
    write_audit(db, actor=actor, action="outbox.approve", entity="outbox", entity_id=row.id,
                details={"channel": row.channel, "contact_id": row.contact_id, "send_after": row.send_after.isoformat() if row.send_after else None})
    return row


def cancel_item(db: Session, row: OutboxItem, actor: User) -> OutboxItem:
    if row.status not in OPEN_STATUSES:
        raise OutboxError(409, f"Row is {row.status}")
    row.status, row.hold_reason = "cancelled", None
    _log(row, "cancel", "cancelled", actor.id)
    write_audit(db, actor=actor, action="outbox.cancel", entity="outbox", entity_id=row.id, details={"channel": row.channel})
    return row


def delivery_status(db: Session, row: OutboxItem) -> str | None:
    if row.email_id:
        e = db.get(Email, row.email_id)
        return e.status if e else None
    if row.message_id:
        m = db.get(Message, row.message_id)
        return m.status if m else None
    return None


# ---------- dispatch ----------

def _hold(db: Session, row: OutboxItem, reason: str, detail: str, now: datetime) -> None:
    row.status, row.hold_reason = "held", reason
    _log(row, "preflight" if reason != "lint" else "lint", "held", detail or reason, now)
    write_audit(db, actor=None, action="outbox.hold", entity="outbox", entity_id=row.id,
                details={"channel": row.channel, "reason": reason})


def reply_headers(db: Session, row: OutboxItem) -> dict[str, str]:
    """In-Reply-To and References when the prior email went out over SMTP (its stored id is a real
    Message-ID). Resend's ids are not message ids, so a Resend reply gets no threading header."""
    if not row.in_reply_to_email_id:
        return {}
    prior = db.get(Email, row.in_reply_to_email_id)
    if prior is None or prior.provider != "smtp" or not prior.provider_message_id:
        return {}
    mid = f"<{prior.provider_message_id}>"
    return {"In-Reply-To": mid, "References": mid}


def dispatch(db: Session, settings: Settings, *, now: datetime | None = None, email_transport=None,
             twilio_transport=None, limit: int = DISPATCH_BATCH) -> dict:
    now = now or datetime.now(timezone.utc)
    report = {"ran_at": now.isoformat(), "paused": False, "shadow": is_shadow(db, settings), "examined": 0,
              "sent": 0, "shadowed": 0, "held": 0, "failed": 0, "deferred": 0}
    due = db.scalars(select(OutboxItem).where(OutboxItem.status == "approved",
                                              (OutboxItem.send_after.is_(None)) | (OutboxItem.send_after <= now))
                     .order_by(OutboxItem.id).limit(limit)).all()
    if is_paused(db, settings):
        report["paused"] = True
        if due:
            write_audit(db, actor=None, action="outbox.paused", entity="outbox", entity_id=None, details={"due": len(due)})
            db.commit()
        return report
    hours_open = text_hours_open(settings, now)
    callback = (settings.public_base_url.rstrip("/") + "/api/webhooks/twilio/status") if settings.public_base_url else None
    for row in due:
        report["examined"] += 1
        lr = run_lint(settings, row)
        if not lr.ok:
            _hold(db, row, "lint", "; ".join(lr.failures), now)
            report["held"] += 1
            db.commit()
            continue
        if row.channel in TEXT_CHANNELS and not hours_open:
            report["deferred"] += 1
            continue
        reason = preflight(db, row, now)
        if reason:
            _hold(db, row, reason, "", now)
            report["held"] += 1
            db.commit()
            continue
        contact = db.get(Contact, row.contact_id)
        row.to_address = contact.email if row.channel == "email" else normalize_phone(contact.phone)
        if report["shadow"]:
            row.status, row.dispatched_at = "shadowed", now
            _log(row, "shadow", "shadowed", f"{row.channel} to ***{row.to_address[-4:]}", now)
            write_audit(db, actor=None, action="outbox.shadow", entity="outbox", entity_id=row.id,
                        details={"channel": row.channel, "contact_id": row.contact_id, "words": lr.words})
            report["shadowed"] += 1
            db.commit()
            continue
        _send(db, settings, row, contact, now, callback, email_transport, twilio_transport)
        report["sent" if row.status == "sent" else "failed"] += 1
        db.commit()
    return report


def _send(db: Session, settings: Settings, row: OutboxItem, contact: Contact, now: datetime, callback: str | None,
          email_transport, twilio_transport) -> None:
    row.dispatched_at = now
    if row.channel == "email":
        deal = db.get(Deal, row.deal_id) if row.deal_id else None
        email = send_to_contact(db, settings, contact=contact, subject=row.subject, body_text=row.body, deal=deal,
                                sent_by=row.approved_by, marketing=row.marketing, transport=email_transport,
                                extra_headers=reply_headers(db, row))
        row.email_id = email.id
        if email.status == "sent":
            row.status = "sent"
        elif email.status == "skipped":
            row.status, row.hold_reason = "held", email.skip_reason
        else:
            row.status, row.error = "failed", email.error
        _log(row, "send", row.status, row.error or row.hold_reason or f"email {email.id}", now)
    else:
        sender = send_whatsapp if row.channel == "whatsapp" else send_sms
        try:
            result = sender(settings, row.to_address, row.body, callback, transport=twilio_transport)
        except RuntimeError as exc:
            row.status, row.error = "failed", str(exc)[:1000]
            _log(row, "send", "failed", row.error, now)
        else:
            msg = Message(channel=row.channel, direction="out", contact_id=contact.id, deal_id=row.deal_id, phone=row.to_address,
                          body=row.body, provider_sid=result.get("sid"), status=(result.get("status") or "queued").lower(),
                          sent_by=row.approved_by)
            db.add(msg)
            db.flush()
            row.message_id, row.status = msg.id, "sent"
            write_audit(db, actor=None, action="message.out", entity="contact", entity_id=contact.id,
                        details={"message_id": msg.id, "phone_last4": row.to_address[-4:], "channel": row.channel, "outbox_id": row.id})
            _log(row, "send", "sent", f"message {msg.id}", now)
    write_audit(db, actor=None, action=f"outbox.{row.status}", entity="outbox", entity_id=row.id,
                details={"channel": row.channel, "contact_id": row.contact_id, "email_id": row.email_id,
                         "message_id": row.message_id, "approved_by": row.approved_by})
