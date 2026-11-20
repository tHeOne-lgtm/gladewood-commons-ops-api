"""Property owner and manager pipeline: new name and stages; referral partner MOA stages.

Idempotent: renames Touring to Toured, adds missing stages, refreshes positions and flags by
stage name. Existing deals keep their stage ids.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
from sqlalchemy.orm import Session

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.seed import sync_default_pipelines  # noqa: WPS433
    session = Session(bind=op.get_bind())
    sync_default_pipelines(session)
    session.flush()


def downgrade() -> None:
    # Stage additions and renames are left in place; they are data, not schema.
    pass
