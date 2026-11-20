"""Machine-credential routes for the Command Center sync (plan Section 9, item 3 cutover).

The Command Center page pushes engaged referral partners as a Bigin-shaped upsert body and
reads the partner list back in Bigin's Accounts shape. These two routes speak that shape, so
the page and the Make scenario (and the n8n workflow after it) only change their URL and auth.

Auth: header `X-Api-Key` equal to INTEGRATION_API_KEY. Constant-time compare. The key opens
nothing outside this router.
"""
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.bigin_import import guess_company_kind
from app.config import Settings, settings_dep
from app.db import get_db
from app.models import Company
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
