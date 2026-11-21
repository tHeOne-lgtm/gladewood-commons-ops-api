"""SQLAlchemy models. Money and dates stay TEXT on the legacy tables until the
Phase 1 migration converts them with a dry-run rejection report."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


JSONType = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=True
    )


class Property(TimestampMixin, Base):
    __tablename__ = "properties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(Text, default="")
    area: Mapped[str] = mapped_column(Text, default="")
    beds: Mapped[str] = mapped_column(Text, default="")
    baths: Mapped[str] = mapped_column(Text, default="")
    zoning_fit: Mapped[str] = mapped_column(Text, default="")
    rent: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="Not sourced yet")
    next_action: Mapped[str] = mapped_column(Text, default="")


class Prospect(TimestampMixin, Base):
    __tablename__ = "prospects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initials: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="")
    room_type: Mapped[str] = mapped_column(Text, default="")
    income_verified: Mapped[str] = mapped_column(Text, default="Not verified")
    deposit: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="Inquiry")
    notes: Mapped[str] = mapped_column(Text, default="")


class Resident(TimestampMixin, Base):
    __tablename__ = "residents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    initials: Mapped[str] = mapped_column(Text, default="")
    room: Mapped[str] = mapped_column(Text, default="")
    lease_start: Mapped[str] = mapped_column(Text, default="")
    rent_status: Mapped[str] = mapped_column(Text, default="")
    house_rules: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class ConflictEntry(TimestampMixin, Base):
    __tablename__ = "conflict_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_date: Mapped[str] = mapped_column(Text, default="")
    house: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(Text, default="")
    safety_flag: Mapped[str] = mapped_column(Text, default="None")
    status: Mapped[str] = mapped_column(Text, default="")
    resolution: Mapped[str] = mapped_column(Text, default="")


class Financial(Base):
    __tablename__ = "financials"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    """Application user keyed by the Supabase Auth user id (JWT `sub`)."""
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(Text, default="", index=True)
    role: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only. Rows are never updated or deleted by the application."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


# ---------------------------------------------------------------------------
# Phase 1: CRM
# ---------------------------------------------------------------------------
from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Numeric, UniqueConstraint  # noqa: E402
from sqlalchemy.orm import backref, relationship  # noqa: E402


class CrmTimestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ImportBatch(Base):
    """One row per import run (CSV upload or the legacy migration). Rows created by the run
    carry its id so an admin can undo the whole run. Data tier: Business."""
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16))            # csv | legacy
    entity: Mapped[str] = mapped_column(String(32))            # contact | company | legacy
    filename: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    undone_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ImportedRow:
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="SET NULL"), nullable=True, index=True)


class Company(ImportedRow, CrmTimestamps, Base):
    """Data tier: Business."""
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="other")
    website: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(Text, default="")
    address: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict] = mapped_column(JSONType, default=dict)
    legacy_ref: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)


class Contact(ImportedRow, CrmTimestamps, Base):
    """Data tier: Personal."""
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, index=True)
    first_name: Mapped[str] = mapped_column(Text, default="")
    last_name: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(Text, default="", index=True)
    phone: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="other", index=True)
    source: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict] = mapped_column(JSONType, default=dict)
    legacy_ref: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    portal_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)  # Supabase user id
    company = relationship("Company", lazy="joined")


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class RecordTag(Base):
    __tablename__ = "record_tags"
    __table_args__ = (UniqueConstraint("entity", "entity_id", "tag_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))
    tag = relationship("Tag", lazy="joined")


class Pipeline(Base):
    __tablename__ = "pipelines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    stages = relationship("PipelineStage", order_by="PipelineStage.position", cascade="all, delete-orphan",
                          lazy="selectin")


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    __table_args__ = (UniqueConstraint("pipeline_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    probability: Mapped[int] = mapped_column(Integer, default=0)
    is_won: Mapped[bool] = mapped_column(Boolean, default=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, default=False)


OPEN_DEAL_RULE = "status <> 'open' OR (owner_id IS NOT NULL AND next_action_at IS NOT NULL)"


class Deal(ImportedRow, CrmTimestamps, Base):
    """Data tier: Business (links to Personal rows by id). An open deal always has an owner
    and a next-action date (comparison item 1, 2026-11-09)."""
    __tablename__ = "deals"
    __table_args__ = (CheckConstraint(OPEN_DEAL_RULE, name="ck_deals_open_has_owner_and_next_action"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"), index=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("pipeline_stages.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_close: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_action_at: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    lost_reason: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict] = mapped_column(JSONType, default=dict)
    legacy_ref: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage = relationship("PipelineStage", lazy="joined")
    contact = relationship("Contact", lazy="joined")
    company = relationship("Company", lazy="joined")
    property = relationship("Property", lazy="joined")


class DealStageHistory(Base):
    __tablename__ = "deal_stage_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), index=True)
    from_stage_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_stage_id: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Activity(CrmTimestamps, Base):
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="task", index=True)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[str] = mapped_column(String(8), default="normal")
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------
# Comparison item 5 (2026-11-09): decision log and consents
# ---------------------------------------------------------------------------
class DecisionLog(Base):
    """One row per application decision: which written criteria version was applied, whether it was
    met, the outcome, and a short reason that must name a criterion and never a protected trait.
    Append-only: no update or delete route exists, and rows are kept for at least two years
    (Fair Housing Rule 11). Data tier: Personal."""
    __tablename__ = "decision_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(16), index=True)          # deal | contact
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    criteria_version: Mapped[str] = mapped_column(String(32))
    criteria_met: Mapped[bool] = mapped_column(Boolean)
    outcome: Mapped[str] = mapped_column(String(16), index=True)         # approved | declined | withdrawn
    reason: Mapped[str] = mapped_column(String(500))
    decided_by: Mapped[str] = mapped_column(String(64), index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    retain_until: Mapped[date] = mapped_column(Date)                      # decided_at + 2 years, minimum


class Consent(Base):
    """A contact's consent for one channel or purpose, with when it was given, where it came from,
    and when it was withdrawn. A consent is active while `withdrawn_at` is null. No free text:
    the row records the fact of consent, nothing about the person. Data tier: Personal."""
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    consent_type: Mapped[str] = mapped_column(String(32), index=True)    # sms | email | calls | portal | partner_sharing
    source: Mapped[str] = mapped_column(String(16))                      # form | email | phone | in_person | import
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    withdrawn_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Message(Base):
    """One WhatsApp (or SMS) message, inbound or outbound, keyed to a phone number and, when
    matched, a contact. Body text is operational conversation content; never copy it into
    notes or templates. Data tier: Personal."""
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp", index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)  # E.164
    body: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(16), default="twilio")
    provider_sid: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="received")  # received|queued|sent|delivered|read|failed|undelivered
    error_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AutomationRun(Base):
    """One firing of an automation rule for one record. Rules check this table before acting,
    so a rule never creates the same task twice and cron can run as often as needed."""
    __tablename__ = "automation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule: Mapped[str] = mapped_column(String(48), index=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    details: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class EmailTemplate(Base):
    """Merge-field email text. Templates never carry protected-trait language (checked on save)."""
    __tablename__ = "email_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="transactional")  # transactional | campaign
    audience: Mapped[str] = mapped_column(String(16), default="any")          # resident | partner | owner | any
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    body_html: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Campaign(Base):
    """A mass send to a segment. The segment holds only source, kind, tag, stage, and company-kind
    filters (schema-enforced), never free text or extra fields."""
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    template_id: Mapped[int] = mapped_column(ForeignKey("email_templates.id"))
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)  # draft|scheduled|sending|sent|cancelled
    segment: Mapped[dict] = mapped_column(JSONType, default=dict)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    template = relationship("EmailTemplate", lazy="joined")


class Email(Base):
    """One outbound email, 1:1 or one campaign recipient. Skipped recipients get a row too, with the
    reason, so a campaign report accounts for everyone in the segment."""
    __tablename__ = "emails"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("email_templates.id", ondelete="SET NULL"), nullable=True)
    to_email: Mapped[str] = mapped_column(Text, index=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(16), default="log")
    provider_message_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)  # queued|sent|delivered|bounced|complained|failed|skipped
    skip_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SavedView(Base):
    """A named filter set for a list screen. Filters are a flat dict of the screen's query params
    (allowlisted per entity in the schema), never free text beyond the search box value."""
    __tablename__ = "saved_views"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(16), index=True)  # contacts | companies | deals | activities
    name: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSONType, default=dict)
    sort: Mapped[str] = mapped_column(String(40), default="")
    columns: Mapped[list] = mapped_column(JSONType, default=list)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    shared: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---- Housing and portal v1 (migration 0010; plan Section 6 and 7). Data tier: Personal unless noted. ----
class Room(Base):
    """Data tier: Business."""
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    room_type: Mapped[str] = mapped_column(String(16), default="private")   # private | shared
    monthly_rent: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="available")    # available | occupied | hold | offline
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Tenancy(Base):
    """A resident's stay in a room. Links the resident contact (and their portal login) to housing."""
    __tablename__ = "tenancies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="RESTRICT"), index=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="RESTRICT"), index=True)
    room_id: Mapped[int | None] = mapped_column(ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # pending | active | ended
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rent_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    deposit_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")  # operational only; the protected-term guard applies
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    contact = relationship("Contact", lazy="joined")
    property = relationship("Property", lazy="joined")
    room = relationship("Room", lazy="joined")


class Document(Base):
    """Metadata only. The file lives on the Mac mini file service with a Google Drive copy."""
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenancy_id: Mapped[int | None] = mapped_column(ForeignKey("tenancies.id", ondelete="CASCADE"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(24), default="other")  # lease | addendum | house_rules | notice | agency | voucher | receipt | other
    status: Mapped[str] = mapped_column(String(16), default="pending_upload")  # pending_upload | stored | removed
    storage_key: Mapped[str] = mapped_column(Text, default="")
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    shared_with_resident: Mapped[bool] = mapped_column(Boolean, default=False)
    shared_with_case_manager: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_role: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MaintenanceRequest(Base):
    """Resident maintenance request. Free text goes through the Rule 11 router before it is kept:
    clear -> stored; flagged -> text dropped, marker kept; router unreachable -> held (decision 2026-11-20)."""
    __tablename__ = "maintenance_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenancy_id: Mapped[int] = mapped_column(ForeignKey("tenancies.id", ondelete="CASCADE"), index=True)
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(24), default="other")  # plumbing | electrical | appliance | hvac | pest | safety | cleaning | other
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending_screening", index=True)  # pending_screening | withheld | open | in_progress | done | closed
    screening_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | clear | flagged | unreachable
    screening_attempts: Mapped[int] = mapped_column(Integer, default=0)
    screened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[str] = mapped_column(String(8), default="normal")
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    tenancy = relationship("Tenancy", lazy="joined")


class MaintenanceComment(Base):
    __tablename__ = "maintenance_comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("maintenance_requests.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    author_role: Mapped[str] = mapped_column(String(16), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    screening_status: Mapped[str] = mapped_column(String(16), default="clear")  # staff text: clear; resident text: screened
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PortalAccessGrant(Base):
    """A resident's grant letting one case manager see parts of one tenancy (plan Section 6)."""
    __tablename__ = "portal_access_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenancy_id: Mapped[int] = mapped_column(ForeignKey("tenancies.id", ondelete="CASCADE"), index=True)
    case_manager_email: Mapped[str] = mapped_column(Text, index=True)
    case_manager_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scopes: Mapped[list] = mapped_column(JSONType, default=list)  # subset of documents, maintenance, balance, payments
    granted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    granted_by_role: Mapped[str] = mapped_column(String(16), default="resident")
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Underwriting(Base):
    """One per property: the Prospect Hub underwriting view (stage, deal type, room plan, costs, per-property
    overrides and the market block). The math lives in app/underwriting.py. Data tier: Business."""
    __tablename__ = "underwritings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), unique=True, index=True)
    stage: Mapped[str] = mapped_column(String(16), default="Found", index=True)
    deal_type: Mapped[str] = mapped_column(String(8), default="lease")
    private_rooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shared_rooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bedrooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lease_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    utilities: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSONType, default=dict)
    market: Mapped[dict] = mapped_column(JSONType, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    stage_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    # delete-orphan so the row goes with its property on SQLite too (Postgres has ON DELETE CASCADE)
    property = relationship("Property", lazy="joined",
                            backref=backref("underwriting", uselist=False, cascade="all, delete-orphan"))


class UnderwritingSetting(Base):
    """Planning defaults and targets for underwriting (the Hub's Settings page). One row per key."""
    __tablename__ = "underwriting_settings"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4))
