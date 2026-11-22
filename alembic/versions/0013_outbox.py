"""Outbound queue with approval and four dispatch gates, plus runtime flags (Atlas gap 2, 2026-11-22).

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_flags",
        sa.Column("key", sa.String(48), primary_key=True),
        sa.Column("value", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(64)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="SET NULL")),
        sa.Column("to_address", sa.Text, nullable=False, server_default=""),
        sa.Column("subject", sa.Text, nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("marketing", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("send_after", sa.DateTime(timezone=True)),
        sa.Column("allow_outside_window", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("in_reply_to_email_id", sa.Integer, sa.ForeignKey("emails.id", ondelete="SET NULL")),
        sa.Column("thread_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("hold_reason", sa.String(32)),
        sa.Column("lint", JSONB, nullable=False, server_default="{}"),
        sa.Column("gate_log", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("approved_by", sa.String(64)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("email_id", sa.Integer, sa.ForeignKey("emails.id", ondelete="SET NULL")),
        sa.Column("message_id", sa.Integer, sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for col in ("channel", "contact_id", "send_after", "thread_key", "status", "created_at"):
        op.create_index(f"ix_outbox_{col}", "outbox", [col])


def downgrade() -> None:
    for col in ("created_at", "status", "thread_key", "send_after", "contact_id", "channel"):
        op.drop_index(f"ix_outbox_{col}", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("system_flags")
