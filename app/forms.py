"""Intake from public web forms: map loose field names, match or create the contact, open the
deal, leave the message as a note, and create the first follow-up task.

Both the direct endpoints and the Netlify webhook call these functions.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.crm_common import automation_owner, set_tags
from app.models import Activity, Company, Consent, Contact, Deal, DealStageHistory, Note, Pipeline
from app.schemas_crm import InquiryFormIn, ReferralFormIn
from app.twilio import normalize_phone

ALIASES = {
    "name": ("name", "full_name", "fullname", "your_name"),
    "email": ("email", "email_address", "e-mail"),
    "phone": ("phone", "tel", "telephone", "mobile", "phone_number"),
    "message": ("message", "notes", "comments", "details", "how_can_we_help"),
    "room_preference": ("room_preference", "room", "room_type", "room_type_preference"),
    "move_in_target": ("move_in_target", "move_in", "move_in_date", "move-in", "move_in_target_date", "timeline"),
    "organization": ("organization", "organisation", "company", "org", "agency", "employer"),
    "organization_type": ("organization_type", "org_type", "partner_type"),
    "role": ("role", "title", "job_title", "position"),
    "contact_ok": ("contact_ok", "consent", "opt_in", "may_contact"),
    "page": ("page", "source_page", "referrer"),
    "website": ("website", "bot-field", "bot_field", "_honey", "honeypot"),
}


def map_fields(raw: dict) -> dict:
    """Lower-case keys, accept the common aliases, join first and last names."""
    low = {str(k).strip().lower().replace(" ", "_"): ("" if v is None else str(v)).strip() for k, v in raw.items()}
    out: dict = {}
    for target, names in ALIASES.items():
        for n in names:
            if n in low and low[n] != "":
                out[target] = low[n]
                break
    if "name" not in out and (low.get("first_name") or low.get("last_name")):
        out["name"] = f"{low.get('first_name', '')} {low.get('last_name', '')}".strip()
    if "contact_ok" in out:
        out["contact_ok"] = out["contact_ok"].lower() in ("1", "true", "yes", "on", "y")
    return out


def initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    return " ".join(p[0].upper() + "." for p in parts[:3]) or "Web inquiry"


def _split_name(name: str) -> tuple[str, str]:
    parts = name.split()
    return (parts[0], " ".join(parts[1:])) if parts else ("", "")


def find_contact(db: Session, email: str, phone: str) -> Contact | None:
    if email:
        c = db.scalar(select(Contact).where(func.lower(Contact.email) == email.lower()))
        if c:
            return c
    tail = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if len(tail) >= 7:
        for c in db.scalars(select(Contact).where(Contact.phone.like(f"%{tail[-4:]}%"))).all():
            if "".join(ch for ch in c.phone if ch.isdigit())[-10:] == tail:
                return c
    return None


def _pipeline(db: Session, slug: str) -> Pipeline | None:
    return db.scalar(select(Pipeline).where(Pipeline.slug == slug))


def _stage(pipeline: Pipeline, name: str | None):
    if name:
        for s in pipeline.stages:
            if s.name == name:
                return s
    return pipeline.stages[0]


def _open_deal(db: Session, pipeline: Pipeline, stage_name: str | None, title: str, contact: Contact,
               company: Company | None, extra: dict) -> Deal | None:
    if db.scalar(select(Deal).where(Deal.contact_id == contact.id, Deal.status == "open")):
        return None
    owner = automation_owner(db)
    if owner is None or not pipeline.stages:
        return None
    stage = _stage(pipeline, stage_name)
    deal = Deal(pipeline_id=pipeline.id, stage_id=stage.id, title=title, contact_id=contact.id,
                company_id=company.id if company else None, owner_id=owner, status="open",
                next_action_at=date.today(), extra=extra)
    db.add(deal)
    db.flush()
    db.add(DealStageHistory(deal_id=deal.id, from_stage_id=None, to_stage_id=stage.id, actor_id=None))
    write_audit(db, actor=None, action="deal.create", entity="deal", entity_id=deal.id, details={"title": title, "source": "web"})
    return deal


def _task(db: Session, deal: Deal, subject: str, hours: int, priority: str = "normal") -> Activity:
    a = Activity(kind="task", subject=subject, due_at=datetime.now(timezone.utc) + timedelta(hours=hours),
                 priority=priority, contact_id=deal.contact_id, company_id=deal.company_id, deal_id=deal.id,
                 assigned_to=deal.owner_id)
    db.add(a)
    db.flush()
    return a


def intake_inquiry(db: Session, f: InquiryFormIn) -> tuple[Contact, Deal | None, bool]:
    phone = normalize_phone(f.phone) if f.phone else ""
    contact = find_contact(db, f.email, phone)
    created = contact is None
    first, last = _split_name(f.name)
    if contact is None:
        contact = Contact(display_name=initials(f.name), first_name=first, last_name=last, email=f.email, phone=phone,
                          kind="prospect", source="web", extra={"page": f.page[:200]})
        db.add(contact)
        db.flush()
        write_audit(db, actor=None, action="contact.create", entity="contact", entity_id=contact.id, details={"source": "web"})
    else:
        if not contact.email and f.email:
            contact.email = f.email
        if not contact.phone and phone:
            contact.phone = phone
    set_tags(db, "contact", contact.id, sorted(set(_current_tags(db, contact.id)) | {"src-web"}))
    if f.contact_ok and f.email:
        db.add(Consent(contact_id=contact.id, consent_type="email", source="form", recorded_by=None))
    if f.message:
        db.add(Note(entity="contact", entity_id=contact.id, body=f"Web form: {f.message}", author_id=None, author_email="web form"))
    pipeline = _pipeline(db, "resident-inquiry")
    deal = None
    if pipeline:
        deal = _open_deal(db, pipeline, "Inquiry", f"Inquiry: {contact.display_name}", contact, None,
                          {"source": "web", "room_preference": f.room_preference[:40], "move_in_target": f.move_in_target[:40]})
        if deal:
            _task(db, deal, "Call back new web inquiry", 24)
    write_audit(db, actor=None, action="form.inquiry", entity="contact", entity_id=contact.id,
                details={"new_contact": created, "deal_id": deal.id if deal else None})
    return contact, deal, created


def intake_referral(db: Session, f: ReferralFormIn) -> tuple[Contact, Deal | None, bool]:
    phone = normalize_phone(f.phone) if f.phone else ""
    company = db.scalar(select(Company).where(func.lower(Company.name) == f.organization.strip().lower()))
    if company is None:
        kind = f.organization_type if f.organization_type in ("property_owner", "brokerage", "agency", "hospital", "employer", "vendor", "other") else "agency"
        company = Company(name=f.organization.strip(), kind=kind, email="", phone="", extra={"source": "web"})
        db.add(company)
        db.flush()
        write_audit(db, actor=None, action="company.create", entity="company", entity_id=company.id, details={"source": "web"})
    contact = find_contact(db, f.email, phone)
    created = contact is None
    first, last = _split_name(f.name)
    if contact is None:
        contact = Contact(display_name=f.name.strip(), first_name=first, last_name=last, email=f.email, phone=phone,
                          kind="case_manager", source="web", company_id=company.id, extra={"role": f.role[:120], "page": f.page[:200]})
        db.add(contact)
        db.flush()
        write_audit(db, actor=None, action="contact.create", entity="contact", entity_id=contact.id, details={"source": "web"})
    elif contact.company_id is None:
        contact.company_id = company.id
    set_tags(db, "contact", contact.id, sorted(set(_current_tags(db, contact.id)) | {"src-web", "referral"}))
    if f.message:
        db.add(Note(entity="contact", entity_id=contact.id, body=f"Web form: {f.message}", author_id=None, author_email="web form"))
    pipeline = _pipeline(db, "referral-partner")
    deal = None
    if pipeline:
        deal = _open_deal(db, pipeline, "Contacted", f"Partner: {company.name}", contact, company, {"source": "web", "role": f.role[:120]})
        if deal:
            _task(db, deal, "Send partner fact sheet", 24)
    write_audit(db, actor=None, action="form.referral", entity="contact", entity_id=contact.id,
                details={"new_contact": created, "company_id": company.id, "deal_id": deal.id if deal else None})
    return contact, deal, created


def _current_tags(db: Session, contact_id: int) -> list[str]:
    from app.crm_common import tags_for
    return tags_for(db, "contact", [contact_id]).get(contact_id, [])
