"""Pydantic schemas for the CRM module."""
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ExtraValue = str | int | float | bool | None
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def validate_extra(v: dict) -> dict:
    if len(v) > 30:
        raise ValueError("extra may hold at most 30 keys")
    for k in v:
        if not _KEY_RE.match(k):
            raise ValueError(f"extra key {k!r} must be snake_case, 40 characters or fewer")
    return v


ContactKind = Literal["prospect", "resident", "landlord", "broker", "case_manager", "vendor", "other"]
CompanyKind = Literal["property_owner", "brokerage", "agency", "hospital", "employer", "vendor", "other"]
ActivityKind = Literal["task", "event", "call"]
Priority = Literal["low", "normal", "high"]
NoteEntity = Literal["contact", "company", "deal", "property", "activity"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: CompanyKind = "other"
    website: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    notes: str = ""
    extra: dict[str, ExtraValue] = Field(default_factory=dict)
    _v_extra = field_validator("extra")(validate_extra)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class CompanyOut(CompanyIn, _Out):
    pass


class ContactIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    kind: ContactKind = "other"
    source: str = ""
    status: Literal["active", "archived"] = "active"
    company_id: int | None = None
    notes: str = ""
    extra: dict[str, ExtraValue] = Field(default_factory=dict)
    _v_extra = field_validator("extra")(validate_extra)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class ContactOut(ContactIn, _Out):
    tags: list[str] = []
    company_name: str | None = None


class TagsSet(BaseModel):
    tags: list[str]

    @field_validator("tags")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        out = []
        for t in v:
            t = t.strip()
            if t and t not in out:
                out.append(t[:60])
        return out


class StageIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    probability: int = Field(0, ge=0, le=100)
    is_won: bool = False
    is_lost: bool = False


class StageOut(StageIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    position: int


class PipelineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    description: str = ""
    is_active: bool = True
    stages: list[StageIn] = Field(min_length=1)


class PipelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    slug: str
    description: str
    position: int
    is_active: bool
    stages: list[StageOut]


class StageSummary(BaseModel):
    stage_id: int
    name: str
    open_count: int
    open_amount: Decimal


class PipelineSummary(BaseModel):
    pipeline_id: int
    open_count: int
    open_amount: Decimal
    won_count: int
    lost_count: int
    stages: list[StageSummary]


class DealIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    pipeline_id: int
    stage_id: int | None = None
    contact_id: int | None = None
    company_id: int | None = None
    property_id: int | None = None
    amount: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    expected_close: date | None = None
    next_action_at: date | None = None
    owner_id: str | None = None
    lost_reason: str = ""
    extra: dict[str, ExtraValue] = Field(default_factory=dict)
    _v_extra = field_validator("extra")(validate_extra)


class DealOut(DealIn, _Out):
    stage_id: int
    status: str
    closed_at: datetime | None = None
    stage_name: str | None = None
    contact_name: str | None = None
    company_name: str | None = None
    property_address: str | None = None
    stage_entered_at: datetime | None = None
    import_batch_id: int | None = None


class DealMove(BaseModel):
    stage_id: int
    lost_reason: str = ""
    next_action_at: date | None = None


class ActivityIn(BaseModel):
    kind: ActivityKind = "task"
    subject: str = Field(min_length=1, max_length=200)
    body: str = ""
    due_at: datetime | None = None
    priority: Priority = "normal"
    contact_id: int | None = None
    company_id: int | None = None
    deal_id: int | None = None
    assigned_to: str | None = None


class ActivityOut(ActivityIn, _Out):
    completed_at: datetime | None = None


class NoteIn(BaseModel):
    entity: NoteEntity
    entity_id: int
    body: str = Field(min_length=1)


class NoteOut(NoteIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    author_id: str | None
    author_email: str | None
    created_at: datetime
    updated_at: datetime


class TimelineItem(BaseModel):
    at: datetime
    type: str
    summary: str
    actor: str | None = None
    ref_id: int | None = None
    details: dict | None = None


class DuplicateGroup(BaseModel):
    reason: str
    value: str
    contact_ids: list[int]


class ImportError_(BaseModel):
    row: int
    error: str


class ImportDuplicate(BaseModel):
    row: int
    reason: Literal["email", "phone", "name"]
    value: str
    existing_contact_id: int | None = None   # None when the match is an earlier row of the same file
    matches_row: int | None = None


class ImportResult(BaseModel):
    batch_id: int | None = None
    created: int
    errors: list[ImportError_]
    duplicates: list[ImportDuplicate] = []


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    entity: str
    filename: str
    created_at: datetime
    created_by: str | None
    row_count: int
    created_count: int
    error_count: int
    duplicate_count: int
    undone_at: datetime | None
    undone_by: str | None


class ImportUndoResult(BaseModel):
    batch_id: int
    deleted: dict[str, int]


class TodayCounts(BaseModel):
    deals_overdue: int
    deals_due_today: int
    activities_overdue: int
    activities_due_today: int
    open_deals: int


class TodayDeal(BaseModel):
    id: int
    title: str
    pipeline_id: int
    stage_name: str | None
    next_action_at: date | None
    owner_id: str | None


class TodayActivity(BaseModel):
    id: int
    kind: str
    subject: str
    due_at: datetime | None
    deal_id: int | None
    assigned_to: str | None


class TodayOut(BaseModel):
    date: date
    mine: TodayCounts
    all: TodayCounts
    deals: list[TodayDeal]
    activities: list[TodayActivity]


class MigrationRejection(BaseModel):
    table: str
    id: int
    field: str
    value: str
    reason: str


class MigrationReport(BaseModel):
    dry_run: bool
    batch_id: int | None = None
    scanned: dict[str, int]
    would_create: dict[str, int]
    skipped_existing: dict[str, int]
    rejections: list[MigrationRejection]


# --- comparison item 5: decision log and consents ---------------------------------------
DecisionEntity = Literal["deal", "contact"]
DecisionOutcome = Literal["approved", "declined", "withdrawn"]
ConsentType = Literal["sms", "whatsapp", "email", "calls", "portal", "partner_sharing"]
ConsentSource = Literal["form", "email", "phone", "in_person", "import", "whatsapp"]


class DecisionIn(BaseModel):
    entity: DecisionEntity
    entity_id: int
    criteria_version: str = Field(min_length=1, max_length=32)
    criteria_met: bool
    outcome: DecisionOutcome
    reason: str = Field(min_length=3, max_length=500,
                        description="Name the written criterion applied. Never a protected trait.")

    @field_validator("criteria_version", "reason")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entity: str
    entity_id: int
    criteria_version: str
    criteria_met: bool
    outcome: str
    reason: str
    decided_by: str
    decided_at: datetime
    retain_until: date


class ConsentIn(BaseModel):
    contact_id: int
    consent_type: ConsentType
    source: ConsentSource
    given_at: datetime | None = None


class ConsentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int
    consent_type: str
    source: str
    given_at: datetime
    withdrawn_at: datetime | None
    recorded_by: str | None
    withdrawn_by: str | None
    active: bool = False


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    channel: str
    direction: str
    contact_id: int | None
    deal_id: int | None
    phone: str
    body: str
    status: str
    error_code: str | None
    media_count: int
    sent_by: str | None
    read_at: datetime | None
    created_at: datetime


class ConversationOut(BaseModel):
    phone: str
    contact_id: int | None
    contact_name: str | None
    consent_active: bool
    window_open: bool
    unread_count: int
    last_message: MessageOut


class SendMessageIn(BaseModel):
    contact_id: int | None = None
    phone: str | None = None
    body: str = Field(min_length=1, max_length=1600)
    allow_outside_window: bool = False


class InquiryFormIn(BaseModel):
    """Public tour or room inquiry. Operational fields only; the form must not ask for health,
    disability, or benefit details, and nothing here stores them."""
    name: str = Field(min_length=1, max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    message: str = Field("", max_length=2000)
    room_preference: str = Field("", max_length=40)
    move_in_target: str = Field("", max_length=40)
    contact_ok: bool = False
    page: str = Field("", max_length=200)
    website: str = Field("", max_length=200)  # honeypot; must stay empty

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class ReferralFormIn(BaseModel):
    """Public referral-partner inquiry from a case manager, coordinator, or employer."""
    name: str = Field(min_length=1, max_length=120)
    organization: str = Field(min_length=1, max_length=200)
    organization_type: str = Field("agency", max_length=32)
    role: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    message: str = Field("", max_length=2000)
    page: str = Field("", max_length=200)
    website: str = Field("", max_length=200)  # honeypot

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class FormResult(BaseModel):
    ok: bool = True
    contact_id: int
    deal_id: int | None
    created_contact: bool


class AutomationAction(BaseModel):
    rule: str
    entity: str
    entity_id: int
    action: str
    detail: str = ""


class AutomationReport(BaseModel):
    dry_run: bool
    ran_at: datetime
    actions: list[AutomationAction]
    counts: dict[str, int]


# ---- Email (Phase 2c) ----
TemplateKind = Literal["transactional", "campaign"]
Audience = Literal["resident", "partner", "owner", "any"]


class EmailTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: TemplateKind = "transactional"
    audience: Audience = "any"
    subject: str = Field(min_length=1, max_length=200)
    body_text: str = Field(min_length=1, max_length=20000)
    body_html: str = Field("", max_length=60000)
    is_active: bool = True


class EmailTemplateOut(EmailTemplateIn, _Out):
    created_by: str | None = None


class EmailPreviewIn(BaseModel):
    template_id: int | None = None
    subject: str | None = None
    body_text: str | None = None
    contact_id: int | None = None
    deal_id: int | None = None


class EmailPreviewOut(BaseModel):
    to_email: str
    subject: str
    body_text: str
    body_html: str
    can_send: bool
    skip_reason: str | None = None
    protected_terms: list[str] = []


class SendEmailIn(BaseModel):
    contact_id: int
    deal_id: int | None = None
    template_id: int | None = None
    subject: str | None = Field(None, max_length=200)
    body_text: str | None = Field(None, max_length=20000)
    marketing: bool = False  # True requires active email consent, as a campaign does


class EmailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    contact_id: int | None
    deal_id: int | None
    campaign_id: int | None
    template_id: int | None
    to_email: str
    subject: str
    status: str
    skip_reason: str | None
    error: str | None
    sent_by: str | None
    sent_at: datetime | None
    delivered_at: datetime | None
    opened_at: datetime | None
    clicked_at: datetime | None
    bounced_at: datetime | None
    created_at: datetime


class Segment(BaseModel):
    """Who a campaign goes to. Keys are fixed on purpose: segments are built from source, kind,
    tag, stage, and company kind only, never from notes, extra fields, or anything health-related."""
    model_config = ConfigDict(extra="forbid")
    contact_kind: list[ContactKind] = []
    company_kind: list[CompanyKind] = []
    source: list[str] = Field(default_factory=list, max_length=20)
    tags_any: list[str] = Field(default_factory=list, max_length=20)
    tags_none: list[str] = Field(default_factory=list, max_length=20)
    pipeline: str | None = None
    stages: list[str] = Field(default_factory=list, max_length=20)
    deal_status: Literal["open", "won", "lost", "any"] = "any"
    contact_ids: list[int] = Field(default_factory=list, max_length=500)


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    template_id: int
    segment: Segment = Field(default_factory=Segment)
    scheduled_at: datetime | None = None


class CampaignOut(CampaignIn, _Out):
    status: str
    started_at: datetime | None = None
    sent_at: datetime | None = None
    created_by: str | None = None
    template_name: str | None = None


class CampaignRecipientPreview(BaseModel):
    contact_id: int
    display_name: str
    email: str
    skip_reason: str | None = None


class CampaignPreviewOut(BaseModel):
    campaign_id: int
    total: int
    sendable: int
    skipped: dict[str, int]
    sample: list[CampaignRecipientPreview]
    subject: str
    body_text: str


class CampaignReportOut(BaseModel):
    campaign_id: int
    status: str
    counts: dict[str, int]
    opened: int
    clicked: int
    unsubscribed_after: int
