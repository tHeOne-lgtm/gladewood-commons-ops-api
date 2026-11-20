
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.campaigns import preview, report, send
from app.config import Settings, settings_dep
from app.crm_common import get_or_404
from app.db import get_db
from app.models import Campaign, EmailTemplate, User
from app.schemas_crm import CampaignIn, CampaignOut, CampaignPreviewOut, CampaignReportOut

router = APIRouter(prefix="/api/campaigns", tags=["crm: campaigns"])


def _out(row: Campaign) -> CampaignOut:
    o = CampaignOut.model_validate(row)
    o.template_name = row.template.name if row.template else None
    return o


@router.get("", response_model=list[CampaignOut])
def list_campaigns(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return [_out(r) for r in db.scalars(select(Campaign).order_by(Campaign.id.desc())).all()]


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(item: CampaignIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    t = get_or_404(db, EmailTemplate, item.template_id, "Template")
    if not t.is_active:
        raise HTTPException(status_code=422, detail="Template is inactive")
    row = Campaign(name=item.name, template_id=t.id, segment=item.segment.model_dump(), scheduled_at=item.scheduled_at,
                   status="scheduled" if item.scheduled_at else "draft", created_by=user.id)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="campaign.create", entity="campaign", entity_id=row.id, details={"name": row.name})
    db.commit()
    return _out(row)


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return _out(get_or_404(db, Campaign, campaign_id, "Campaign"))


@router.put("/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: int, item: CampaignIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Campaign, campaign_id, "Campaign")
    if row.status not in ("draft", "scheduled"):
        raise HTTPException(status_code=409, detail=f"Campaign is {row.status} and can no longer be edited")
    get_or_404(db, EmailTemplate, item.template_id, "Template")
    row.name, row.template_id, row.segment, row.scheduled_at = item.name, item.template_id, item.segment.model_dump(), item.scheduled_at
    row.status = "scheduled" if item.scheduled_at else "draft"
    write_audit(db, actor=user, action="campaign.update", entity="campaign", entity_id=row.id, details={"name": row.name})
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
def cancel_campaign(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Campaign, campaign_id, "Campaign")
    if row.status not in ("draft", "scheduled"):
        raise HTTPException(status_code=409, detail=f"Campaign is {row.status}")
    row.status = "cancelled"
    write_audit(db, actor=user, action="campaign.cancel", entity="campaign", entity_id=row.id, details={})
    db.commit()
    return _out(row)


@router.post("/{campaign_id}/preview", response_model=CampaignPreviewOut)
def preview_campaign(campaign_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff),
                     settings: Settings = Depends(settings_dep)):
    return preview(db, settings, get_or_404(db, Campaign, campaign_id, "Campaign"))


@router.post("/{campaign_id}/send", response_model=CampaignReportOut)
def send_campaign(campaign_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_staff),
                  settings: Settings = Depends(settings_dep)):
    row = get_or_404(db, Campaign, campaign_id, "Campaign")
    if not settings.email_postal_address and settings.email_provider != "log":
        raise HTTPException(status_code=503, detail="EMAIL_POSTAL_ADDRESS must be set before a campaign can go out")
    try:
        out = send(db, settings, row, actor_id=user.id, transport=getattr(request.app.state, "email_transport", None))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return out


@router.get("/{campaign_id}/report", response_model=CampaignReportOut)
def campaign_report(campaign_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return report(db, get_or_404(db, Campaign, campaign_id, "Campaign"))


