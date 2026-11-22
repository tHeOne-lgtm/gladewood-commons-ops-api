"""Advisory Council sessions mirrored into the CRM (2026-11-21).

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "council_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("panel", sa.String(1), nullable=False, server_default="A"),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("door", sa.String(8), nullable=False),
        sa.Column("brief", sa.Text, nullable=False),
        sa.Column("verdict_call", sa.String(20), nullable=False),
        sa.Column("verdict_text", sa.Text, nullable=False, server_default=""),
        sa.Column("conditions", JSONB, nullable=False, server_default="[]"),
        sa.Column("split", sa.Text, nullable=False, server_default=""),
        sa.Column("human_check", sa.Text, nullable=False, server_default=""),
        sa.Column("property_id", sa.Integer, sa.ForeignKey("properties.id", ondelete="SET NULL")),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="SET NULL")),
        sa.Column("commitment_ref", sa.String(64)),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(24)),
        sa.Column("decision_reason", sa.String(400), nullable=False, server_default=""),
        sa.Column("review_date", sa.Date),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.String(64)),
    )
    for col in ("held_at", "property_id", "deal_id", "commitment_ref", "review_date"):
        op.create_index(f"ix_council_sessions_{col}", "council_sessions", [col])


def downgrade() -> None:
    for col in ("review_date", "commitment_ref", "deal_id", "property_id", "held_at"):
        op.drop_index(f"ix_council_sessions_{col}", table_name="council_sessions")
    op.drop_table("council_sessions")
