"""Machine-credential routes for the Command Center sync (plan Section 9, item 3 cutover).

The Command Center page pushes engaged referral partners as a Bigin-shaped upsert body and
reads the partner list back in Bigin's Accounts shape. These two routes speak that shape, so
the page and the Make scenario (and the n8n workflow after it) only change their URL and auth.

Auth: header `X-Api-Key` equal to INTEGRATION_API_KEY. Constant-time compare. The key opens
nothing outside this router.
"""
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.bigin_import import guess_company_kind
from app.config import Settings, settings_dep
from app.crm_common import get_or_404
from app.db import get_db
from app.fair_housing import protected_term_hits
from app.models import Activity, Company, Contact, Deal, DealStageHistory, Document, Message, Note, Pipeline
from app.outbox import OutboxError, create_item
from app.schemas_outbox import AgentOutboxIn
from app.twilio import normalize_phone

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
PARTNER_KINDS = ("agency", "hospital", "employer", "other")  # what the Command Center treats as referral partners
CC_KEY = "cc_description"


def require_integration_key(x_api_key: str | None = Header(default=None), settings: Settings = Depends(settings_dep)) -> str:
    if not settings.integration_api_key:
        raise HTTPException(status_code=503, detail="INTEGRATION_API_KEY is not set")
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.integration_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    return "command-center"


class BiginAccount(BaseModel):
    model_config = {"extra": "ignore"}
    Account_Name: str = Field(min_length=1, max_length=200)
    Description: str = Field("", max_length=4000)
    Phone: str = Field("", max_length=50)
    Website: str = Field("", max_length=255)


class BiginUpsertIn(BaseModel):
    data: list[BiginAccount] = Field(min_length=1, max_length=100)
    duplicate_check_fields: list[str] = Field(default_factory=lambda: ["Account_Name"])


def _as_bigin(c: Company) -> dict:
    desc = (c.extra or {}).get(CC_KEY) or c.notes or ""
    updated = c.updated_at if c.updated_at.tzinfo else c.updated_at.replace(tzinfo=timezone.utc)
    return {"id": str(c.id), "Account_Name": c.name, "Phone": c.phone or None, "Website": c.website or None,
            "Description": desc or None, "Modified_Time": updated.isoformat()}


@router.get("/bigin-accounts")
def list_accounts(db: Session = Depends(get_db), _: str = Depends(require_integration_key)):
    """Partner organizations in Bigin's Accounts shape: {"data": [...]}."""
    rows = db.scalars(select(Company).where(Company.kind.in_(PARTNER_KINDS)).order_by(Company.name)).all()
    return {"data": [_as_bigin(c) for c in rows], "info": {"count": len(rows), "more_records": False}}


@router.post("/bigin-accounts/upsert")
def upsert_accounts(body: BiginUpsertIn, db: Session = Depends(get_db), source: str = Depends(require_integration_key),
                    settings: Settings = Depends(settings_dep)):
    """Upsert by Account_Name (case-insensitive). Phone and website fill blanks only; the Command
    Center description goes to extra.cc_description and never touches staff notes."""
    created, updated, results = 0, 0, []
    now = datetime.now(timezone.utc).isoformat()
    for a in body.data:
        name = a.Account_Name.strip()
        row = db.scalar(select(Company).where(func.lower(Company.name) == name.lower()))
        phone = normalize_phone(a.Phone) if a.Phone else ""
        if row is None:
            row = Company(name=name, kind=guess_company_kind(name), phone=phone, website=a.Website.strip(),
                          extra={CC_KEY: a.Description, "source": source, "cc_updated_at": now})
            db.add(row)
            db.flush()
            created += 1
            action = "insert"
        else:
            changed = False
            if (row.extra or {}).get(CC_KEY) != a.Description:
                row.extra = {**(row.extra or {}), CC_KEY: a.Description, "cc_updated_at": now}
                changed = True
            if phone and not row.phone:
                row.phone, changed = phone, True
            if a.Website and not row.website:
                row.website, changed = a.Website.strip(), True
            updated += changed
            action = "update"
        results.append({"code": "SUCCESS", "action": action, "details": {"id": str(row.id)}, "status": "success"})
    write_audit(db, actor=None, action="integration.bigin_upsert", entity="company", entity_id=None,
                details={"source": source, "rows": len(body.data), "created": created, "updated": updated})
    db.commit()
    return {"data": results, "created": created, "updated": updated}


# ---- n8n jobs (comparison items 3 and 13, adopted 2026-11-09) ----
def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/stuck-deals")
def stuck_deals(days: int = Query(14, ge=1, le=365), db: Session = Depends(get_db), _: str = Depends(require_integration_key)):
    """Item 3: open deals with no stage change, activity, or note for `days` days. n8n drafts a
    note from this list (draft mode: Paul approves each one) and posts it back through /notes."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    slugs = {p.id: p.slug for p in db.scalars(select(Pipeline)).all()}
    out = []
    for d in db.scalars(select(Deal).where(Deal.status == "open").order_by(Deal.id)).all():
        touches = [_aware(d.created_at)]
        touches += [_aware(h.at) for h in db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id == d.id)).all()]
        touches += [_aware(a.updated_at) for a in db.scalars(select(Activity).where(Activity.deal_id == d.id)).all()]
        touches += [_aware(n.created_at) for n in db.scalars(select(Note).where(Note.entity == "deal", Note.entity_id == d.id)).all()]
        last = max(t for t in touches if t is not None)
        if last < cutoff:
            out.append({"deal_id": d.id, "title": d.title, "pipeline": slugs.get(d.pipeline_id, ""),
                        "stage": d.stage.name if d.stage else None, "owner_id": d.owner_id,
                        "last_touch_at": last.isoformat(), "days_quiet": (now - last).days,
                        "next_action_at": d.next_action_at.isoformat() if d.next_action_at else None})
    return {"days": days, "count": len(out), "deals": out}


class IntegrationNoteIn(BaseModel):
    entity: str = Field(pattern="^(deal|contact|company)$")
    entity_id: int
    body: str = Field(min_length=1, max_length=4000)
    author: str = Field("n8n", max_length=80)


@router.post("/notes", status_code=201)
def post_note(item: IntegrationNoteIn, db: Session = Depends(get_db), source: str = Depends(require_integration_key)):
    """A note written by an n8n job after Paul approves the draft. Refused when the text carries a
    protected-trait term (same guard as staff notes and decisions)."""
    hits = protected_term_hits(item.body)
    if hits:
        raise HTTPException(status_code=422, detail=f"Note text is not allowed to carry: {', '.join(hits)}")
    model = {"deal": Deal, "contact": Contact, "company": Company}[item.entity]
    get_or_404(db, model, item.entity_id, item.entity.title())
    row = Note(entity=item.entity, entity_id=item.entity_id, body=item.body, author_id=None, author_email=f"{source}:{item.author}")
    db.add(row)
    db.flush()
    write_audit(db, actor=None, action="note.create", entity=item.entity, entity_id=item.entity_id,
                details={"note_id": row.id, "source": source, "author": item.author})
    db.commit()
    return {"id": row.id, "entity": item.entity, "entity_id": item.entity_id, "created_at": row.created_at}


@router.get("/keyword-scan")
def keyword_scan(db: Session = Depends(get_db), _: str = Depends(require_integration_key)):
    """Item 13: weekly scan of free-text fields for the Rule 11 word list. Counts only; no text,
    no ids beyond the table, so nothing restricted leaves this database."""
    def scan(rows) -> tuple[int, int]:
        n = hit = 0
        for text in rows:
            n += 1
            if text and protected_term_hits(text):
                hit += 1
        return n, hit
    report = {}
    for name, stmt in (
        ("notes", select(Note.body)),
        ("contact_notes", select(Contact.notes).where(Contact.notes != "")),
        ("company_notes", select(Company.notes).where(Company.notes != "")),
        ("deal_lost_reasons", select(Deal.lost_reason).where(Deal.lost_reason != "")),
        ("activity_bodies", select(Activity.body).where(Activity.body != "")),
        ("activity_subjects", select(Activity.subject)),
        ("messages", select(Message.body)),
    ):
        scanned, flagged = scan(db.scalars(stmt).all())
        report[name] = {"scanned": scanned, "flagged": flagged}
    return {"scanned_at": datetime.now(timezone.utc).isoformat(), "fields": report,
            "flagged_total": sum(v["flagged"] for v in report.values())}


# ---- outbox drafts from agents (Atlas gap 2, 2026-11-22) ----
@router.post("/outbox", status_code=201)
def agent_outbox_draft(item: AgentOutboxIn, db: Session = Depends(get_db), source: str = Depends(require_integration_key),
                       settings: Settings = Depends(settings_dep)):
    """An agent (n8n job or the Claude lane) puts a draft in the queue. It arrives as a draft, linted,
    and stays there until an admin approves it in the staff app; this key can neither approve nor send."""
    contact = get_or_404(db, Contact, item.contact_id, "Contact")
    deal = get_or_404(db, Deal, item.deal_id, "Deal") if item.deal_id else None
    try:
        row = create_item(db, settings, channel=item.channel, contact=contact, deal=deal, subject=item.subject, body=item.body,
                          marketing=item.marketing, send_after=item.send_after, allow_outside_window=item.allow_outside_window,
                          in_reply_to_email_id=item.in_reply_to_email_id, created_by=f"agent:{item.agent.strip()}", actor=None)
    except OutboxError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.commit()
    return {"id": row.id, "status": row.status, "lint": row.lint, "source": source}


# ---- file service callback (Mac mini, n8n): the file is stored, with its Google Drive copy ----
class StoredIn(BaseModel):
    storage_key: str = Field(min_length=1, max_length=500)
    size_bytes: int | None = None
    content_type: str = Field("", max_length=100)
    drive_file_id: str | None = Field(None, max_length=128)


@router.post("/documents/{doc_id}/stored")
def document_stored(doc_id: int, item: StoredIn, db: Session = Depends(get_db), source: str = Depends(require_integration_key)):
    row = get_or_404(db, Document, doc_id, "Document")
    row.storage_key, row.status = item.storage_key, "stored"
    row.size_bytes = item.size_bytes
    if item.content_type:
        row.content_type = item.content_type
    row.drive_file_id = item.drive_file_id
    write_audit(db, actor=None, action="document.stored", entity="document", entity_id=row.id,
                details={"source": source, "size_bytes": item.size_bytes, "drive": bool(item.drive_file_id)})
    db.commit()
    return {"id": row.id, "status": row.status}
