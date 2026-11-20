from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.fair_housing import protected_term_hits

RoomType = Literal["private", "shared"]
RoomStatus = Literal["available", "occupied", "hold", "offline"]
TenancyStatus = Literal["pending", "active", "ended"]
DocCategory = Literal["lease", "addendum", "house_rules", "notice", "agency", "voucher", "receipt", "other"]
MaintCategory = Literal["plumbing", "electrical", "appliance", "hvac", "pest", "safety", "cleaning", "other"]
MaintStatus = Literal["pending_screening", "withheld", "open", "in_progress", "done", "closed"]
Scope = Literal["documents", "maintenance", "balance", "payments"]


def _no_protected_terms(v: str) -> str:
    hits = protected_term_hits(v)
    if hits:
        raise ValueError(f"not allowed to carry: {', '.join(hits)}")
    return v


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class RoomIn(BaseModel):
    property_id: int
    name: str = Field(min_length=1, max_length=60)
    room_type: RoomType = "private"
    monthly_rent: Decimal | None = None
    status: RoomStatus = "available"


class RoomOut(RoomIn, _Out):
    pass


class TenancyIn(BaseModel):
    contact_id: int
    property_id: int
    room_id: int | None = None
    status: TenancyStatus = "active"
    start_date: date
    end_date: date | None = None
    rent_amount: Decimal | None = None
    deposit_amount: Decimal | None = None
    notes: str = Field("", max_length=2000)
    _v = field_validator("notes")(_no_protected_terms)


class TenancyOut(TenancyIn, _Out):
    contact_name: str | None = None
    property_address: str | None = None
    room_name: str | None = None


class DocumentIn(BaseModel):
    tenancy_id: int | None = None
    contact_id: int | None = None
    property_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    category: DocCategory = "other"
    content_type: str = Field("", max_length=100)
    shared_with_resident: bool = False
    shared_with_case_manager: bool = False


class DocumentOut(DocumentIn, _Out):
    status: str
    size_bytes: int | None = None
    uploaded_by: str | None = None
    uploaded_role: str = ""


class DocumentCreated(BaseModel):
    document: DocumentOut
    upload: dict


class MaintenanceIn(BaseModel):
    tenancy_id: int | None = None  # residents with one tenancy may omit it
    category: MaintCategory = "other"
    title: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=4000)


class MaintenanceUpdate(BaseModel):
    status: MaintStatus | None = None
    priority: Literal["low", "normal", "high"] | None = None
    assigned_to: str | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: int
    author_role: str
    body: str
    screening_status: str
    created_at: datetime
    mine: bool = False


class MaintenanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenancy_id: int
    category: str
    title: str
    description: str
    status: str
    screening_status: str
    priority: str
    assigned_to: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    property_address: str | None = None
    room_name: str | None = None
    resident_name: str | None = None
    comments: list[CommentOut] = []


class GrantIn(BaseModel):
    tenancy_id: int | None = None
    case_manager_email: str = Field(min_length=3, max_length=200)
    scopes: list[Scope] = Field(default_factory=lambda: ["documents", "maintenance"])
    expires_at: datetime | None = None

    @field_validator("case_manager_email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class GrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenancy_id: int
    case_manager_email: str
    case_manager_user_id: str | None
    scopes: list[str]
    granted_by_role: str
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class PortalProfile(BaseModel):
    role: str
    email: str
    display_name: str | None = None
    first_name: str = ""
    phone: str = ""
    contact_id: int | None = None
    tenancies: list[TenancyOut] = []
    grants: list[GrantOut] = []
    rule11_notice: str = "Do not include health information. Describe the problem with the room or the house only."


class ProfileUpdate(BaseModel):
    first_name: str = Field("", max_length=80)
    phone: str = Field("", max_length=40)
