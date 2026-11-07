"""CRM core: companies, contacts, tags, pipelines, stages, deals, stage history, activities, notes.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="other"),
        sa.Column("website", sa.Text, nullable=False, server_default=""),
        sa.Column("phone", sa.Text, nullable=False, server_default=""),
        sa.Column("email", sa.Text, nullable=False, server_default=""),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("extra", JSONB, nullable=False, server_default="{}"),
        sa.Column("legacy_ref", sa.String(64), unique=True),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    op.create_index("ix_companies_name", "companies", ["name"])
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("first_name", sa.Text, nullable=False, server_default=""),
        sa.Column("last_name", sa.Text, nullable=False, server_default=""),
        sa.Column("email", sa.Text, nullable=False, server_default=""),
        sa.Column("phone", sa.Text, nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False, server_default="other"),
        sa.Column("source", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="SET NULL")),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("extra", JSONB, nullable=False, server_default="{}"),
        sa.Column("legacy_ref", sa.String(64), unique=True),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    for col in ("display_name", "email", "kind", "status"):
        op.create_index(f"ix_contacts_{col}", "contacts", [col])
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
    )
    op.create_table(
        "record_tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("tag_id", sa.Integer, sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("entity", "entity_id", "tag_id"),
    )
    op.create_index("ix_record_tags_entity", "record_tags", ["entity"])
    op.create_index("ix_record_tags_entity_id", "record_tags", ["entity_id"])
    op.create_table(
        "pipelines",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "pipeline_stages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pipeline_id", sa.Integer, sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("probability", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_won", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_lost", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("pipeline_id", "name"),
    )
    op.create_index("ix_pipeline_stages_pipeline_id", "pipeline_stages", ["pipeline_id"])
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("pipeline_id", sa.Integer, sa.ForeignKey("pipelines.id"), nullable=False),
        sa.Column("stage_id", sa.Integer, sa.ForeignKey("pipeline_stages.id"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="SET NULL")),
        sa.Column("property_id", sa.Integer, sa.ForeignKey("properties.id", ondelete="SET NULL")),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("expected_close", sa.Date),
        sa.Column("lost_reason", sa.Text, nullable=False, server_default=""),
        sa.Column("owner_id", sa.String(64)),
        sa.Column("extra", JSONB, nullable=False, server_default="{}"),
        sa.Column("legacy_ref", sa.String(64), unique=True),
        sa.Column("closed_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    for col in ("pipeline_id", "stage_id", "status"):
        op.create_index(f"ix_deals_{col}", "deals", [col])
    op.create_table(
        "deal_stage_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_stage_id", sa.Integer),
        sa.Column("to_stage_id", sa.Integer, nullable=False),
        sa.Column("at", TS, nullable=False, server_default=NOW),
        sa.Column("actor_id", sa.String(64)),
    )
    op.create_index("ix_deal_stage_history_deal_id", "deal_stage_history", ["deal_id"])
    op.create_table(
        "activities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False, server_default="task"),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("due_at", TS),
        sa.Column("completed_at", TS),
        sa.Column("priority", sa.String(8), nullable=False, server_default="normal"),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id", ondelete="SET NULL")),
        sa.Column("deal_id", sa.Integer, sa.ForeignKey("deals.id", ondelete="SET NULL")),
        sa.Column("assigned_to", sa.String(64)),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    for col in ("kind", "due_at", "assigned_to"):
        op.create_index(f"ix_activities_{col}", "activities", [col])
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("author_id", sa.String(64)),
        sa.Column("author_email", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    op.create_index("ix_notes_entity", "notes", ["entity"])
    op.create_index("ix_notes_entity_id", "notes", ["entity_id"])

    # Seed the three Gladewood pipelines (idempotent by slug).
    from app.seed import DEFAULT_PIPELINES  # noqa: WPS433
    conn = op.get_bind()
    for spec in DEFAULT_PIPELINES:
        exists = conn.execute(sa.text("SELECT id FROM pipelines WHERE slug = :s"), {"s": spec["slug"]}).first()
        if exists:
            continue
        pid = conn.execute(
            sa.text("INSERT INTO pipelines (name, slug, description, position, is_active) "
                    "VALUES (:n, :s, :d, :p, true) RETURNING id"),
            {"n": spec["name"], "s": spec["slug"], "d": spec["description"], "p": spec["position"]},
        ).scalar_one()
        for i, s in enumerate(spec["stages"]):
            flag = s[2] if len(s) > 2 else ""
            conn.execute(
                sa.text("INSERT INTO pipeline_stages (pipeline_id, name, position, probability, is_won, is_lost) "
                        "VALUES (:pid, :n, :pos, :prob, :w, :l)"),
                {"pid": pid, "n": s[0], "pos": i, "prob": s[1], "w": flag == "won", "l": flag == "lost"},
            )


def downgrade() -> None:
    for t in ("notes", "activities", "deal_stage_history", "deals", "pipeline_stages", "pipelines",
              "record_tags", "tags", "contacts", "companies"):
        op.drop_table(t)
