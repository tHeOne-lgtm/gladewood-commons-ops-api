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
