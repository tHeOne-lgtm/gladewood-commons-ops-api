"""WhatsApp and SMS messages.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("channel", sa.String(16), nullable=False, server_default="whatsapp"),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="SET NULL")),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("provider", sa.String(16), nullable=False, server_default="twilio"),
        sa.Column("provider_sid", sa.String(64), unique=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="received"),
        sa.Column("error_code", sa.String(16)),
        sa.Column("media_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_by", sa.String(64)),
        sa.Column("read_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("direction IN ('in','out')", name="ck_messages_direction"),
    )
    for col in ("channel", "contact_id", "phone", "created_at"):
        op.create_index(f"ix_messages_{col}", "messages", [col])


def downgrade() -> None:
    op.drop_table("messages")
