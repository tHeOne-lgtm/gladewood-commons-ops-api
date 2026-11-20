"""Saved views for list screens.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_views",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entity", sa.String(16), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("filters", JSONB, nullable=False, server_default="{}"),
        sa.Column("sort", sa.String(40), nullable=False, server_default=""),
        sa.Column("columns", JSONB, nullable=False, server_default="[]"),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("shared", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_saved_views_entity", "saved_views", ["entity"])
    op.create_index("ix_saved_views_owner_id", "saved_views", ["owner_id"])


def downgrade() -> None:
    op.drop_table("saved_views")
