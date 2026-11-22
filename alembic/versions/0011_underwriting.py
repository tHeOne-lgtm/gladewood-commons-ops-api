"""Underwriting per property and its settings (Prospect Hub port, 2026-11-21).

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "underwritings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("property_id", sa.Integer, sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False, server_default="Found"),
        sa.Column("deal_type", sa.String(8), nullable=False, server_default="lease"),
        sa.Column("private_rooms", sa.Integer),
        sa.Column("shared_rooms", sa.Integer),
        sa.Column("bedrooms", sa.Integer),
        sa.Column("lease_cost", sa.Numeric(10, 2)),
        sa.Column("sale_price", sa.Numeric(12, 2)),
        sa.Column("utilities", sa.Numeric(10, 2)),
        sa.Column("inputs", JSONB, nullable=False, server_default="{}"),
        sa.Column("market", JSONB, nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_underwritings_property_id", "underwritings", ["property_id"])
    op.create_index("ix_underwritings_property_id", "underwritings", ["property_id"])
    op.create_index("ix_underwritings_stage", "underwritings", ["stage"])
    op.create_table(
        "underwriting_settings",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("value", sa.Numeric(14, 4), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("underwriting_settings")
    op.drop_index("ix_underwritings_stage", table_name="underwritings")
    op.drop_index("ix_underwritings_property_id", table_name="underwritings")
    op.drop_constraint("uq_underwritings_property_id", "underwritings", type_="unique")
    op.drop_table("underwritings")
