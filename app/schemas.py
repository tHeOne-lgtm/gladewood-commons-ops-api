"""Pydantic request and response schemas."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime | None = None


class PropertyIn(BaseModel):
    address: str = ""
    area: str = ""
    beds: str = ""
    baths: str = ""
    zoning_fit: str = ""
    rent: str = ""
    status: str = "Not sourced yet"
    next_action: str = ""


class PropertyOut(PropertyIn, _Out):
    pass


class ProspectIn(BaseModel):
    initials: str = ""
    source: str = ""
    room_type: str = ""
    income_verified: str = "Not verified"
    deposit: str = ""
    status: str = "Inquiry"
    notes: str = ""


class ProspectOut(ProspectIn, _Out):
    pass


class ResidentIn(BaseModel):
    initials: str = ""
    room: str = ""
    lease_start: str = ""
    rent_status: str = ""
    house_rules: str = ""
    notes: str = ""


class ResidentOut(ResidentIn, _Out):
    pass


class ConflictEntryIn(BaseModel):
    entry_date: str = ""
    house: str = ""
    category: str = ""
    safety_flag: str = "None"
    status: str = ""
    resolution: str = ""


class ConflictEntryOut(ConflictEntryIn, _Out):
    pass


class FinancialsUpdate(BaseModel):
    values: dict[str, str]


class DeleteResult(BaseModel):
    deleted: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role: str
    created_at: datetime
    last_seen_at: datetime
    mfa_required: bool = False


class RoleUpdate(BaseModel):
    role: str = Field(pattern=r"^(admin|staff|tenant|case_manager|pending)$")


class DemandSummary(BaseModel):
    raw_inquiries: int
    screened: int
    income_verified: int
    holding_deposit: int
    target: int


class Health(BaseModel):
    ok: bool
    db: bool
