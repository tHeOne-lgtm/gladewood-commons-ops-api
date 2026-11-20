"""Mass email campaigns: segment query, preview, send, report."""
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.config import Settings
from app.emailing import send_to_contact, skip_reason
from app.models import Campaign, Company, Consent, Contact, Deal, Email, Pipeline, PipelineStage, RecordTag, Tag
from app.schemas_crm import CampaignPreviewOut, CampaignRecipientPreview, CampaignReportOut, Segment


def segment_contacts(db: Session, seg: Segment) -> list[Contact]:
    q = select(Contact).where(Contact.status == "active")
    if seg.contact_ids:
        q = q.where(Contact.id.in_(seg.contact_ids))
    if seg.contact_kind:
        q = q.where(Contact.kind.in_(seg.contact_kind))
    if seg.source:
        q = q.where(Contact.source.in_(seg.source))
    if seg.company_kind:
        q = q.join(Company, Company.id == Contact.company_id).where(Company.kind.in_(seg.company_kind))
    if seg.tags_any:
        ids = select(RecordTag.entity_id).join(Tag, Tag.id == RecordTag.tag_id).where(
            RecordTag.entity == "contact", Tag.name.in_(seg.tags_any))
        q = q.where(Contact.id.in_(ids))
    if seg.tags_none:
        ids = select(RecordTag.entity_id).join(Tag, Tag.id == RecordTag.tag_id).where(
            RecordTag.entity == "contact", Tag.name.in_(seg.tags_none))
        q = q.where(Contact.id.not_in(ids))
    if seg.pipeline or seg.stages or seg.deal_status != "any":
        dq = select(Deal.contact_id).where(Deal.contact_id.is_not(None))
        if seg.pipeline:
            dq = dq.join(Pipeline, Pipeline.id == Deal.pipeline_id).where(Pipeline.slug == seg.pipeline)
        if seg.stages:
            dq = dq.join(PipelineStage, PipelineStage.id == Deal.stage_id).where(PipelineStage.name.in_(seg.stages))
        if seg.deal_status != "any":
            dq = dq.where(Deal.status == seg.deal_status)
        q = q.where(Contact.id.in_(dq))
    return db.scalars(q.order_by(Contact.id)).all()


def preview(db: Session, settings: Settings, campaign: Campaign) -> CampaignPreviewOut:
    from app.emailing import compose, merge_context
    seg = Segment(**(campaign.segment or {}))
    contacts = segment_contacts(db, seg)
    skipped: Counter = Counter()
    sample: list[CampaignRecipientPreview] = []
    sendable = 0
    for c in contacts:
        reason = skip_reason(db, c, marketing=True)
        if reason:
            skipped[reason] += 1
        else:
            sendable += 1
        if len(sample) < 20:
            sample.append(CampaignRecipientPreview(contact_id=c.id, display_name=c.display_name, email=c.email, skip_reason=reason))
    t = campaign.template
    first = next((c for c in contacts if not skip_reason(db, c, marketing=True)), contacts[0] if contacts else None)
    if first is not None:
        subj, text, _ = compose(settings, subject=t.subject, body_text=t.body_text, body_html=t.body_html,
                                ctx=merge_context(settings, first, None, "Paul"))
    else:
        subj, text = t.subject, t.body_text
    return CampaignPreviewOut(campaign_id=campaign.id, total=len(contacts), sendable=sendable, skipped=dict(skipped),
                              sample=sample, subject=subj, body_text=text)


def send(db: Session, settings: Settings, campaign: Campaign, *, actor_id: str | None, transport=None) -> CampaignReportOut:
    if campaign.status not in ("draft", "scheduled"):
        raise ValueError(f"Campaign is {campaign.status}; only draft or scheduled campaigns can be sent")
    t = campaign.template
    campaign.status, campaign.started_at = "sending", datetime.now(timezone.utc)
    db.flush()
    already = {e.contact_id for e in db.scalars(select(Email).where(Email.campaign_id == campaign.id)).all()}
    for c in segment_contacts(db, Segment(**(campaign.segment or {}))):
        if c.id in already:  # a rerun after a crash never sends twice
            continue
        send_to_contact(db, settings, contact=c, subject=t.subject, body_text=t.body_text, body_html=t.body_html,
                        template=t, sent_by=actor_id, marketing=True, campaign_id=campaign.id, transport=transport)
        db.flush()
    campaign.status, campaign.sent_at = "sent", datetime.now(timezone.utc)
    write_audit(db, actor=None, action="campaign.send", entity="campaign", entity_id=campaign.id,
                details={"name": campaign.name, "by": actor_id})
    return report(db, campaign)


def report(db: Session, campaign: Campaign) -> CampaignReportOut:
    rows = db.execute(select(Email.status, func.count()).where(Email.campaign_id == campaign.id).group_by(Email.status)).all()
    counts = {status: n for status, n in rows}
    opened = db.scalar(select(func.count()).where(Email.campaign_id == campaign.id, Email.opened_at.is_not(None))) or 0
    clicked = db.scalar(select(func.count()).where(Email.campaign_id == campaign.id, Email.clicked_at.is_not(None))) or 0
    unsub = 0
    if campaign.started_at:
        ids = select(Email.contact_id).where(Email.campaign_id == campaign.id, Email.status != "skipped")
        unsub = db.scalar(select(func.count()).where(Consent.contact_id.in_(ids), Consent.consent_type == "email",
                                                     Consent.withdrawn_at >= campaign.started_at)) or 0
    return CampaignReportOut(campaign_id=campaign.id, status=campaign.status, counts=counts, opened=opened,
                             clicked=clicked, unsubscribed_after=unsub)


def send_due(db: Session, settings: Settings, now: datetime | None = None) -> list[CampaignReportOut]:
    now = now or datetime.now(timezone.utc)
    out = []
    for c in db.scalars(select(Campaign).where(Campaign.status == "scheduled", Campaign.scheduled_at <= now)
                        .order_by(Campaign.scheduled_at)).all():
        out.append(send(db, settings, c, actor_id=None))
        db.commit()
    return out
