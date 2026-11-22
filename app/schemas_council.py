from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["Brainstorm", "Negotiate", "Bottleneck", "Major Decision"]
Door = Literal["one-way", "two-way"]
Call = Literal["Go", "Go with conditions", "No"]
Decision = Literal["adopted", "adopted with changes", "declined", "deferred"]


class CouncilSessionIn(BaseModel):
    panel: Literal["A"] = "A"            # only the Business panel belongs in the CRM
    mode: Mode
    door: Door
    brief: str = Field(min_length=1, max_length=30000)
    verdict_call: Call
    verdict_text: str = Field(default="", max_length=8000)
    conditions: list[str] = Field(default_factory=list, max_length=20)
    split: str = Field(default="", max_length=4000)
    human_check: str = Field(default="", max_length=1000)
    property_id: int | None = None
    deal_id: int | None = None
    commitment_ref: str | None = Field(default=None, max_length=64)
    held_at: datetime | None = None


class CouncilDecisionIn(BaseModel):
    decision: Decision
    decision_reason: str = Field(default="", max_length=400)
    review_date: date | None = None


class CouncilSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    held_at: datetime
    panel: str
    mode: str
    door: str
    brief: str
    verdict_call: str
    verdict_text: str
    conditions: list[str]
    split: str
    human_check: str
    property_id: int | None
    deal_id: int | None
    commitment_ref: str | None
    created_by: str
    decision: str | None
    decision_reason: str
    review_date: date | None
    decided_at: datetime | None
    decided_by: str | None
