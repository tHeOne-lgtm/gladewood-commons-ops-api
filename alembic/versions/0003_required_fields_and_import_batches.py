"""Comparison items 1 and 4 (2026-11-09): next_action_at on deals with the open-deal rule,
and import_batches with a batch id on contacts, companies, and deals.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
OPEN_DEAL_RULE = "status <> 'open' OR (owner_id IS NOT NULL AND next_action_at IS NOT NULL)"


def upgrade() -> None:
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("filename", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("created_by", sa.String(64)),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("undone_at", TS),
        sa.Column("undone_by", sa.String(64)),
    )
    for table in ("contacts", "companies", "deals"):
        op.add_column(table, sa.Column("import_batch_id", sa.Integer,
                                       sa.ForeignKey("import_batches.id", ondelete="SET NULL")))
        op.create_index(f"ix_{table}_import_batch_id", table, ["import_batch_id"])

    op.add_column("deals", sa.Column("next_action_at", sa.Date))
    op.create_index("ix_deals_next_action_at", "deals", ["next_action_at"])
    # Existing open deals get today as their next action so the rule can be enforced at once.
    # Open deals with no owner are left for the rule to refuse: none exist before the legacy
    # migration, and the migration now requires an actor.
    op.execute("UPDATE deals SET next_action_at = CURRENT_DATE WHERE status = 'open' AND next_action_at IS NULL")
    op.create_check_constraint("ck_deals_open_has_owner_and_next_action", "deals", OPEN_DEAL_RULE)


def downgrade() -> None:
    op.drop_constraint("ck_deals_open_has_owner_and_next_action", "deals", type_="check")
    op.drop_index("ix_deals_next_action_at", table_name="deals")
    op.drop_column("deals", "next_action_at")
    for table in ("contacts", "companies", "deals"):
        op.drop_index(f"ix_{table}_import_batch_id", table_name=table)
        op.drop_column(table, "import_batch_id")
    op.drop_table("import_batches")
