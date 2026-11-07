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

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, UniqueConstraint  # noqa: E402
from sqlalchemy.orm import relationship  # noqa: E402


class CrmTimestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Company(CrmTimestamps, Base):
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


class Contact(CrmTimestamps, Base):
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


class Deal(CrmTimestamps, Base):
    __tablename__ = "deals"
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
    lost_reason: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict] = mapped_column(JSONType, default=dict)
    legacy_ref: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage = relationship("PipelineStage", lazy="joined")


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
