"""Comparison item 5 (2026-11-09): decision_log (append-only, two-year retention) and consents.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "decision_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entity", sa.String(16), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("criteria_version", sa.String(32), nullable=False),
        sa.Column("criteria_met", sa.Boolean, nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("decided_by", sa.String(64), nullable=False),
        sa.Column("decided_at", TS, nullable=False, server_default=NOW),
        sa.Column("retain_until", sa.Date, nullable=False),
        sa.CheckConstraint("outcome IN ('approved','declined','withdrawn')", name="ck_decision_log_outcome"),
        sa.CheckConstraint("entity IN ('deal','contact')", name="ck_decision_log_entity"),
    )
    op.create_index("ix_decision_log_entity", "decision_log", ["entity"])
    op.create_index("ix_decision_log_entity_id", "decision_log", ["entity_id"])
    op.create_index("ix_decision_log_outcome", "decision_log", ["outcome"])
    op.create_index("ix_decision_log_decided_by", "decision_log", ["decided_by"])
    op.create_index("ix_decision_log_decided_at", "decision_log", ["decided_at"])

    op.create_table(
        "consents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("given_at", TS, nullable=False, server_default=NOW),
        sa.Column("withdrawn_at", TS),
        sa.Column("recorded_by", sa.String(64)),
        sa.Column("withdrawn_by", sa.String(64)),
    )
    op.create_index("ix_consents_contact_id", "consents", ["contact_id"])
    op.create_index("ix_consents_consent_type", "consents", ["consent_type"])
    # At most one active consent per contact and type.
    op.create_index("uq_consents_active", "consents", ["contact_id", "consent_type"], unique=True,
                    postgresql_where=sa.text("withdrawn_at IS NULL"), sqlite_where=sa.text("withdrawn_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_consents_active", table_name="consents")
    op.drop_index("ix_consents_consent_type", table_name="consents")
    op.drop_index("ix_consents_contact_id", table_name="consents")
    op.drop_table("consents")
    for ix in ("decided_at", "decided_by", "outcome", "entity_id", "entity"):
        op.drop_index(f"ix_decision_log_{ix}", table_name="decision_log")
    op.drop_table("decision_log")
