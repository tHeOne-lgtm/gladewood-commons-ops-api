"""automation_runs table; resident inquiry gains Tour scheduled and Toured stages.

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op
from sqlalchemy.orm import Session

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("rule", sa.String(48), nullable=False),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("details", JSONB),
    )
    op.create_index("ix_automation_runs_rule", "automation_runs", ["rule"])
    op.create_index("ix_automation_runs_entity_id", "automation_runs", ["entity_id"])
    op.create_index("ix_automation_runs_ran_at", "automation_runs", ["ran_at"])
    from app.seed import sync_default_pipelines  # noqa: WPS433
    session = Session(bind=op.get_bind())
    sync_default_pipelines(session)
    session.flush()


def downgrade() -> None:
    op.drop_table("automation_runs")
