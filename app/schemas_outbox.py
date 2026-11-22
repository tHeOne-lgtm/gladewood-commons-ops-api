from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.outbox import CHANNELS
from app.outbox_lint import SMS_HARD_LIMIT, TEXT_CHANNELS


class OutboxIn(BaseModel):
    channel: str
    contact_id: int
    deal_id: int | None = None
    subject: str = Field("", max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    marketing: bool = False              # True needs an active consent for the channel, as a campaign does
    send_after: datetime | None = None   # null means the next cron run
    allow_outside_window: bool = False   # WhatsApp only: send even with no inbound message in 24 hours
    in_reply_to_email_id: int | None = None

    @model_validator(mode="after")
    def _shape(self):
        if self.channel not in CHANNELS:
            raise ValueError("channel must be email, sms or whatsapp")
        if self.channel in TEXT_CHANNELS and len(self.body) > SMS_HARD_LIMIT:
            raise ValueError(f"a text body is at most {SMS_HARD_LIMIT} characters")
        if self.channel == "email" and not self.subject.strip():
            raise ValueError("an email needs a subject")
        if self.channel != "email" and self.in_reply_to_email_id is not None:
            raise ValueError("in_reply_to_email_id applies to email only")
        return self


class AgentOutboxIn(OutboxIn):
    agent: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9 _.-]+$")


class OutboxEditIn(BaseModel):
    subject: str | None = Field(None, max_length=200)
    body: str | None = Field(None, min_length=1, max_length=20000)
    send_after: datetime | None = None
    allow_outside_window: bool | None = None
    marketing: bool | None = None


class OutboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    channel: str
    contact_id: int
    deal_id: int | None
    to_address: str
    subject: str
    body: str
    marketing: bool
    send_after: datetime | None
    allow_outside_window: bool
    in_reply_to_email_id: int | None
    thread_key: str
    status: str
    hold_reason: str | None
    lint: dict
    gate_log: list
    created_by: str
    approved_by: str | None
    approved_at: datetime | None
    dispatched_at: datetime | None
    email_id: int | None
    message_id: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    delivery_status: str | None = None


class FlagsOut(BaseModel):
    paused: bool
    shadow: bool
    env_paused: bool
    env_shadow: bool
    flag_paused: bool
    flag_shadow: bool
    text_hours_open: bool
    text_hours: str
    timezone: str
    allowed_prices_set: bool


class FlagsIn(BaseModel):
    paused: bool | None = None
    shadow: bool | None = None


class DispatchReport(BaseModel):
    ran_at: str
    paused: bool
    shadow: bool
    examined: int
    sent: int
    shadowed: int
    held: int
    failed: int
    deferred: int
