"""Portal v1: six roles, rooms, tenancies, documents, maintenance requests and comments, access grants.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TS = lambda: sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))  # noqa: E731
TU = lambda: sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))  # noqa: E731


def upgrade() -> None:
    # role names (decision 2026-11-20)
    op.execute("UPDATE users SET role = 'owner' WHERE role = 'admin'")
    op.execute("UPDATE users SET role = 'ops_staff' WHERE role = 'staff'")
    op.execute("UPDATE users SET role = 'resident' WHERE role = 'tenant'")
    op.add_column("contacts", sa.Column("portal_user_id", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_contacts_portal_user_id", "contacts", ["portal_user_id"])
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("property_id", sa.Integer, sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("room_type", sa.String(16), nullable=False, server_default="private"),
        sa.Column("monthly_rent", sa.Numeric(10, 2)),
        sa.Column("status", sa.String(16), nullable=False, server_default="available"),
        TS(), TU(),
    )
    op.create_index("ix_rooms_property_id", "rooms", ["property_id"])
    op.create_table(
        "tenancies",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("property_id", sa.Integer, sa.ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("room_id", sa.Integer, sa.ForeignKey("rooms.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("rent_amount", sa.Numeric(10, 2)),
        sa.Column("deposit_amount", sa.Numeric(10, 2)),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        TS(), TU(),
    )
    for col in ("contact_id", "property_id", "status"):
        op.create_index(f"ix_tenancies_{col}", "tenancies", [col])
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenancy_id", sa.Integer, sa.ForeignKey("tenancies.id", ondelete="CASCADE")),
        sa.Column("contact_id", sa.Integer, sa.ForeignKey("contacts.id", ondelete="SET NULL")),
        sa.Column("property_id", sa.Integer, sa.ForeignKey("properties.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("category", sa.String(24), nullable=False, server_default="other"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending_upload"),
        sa.Column("storage_key", sa.Text, nullable=False, server_default=""),
        sa.Column("content_type", sa.String(100), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer),
        sa.Column("drive_file_id", sa.String(128)),
        sa.Column("shared_with_resident", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("shared_with_case_manager", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("uploaded_by", sa.String(64)),
        sa.Column("uploaded_role", sa.String(16), nullable=False, server_default=""),
        TS(), TU(),
    )
    op.create_index("ix_documents_tenancy_id", "documents", ["tenancy_id"])
    op.create_index("ix_documents_contact_id", "documents", ["contact_id"])
    op.create_table(
        "maintenance_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenancy_id", sa.Integer, sa.ForeignKey("tenancies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submitted_by", sa.String(64)),
        sa.Column("category", sa.String(24), nullable=False, server_default="other"),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_screening"),
        sa.Column("screening_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("screening_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("screened_at", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.String(8), nullable=False, server_default="normal"),
        sa.Column("assigned_to", sa.String(64)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        TS(), TU(),
    )
    for col in ("tenancy_id", "status", "created_at"):
        op.create_index(f"ix_maintenance_requests_{col}", "maintenance_requests", [col])
    op.create_table(
        "maintenance_comments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("request_id", sa.Integer, sa.ForeignKey("maintenance_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.String(64)),
        sa.Column("author_role", sa.String(16), nullable=False, server_default=""),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("screening_status", sa.String(16), nullable=False, server_default="clear"),
        TS(),
    )
    op.create_index("ix_maintenance_comments_request_id", "maintenance_comments", ["request_id"])
    op.create_table(
        "portal_access_grants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenancy_id", sa.Integer, sa.ForeignKey("tenancies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("case_manager_email", sa.Text, nullable=False),
        sa.Column("case_manager_user_id", sa.String(64)),
        sa.Column("scopes", JSONB, nullable=False, server_default="[]"),
        sa.Column("granted_by", sa.String(64)),
        sa.Column("granted_by_role", sa.String(16), nullable=False, server_default="resident"),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.String(64)),
    )
    for col in ("tenancy_id", "case_manager_email", "case_manager_user_id"):
        op.create_index(f"ix_portal_access_grants_{col}", "portal_access_grants", [col])


def downgrade() -> None:
    for name in ("portal_access_grants", "maintenance_comments", "maintenance_requests", "documents", "tenancies", "rooms"):
        op.drop_table(name)
    op.drop_constraint("uq_contacts_portal_user_id", "contacts", type_="unique")
    op.drop_column("contacts", "portal_user_id")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'owner'")
    op.execute("UPDATE users SET role = 'staff' WHERE role IN ('ops_staff', 'management', 'audit')")
    op.execute("UPDATE users SET role = 'tenant' WHERE role = 'resident'")
