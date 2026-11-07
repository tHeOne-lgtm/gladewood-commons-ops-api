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
    owner_id: str | None = None
    lost_reason: str = ""
    extra: dict[str, ExtraValue] = Field(default_factory=dict)
    _v_extra = field_validator("extra")(validate_extra)


class DealOut(DealIn, _Out):
    stage_id: int
    status: str
    closed_at: datetime | None = None
    stage_name: str | None = None


class DealMove(BaseModel):
    stage_id: int
    lost_reason: str = ""


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


class ImportResult(BaseModel):
    created: int
    errors: list[ImportError_]


class MigrationRejection(BaseModel):
    table: str
    id: int
    field: str
    value: str
    reason: str


class MigrationReport(BaseModel):
    dry_run: bool
    scanned: dict[str, int]
    would_create: dict[str, int]
    skipped_existing: dict[str, int]
    rejections: list[MigrationRejection]
