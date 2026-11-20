"""Email templates, preview, 1:1 send, send log, unsubscribe (public), and the Resend webhook."""
import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.config import Settings, settings_dep
from app.crm_common import get_or_404
from app.db import get_db
from app.emailing import (apply_provider_event, compose, lint, merge_context, parse_unsubscribe_token, send_to_contact,
                          skip_reason, unknown_fields, unsubscribe_contact)
from app.models import Contact, Deal, Email, EmailTemplate, User
from app.schemas_crm import EmailOut, EmailPreviewIn, EmailPreviewOut, EmailTemplateIn, EmailTemplateOut, SendEmailIn

router = APIRouter(prefix="/api/email", tags=["crm: email"])
webhooks = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _check_text(subject: str, body_text: str, body_html: str = "") -> None:
    bad = unknown_fields(subject, body_text, body_html)
    if bad:
        raise HTTPException(status_code=422, detail=f"Unknown merge fields: {', '.join(bad)}")
    hits = lint(subject, body_text + "\n" + body_html)
    if hits:
        raise HTTPException(status_code=422, detail=f"Protected-trait terms are not allowed in email: {', '.join(hits)}")


# ---- templates ----
@router.get("/templates", response_model=list[EmailTemplateOut])
def list_templates(include_inactive: bool = False, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(EmailTemplate)
    if not include_inactive:
        q = q.where(EmailTemplate.is_active.is_(True))
    return db.scalars(q.order_by(EmailTemplate.kind, EmailTemplate.name)).all()


@router.post("/templates", response_model=EmailTemplateOut, status_code=201)
def create_template(item: EmailTemplateIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    _check_text(item.subject, item.body_text, item.body_html)
    if db.scalar(select(EmailTemplate).where(EmailTemplate.name == item.name)):
        raise HTTPException(status_code=409, detail="A template with that name exists")
    row = EmailTemplate(**item.model_dump(), created_by=user.id)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="email_template.create", entity="email_template", entity_id=row.id, details={"name": row.name})
    db.commit()
    return row


@router.get("/templates/{template_id}", response_model=EmailTemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return get_or_404(db, EmailTemplate, template_id, "Template")


@router.put("/templates/{template_id}", response_model=EmailTemplateOut)
def update_template(template_id: int, item: EmailTemplateIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, EmailTemplate, template_id, "Template")
    _check_text(item.subject, item.body_text, item.body_html)
    dup = db.scalar(select(EmailTemplate).where(EmailTemplate.name == item.name, EmailTemplate.id != template_id))
    if dup:
        raise HTTPException(status_code=409, detail="A template with that name exists")
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    write_audit(db, actor=user, action="email_template.update", entity="email_template", entity_id=row.id, details={"name": row.name})
    db.commit()
    return row


# ---- preview and send ----
def _subject_body(db: Session, template_id: int | None, subject: str | None, body_text: str | None):
    if template_id is not None:
        t = get_or_404(db, EmailTemplate, template_id, "Template")
        return t, t.subject, t.body_text, t.body_html
    if not subject or not body_text:
        raise HTTPException(status_code=422, detail="Give a template_id or both subject and body_text")
    _check_text(subject, body_text)
    return None, subject, body_text, ""


@router.post("/preview", response_model=EmailPreviewOut)
def preview(item: EmailPreviewIn, db: Session = Depends(get_db), user: User = Depends(require_staff),
            settings: Settings = Depends(settings_dep)):
    _, subject, body_text, body_html = _subject_body(db, item.template_id, item.subject, item.body_text)
    deal = get_or_404(db, Deal, item.deal_id, "Deal") if item.deal_id else None
    contact = get_or_404(db, Contact, item.contact_id, "Contact") if item.contact_id else (deal.contact if deal else None)
    if contact is None:
        sample = Contact(id=0, display_name="Resident A", first_name="Resident", email="resident.a@example.test")
        subj, text, html = compose(settings, subject=subject, body_text=body_text, body_html=body_html,
                                   ctx=merge_context(settings, sample, deal, "Paul"))
        return EmailPreviewOut(to_email=sample.email, subject=subj, body_text=text, body_html=html, can_send=False,
                               skip_reason="no_contact", protected_terms=lint(subject, body_text))
    subj, text, html = compose(settings, subject=subject, body_text=body_text, body_html=body_html,
                               ctx=merge_context(settings, contact, deal, "Paul"))
    reason = skip_reason(db, contact, marketing=False)
    return EmailPreviewOut(to_email=contact.email or "", subject=subj, body_text=text, body_html=html,
                           can_send=reason is None, skip_reason=reason, protected_terms=lint(subject, body_text))


@router.post("/send", response_model=EmailOut, status_code=201)
def send(item: SendEmailIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_staff),
         settings: Settings = Depends(settings_dep)):
    template, subject, body_text, body_html = _subject_body(db, item.template_id, item.subject, item.body_text)
    contact = get_or_404(db, Contact, item.contact_id, "Contact")
    deal = get_or_404(db, Deal, item.deal_id, "Deal") if item.deal_id else None
    reason = skip_reason(db, contact, marketing=item.marketing)
    if reason:
        raise HTTPException(status_code=409, detail={"skip_reason": reason})
    row = send_to_contact(db, settings, contact=contact, subject=subject, body_text=body_text, body_html=body_html,
                          deal=deal, template=template, sent_by=user.id, marketing=item.marketing,
                          transport=getattr(request.app.state, "email_transport", None))
    db.commit()
    if row.status == "failed":
        raise HTTPException(status_code=502, detail=f"Send failed: {row.error}")
    return row


@router.get("/log", response_model=list[EmailOut])
def log(contact_id: int | None = None, deal_id: int | None = None, campaign_id: int | None = None,
        limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(Email)
    if contact_id is not None:
        q = q.where(Email.contact_id == contact_id)
    if deal_id is not None:
        q = q.where(Email.deal_id == deal_id)
    if campaign_id is not None:
        q = q.where(Email.campaign_id == campaign_id)
    return db.scalars(q.order_by(Email.id.desc()).limit(limit)).all()


# ---- public unsubscribe (GET shows a page, POST is RFC 8058 one-click) ----
_PAGE = ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
         "<title>Gladewood Commons</title></head><body style='font-family:system-ui,sans-serif;max-width:520px;margin:48px auto;padding:0 16px'>"
         "<h2>{title}</h2><p>{body}</p></body></html>")


@router.api_route("/unsubscribe/{token}", methods=["GET", "POST"], response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(token: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    cid = parse_unsubscribe_token(settings, token)
    if cid is None or not unsubscribe_contact(db, cid, source="link"):
        return HTMLResponse(_PAGE.format(title="Link not recognized", body="This unsubscribe link is not valid. Reply to any email from us and we will remove you by hand."), status_code=404)
    db.commit()
    return HTMLResponse(_PAGE.format(title="You are unsubscribed", body="You will not receive further marketing email from Gladewood Commons. Messages about a tour, application, or lease you asked for may still arrive."))


# ---- Resend webhook (Svix signature) ----
def _svix_valid(secret: str, msg_id: str, ts: str, sig_header: str, body: bytes, tolerance: int = 300) -> bool:
    if not (secret and msg_id and ts and sig_header):
        return False
    try:
        if abs(time.time() - int(ts)) > tolerance:
            return False
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except (ValueError, TypeError):
        return False
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    for part in sig_header.split(" "):
        if "," in part:
            version, sig = part.split(",", 1)
            if version == "v1" and hmac.compare_digest(sig, expected):
                return True
    return False


@webhooks.post("/resend", status_code=204, include_in_schema=False)
async def resend_webhook(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    if not settings.resend_webhook_secret:
        raise HTTPException(status_code=503, detail="RESEND_WEBHOOK_SECRET is not set")
    body = await request.body()
    h = request.headers
    if not _svix_valid(settings.resend_webhook_secret, h.get("svix-id", ""), h.get("svix-timestamp", ""),
                       h.get("svix-signature", ""), body):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    try:
        event = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Body is not JSON") from exc
    data = event.get("data") or {}
    apply_provider_event(db, str(event.get("type") or ""), str(data.get("email_id") or ""))
    db.commit()
    return None
