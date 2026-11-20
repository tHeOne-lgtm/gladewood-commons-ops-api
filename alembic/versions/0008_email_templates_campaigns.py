"""Email templates, campaigns, and the outbound email log; default templates seeded.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="transactional"),
        sa.Column("audience", sa.String(16), nullable=False, server_default="any"),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body_text", sa.Text, nullable=False),
        sa.Column("body_html", sa.Text, nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("template_id", sa.Integer, sa.ForeignKey("email_templates.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("segment", JSONB, nullable=False, server_default="{}"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_campaigns_status", "campaigns", ["status"])
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="SET NULL")),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id", ondelete="CASCADE")),
        sa.Column("template_id", sa.Integer, sa.ForeignKey("email_templates.id", ondelete="SET NULL")),
        sa.Column("to_email", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False, server_default=""),
        sa.Column("body_text", sa.Text, nullable=False, server_default=""),
        sa.Column("provider", sa.String(16), nullable=False, server_default="log"),
        sa.Column("provider_message_id", sa.String(128), unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("skip_reason", sa.String(32)),
        sa.Column("error", sa.Text),
        sa.Column("sent_by", sa.String(64)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("clicked_at", sa.DateTime(timezone=True)),
        sa.Column("bounced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for col in ("contact_id", "campaign_id", "to_email", "status", "created_at"):
        op.create_index(f"ix_emails_{col}", "emails", [col])
    from app.seed import seed_default_email_templates  # noqa: WPS433
    session = Session(bind=op.get_bind())
    seed_default_email_templates(session)
    session.flush()


def downgrade() -> None:
    op.drop_table("emails")
    op.drop_table("campaigns")
    op.drop_table("email_templates")
