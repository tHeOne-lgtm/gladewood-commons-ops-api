"""Baseline: legacy operations tables (idempotent) plus users and audit_log.

The five legacy tables were created by the pre-Alembic application with
CREATE TABLE IF NOT EXISTS, so this migration repeats those statements
unchanged to adopt an existing production database without altering it.
Downgrade removes only the tables this migration introduced.

Revision ID: 0001
Revises: None
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_SQL = """
CREATE TABLE IF NOT EXISTS properties (
    id SERIAL PRIMARY KEY,
    address TEXT NOT NULL DEFAULT '',
    area TEXT NOT NULL DEFAULT '',
    beds TEXT NOT NULL DEFAULT '',
    baths TEXT NOT NULL DEFAULT '',
    zoning_fit TEXT NOT NULL DEFAULT '',
    rent TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Not sourced yet',
    next_action TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS prospects (
    id SERIAL PRIMARY KEY,
    initials TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    room_type TEXT NOT NULL DEFAULT '',
    income_verified TEXT NOT NULL DEFAULT 'Not verified',
    deposit TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Inquiry',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS residents (
    id SERIAL PRIMARY KEY,
    initials TEXT NOT NULL DEFAULT '',
    room TEXT NOT NULL DEFAULT '',
    lease_start TEXT NOT NULL DEFAULT '',
    rent_status TEXT NOT NULL DEFAULT '',
    house_rules TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS conflict_log (
    id SERIAL PRIMARY KEY,
    entry_date TEXT NOT NULL DEFAULT '',
    house TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    safety_flag TEXT NOT NULL DEFAULT 'None',
    status TEXT NOT NULL DEFAULT '',
    resolution TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS financials (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

NEW_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '',
    role VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id VARCHAR(64),
    actor_email TEXT,
    action VARCHAR(64) NOT NULL,
    entity VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64),
    details JSONB
);
CREATE INDEX IF NOT EXISTS ix_audit_log_at ON audit_log (at);
CREATE INDEX IF NOT EXISTS ix_audit_log_actor_id ON audit_log (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_entity ON audit_log (entity);
"""


def upgrade() -> None:
    for stmt in (LEGACY_SQL + NEW_SQL).split(";"):
        if stmt.strip():
            op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS users")
