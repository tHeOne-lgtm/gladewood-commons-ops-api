"""WhatsApp conversations: Twilio webhooks (inbound and status), conversation list, thread, send.

Inbound flow: validate the Twilio signature; find or create the contact by phone; record or
withdraw WhatsApp consent (STOP words withdraw); store the message; open a Resident inquiry
deal if the contact has no open deal. Staff never see the auth token; it lives in Render.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.config import Settings, settings_dep
from app.crm_common import set_tags
from app.db import get_db
from app.models import Consent, Contact, Deal, DealStageHistory, Message, Pipeline, User, utcnow
from app.schemas_crm import ConversationOut, MessageOut, SendMessageIn
from app.twilio import STOP_WORDS, normalize_phone, send_whatsapp, signature_valid

router = APIRouter(tags=["crm: messages"])
WINDOW = timedelta(hours=24)


# ---------- helpers ----------

def _last10(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())[-10:]


def find_contact_by_phone(db: Session, phone: str) -> Contact | None:
    tail = _last10(phone)
    if len(tail) < 7:
        return None
    candidates = db.scalars(select(Contact).where(Contact.phone.like(f"%{tail[-4:]}%"))).all()
    for c in candidates:
        if _last10(c.phone) == tail:
            return c
    return None


def active_consent(db: Session, contact_id: int, consent_type: str = "whatsapp") -> Consent | None:
    return db.scalar(select(Consent).where(Consent.contact_id == contact_id, Consent.consent_type == consent_type,
                                           Consent.withdrawn_at.is_(None)).order_by(Consent.id.desc()))


def _automation_owner(db: Session) -> str | None:
    u = db.scalar(select(User).where(User.role == "admin").order_by(User.created_at)) or \
        db.scalar(select(User).where(User.role == "staff").order_by(User.created_at))
    return u.id if u else None


def _open_inquiry_if_needed(db: Session, contact: Contact) -> Deal | None:
    if db.scalar(select(Deal).where(Deal.contact_id == contact.id, Deal.status == "open")):
        return None
    pipeline = db.scalar(select(Pipeline).where(Pipeline.slug == "resident-inquiry"))
    owner = _automation_owner(db)
    if pipeline is None or not pipeline.stages or owner is None:
        return None
    stage = pipeline.stages[0]
    deal = Deal(pipeline_id=pipeline.id, stage_id=stage.id, title=f"WhatsApp inquiry: {contact.display_name}",
                contact_id=contact.id, owner_id=owner, status="open", next_action_at=datetime.now(timezone.utc).date(),
                extra={"source": "whatsapp"})
    db.add(deal)
    db.flush()
    db.add(DealStageHistory(deal_id=deal.id, from_stage_id=None, to_stage_id=stage.id, actor_id=None))
    write_audit(db, actor=None, action="deal.create", entity="deal", entity_id=deal.id,
                details={"title": deal.title, "source": "whatsapp"})
    return deal


def _window_open(db: Session, phone: str) -> bool:
    last_in = db.scalar(select(func.max(Message.created_at)).where(Message.phone == phone, Message.direction == "in"))
    if last_in is None:
        return False
    if last_in.tzinfo is None:
        last_in = last_in.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_in < WINDOW


async def _form(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: str(v) for k, v in form.items()}


def _check_signature(request: Request, settings: Settings, params: dict[str, str]) -> None:
    if not settings.twilio_validate_signature:
        return
    base = settings.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not signature_valid(settings.twilio_auth_token, url, params, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


# ---------- webhooks (no bearer auth; Twilio signature instead) ----------

@router.post("/api/webhooks/twilio/whatsapp", include_in_schema=False)
async def twilio_inbound(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    params = await _form(request)
    _check_signature(request, settings, params)
    sid = params.get("MessageSid") or params.get("SmsSid") or ""
    phone = normalize_phone(params.get("From", ""))
    body = (params.get("Body") or "").strip()
    if not phone:
        raise HTTPException(status_code=422, detail="From is required")
    if sid and db.scalar(select(Message).where(Message.provider_sid == sid)):
        return Response(content="<Response/>", media_type="application/xml")  # Twilio retry; already stored

    contact = find_contact_by_phone(db, phone)
    created = False
    if contact is None:
        contact = Contact(display_name=f"WhatsApp {phone[-4:]}", phone=phone, kind="prospect", source="whatsapp",
                          extra={"whatsapp_profile": (params.get("ProfileName") or "")[:80]})
        db.add(contact)
        db.flush()
        set_tags(db, "contact", contact.id, ["src-whatsapp"])
        write_audit(db, actor=None, action="contact.create", entity="contact", entity_id=contact.id,
                    details={"source": "whatsapp"})
        created = True

    stop = body.lower().strip(" .!") in STOP_WORDS
    consent = active_consent(db, contact.id)
    if stop:
        if consent:
            consent.withdrawn_at = utcnow()
            consent.withdrawn_by = "contact"
            write_audit(db, actor=None, action="consent.withdraw", entity="contact", entity_id=contact.id,
                        details={"consent_type": "whatsapp", "source": "stop_keyword"})
    elif consent is None:
        db.add(Consent(contact_id=contact.id, consent_type="whatsapp", source="whatsapp", recorded_by=None))
        write_audit(db, actor=None, action="consent.record", entity="contact", entity_id=contact.id,
                    details={"consent_type": "whatsapp", "source": "inbound_message"})

    msg = Message(channel="whatsapp", direction="in", contact_id=contact.id, phone=phone, body=body,
                  provider_sid=sid or None, status="received", media_count=int(params.get("NumMedia") or 0))
    db.add(msg)
    db.flush()
    deal = None if stop else _open_inquiry_if_needed(db, contact)
    if deal is not None:
        msg.deal_id = deal.id
    write_audit(db, actor=None, action="message.in", entity="contact", entity_id=contact.id,
                details={"message_id": msg.id, "new_contact": created, "stop": stop, "deal_id": deal.id if deal else None})
    db.commit()
    return Response(content="<Response/>", media_type="application/xml")


@router.post("/api/webhooks/twilio/status", include_in_schema=False)
async def twilio_status(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    params = await _form(request)
    _check_signature(request, settings, params)
    sid = params.get("MessageSid") or params.get("SmsSid") or ""
    msg = db.scalar(select(Message).where(Message.provider_sid == sid)) if sid else None
    if msg is None:
        return Response(status_code=204)
    msg.status = (params.get("MessageStatus") or msg.status).lower()
    msg.error_code = params.get("ErrorCode") or None
    db.commit()
    return Response(status_code=204)


# ---------- staff endpoints ----------

def _conversation(db: Session, phone: str, last: Message, unread: int) -> ConversationOut:
    contact = db.get(Contact, last.contact_id) if last.contact_id else None
    return ConversationOut(
        phone=phone, contact_id=contact.id if contact else None, contact_name=contact.display_name if contact else None,
        consent_active=bool(contact and active_consent(db, contact.id)), window_open=_window_open(db, phone),
        unread_count=unread, last_message=MessageOut.model_validate(last),
    )


@router.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                       _: User = Depends(require_staff)):
    latest = db.execute(select(Message.phone, func.max(Message.id)).group_by(Message.phone)).all()
    if not latest:
        return []
    ids = [r[1] for r in latest]
    last_by_phone = {m.phone: m for m in db.scalars(select(Message).where(Message.id.in_(ids))).all()}
    unread = dict(db.execute(select(Message.phone, func.count(Message.id))
                             .where(Message.direction == "in", Message.read_at.is_(None)).group_by(Message.phone)).all())
    out = [_conversation(db, phone, m, unread.get(phone, 0)) for phone, m in last_by_phone.items()]
    out.sort(key=lambda c: c.last_message.created_at, reverse=True)
    return out[:limit]


@router.get("/api/conversations/{phone}/messages", response_model=list[MessageOut])
def thread(phone: str, limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db),
           _: User = Depends(require_staff)):
    phone = normalize_phone(phone)
    rows = db.scalars(select(Message).where(Message.phone == phone).order_by(Message.id.desc()).limit(limit)).all()
    return list(reversed(rows))


@router.post("/api/conversations/{phone}/read", response_model=dict)
def mark_read(phone: str, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    phone = normalize_phone(phone)
    rows = db.scalars(select(Message).where(Message.phone == phone, Message.direction == "in",
                                            Message.read_at.is_(None))).all()
    for m in rows:
        m.read_at = utcnow()
    db.commit()
    return {"marked": len(rows)}


@router.post("/api/messages/whatsapp", response_model=MessageOut, status_code=201)
def send_message(item: SendMessageIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_staff), settings: Settings = Depends(settings_dep)):
    contact = db.get(Contact, item.contact_id) if item.contact_id else None
    if item.contact_id and contact is None:
        raise HTTPException(status_code=422, detail="Contact does not exist")
    phone = normalize_phone(item.phone or (contact.phone if contact else ""))
    if not phone:
        raise HTTPException(status_code=422, detail="A phone number is required")
    if contact is None:
        contact = find_contact_by_phone(db, phone)
    if contact is not None:
        consent = active_consent(db, contact.id)
        if consent is None and db.scalar(select(Consent).where(Consent.contact_id == contact.id,
                                                                Consent.consent_type == "whatsapp")):
            raise HTTPException(status_code=409, detail="This contact withdrew WhatsApp consent (STOP). Do not message them.")
    if not _window_open(db, phone) and not item.allow_outside_window:
        raise HTTPException(status_code=409, detail="No inbound message in the last 24 hours; WhatsApp requires an approved template outside that window. Set allow_outside_window to send anyway.")
    callback = (settings.public_base_url.rstrip("/") + "/api/webhooks/twilio/status") if settings.public_base_url else None
    try:
        result = send_whatsapp(settings, phone, item.body, callback, transport=getattr(request.app.state, "twilio_transport", None))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    msg = Message(channel="whatsapp", direction="out", contact_id=contact.id if contact else None, phone=phone,
                  body=item.body, provider_sid=result.get("sid"), status=(result.get("status") or "queued").lower(),
                  sent_by=user.id)
    db.add(msg)
    db.flush()
    write_audit(db, actor=user, action="message.out", entity="contact", entity_id=contact.id if contact else None,
                details={"message_id": msg.id, "phone_last4": phone[-4:]})
    db.commit()
    db.refresh(msg)
    return msg
