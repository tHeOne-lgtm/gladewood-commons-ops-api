from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.underwriting import DEAL_TYPES, DEFAULT_SETTINGS, INPUT_KEYS, PROPERTY_STAGES, num


class UnderwritingIn(BaseModel):
    """Everything the underwriting page edits except the stage (POST .../stage) and the market block (set by
    listing research). Omitted fields keep their stored value."""
    deal_type: str | None = None
    private_rooms: int | None = Field(default=None, ge=0, le=99)
    shared_rooms: int | None = Field(default=None, ge=0, le=99)
    bedrooms: int | None = Field(default=None, ge=0, le=99)
    lease_cost: Decimal | None = Field(default=None, ge=0)
    sale_price: Decimal | None = Field(default=None, ge=0)
    utilities: Decimal | None = Field(default=None, ge=0)
    inputs: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("deal_type")
    @classmethod
    def _deal_type(cls, v):
        if v is not None and v not in DEAL_TYPES:
            raise ValueError("deal_type must be lease or buy")
        return v

    @field_validator("inputs")
    @classmethod
    def _inputs(cls, v):
        if v is None:
            return v
        clean: dict[str, Any] = {}
        for k, val in v.items():
            if k not in INPUT_KEYS:
                raise ValueError(f"unknown input {k}")
            if val is None or val == "":
                continue  # blank means "use the default"
            if k == "mode":
                if val not in DEAL_TYPES:
                    raise ValueError("mode must be lease or buy")
                clean[k] = val
                continue
            n = num(val)
            if n is None:
                raise ValueError(f"{k} must be a number")
            clean[k] = n
        return clean


class StageIn(BaseModel):
    stage: str

    @field_validator("stage")
    @classmethod
    def _stage(cls, v):
        if v not in PROPERTY_STAGES:
            raise ValueError("stage must be one of " + ", ".join(PROPERTY_STAGES))
        return v


class SettingsIn(BaseModel):
    """Partial update: only the keys sent change. Every key must be one the model reads."""
    values: dict[str, Decimal]

    @field_validator("values")
    @classmethod
    def _keys(cls, v):
        bad = [k for k in v if k not in DEFAULT_SETTINGS]
        if bad:
            raise ValueError("unknown setting " + ", ".join(bad))
        return v


class Check(BaseModel):
    label: str
    value: str
    target: str
    ok: bool


class UnderwritingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    property_id: int
    address: str
    exists: bool
    stage: str
    deal_type: str
    private_rooms: int | None
    shared_rooms: int | None
    bedrooms: int | None
    lease_cost: Decimal | None
    sale_price: Decimal | None
    utilities: Decimal | None
    inputs: dict[str, Any]
    market: dict[str, Any]
    notes: str
    stage_changed_at: datetime | None
    updated_at: datetime | None
    resolved: dict[str, Any]
    missing: list[str]
    calc: dict[str, Any] | None
    checks: list[Check] | None
    scenarios: dict[str, dict[str, Any]] | None
    projection: list[dict[str, float]] | None


class UnderwritingSummary(BaseModel):
    property_id: int
    address: str
    stage: str
    deal_type: str
    beds: float
    missing: list[str]
    cash: float | None
    coverage: float | None
    breakeven: float | None
    coc: float | None
    targets_met: int | None
    targets: int | None
