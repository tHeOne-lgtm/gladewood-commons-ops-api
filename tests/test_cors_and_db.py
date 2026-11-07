from app.db import mask_database_url, normalize_database_url
from tests.conftest import ALLOWED_ORIGIN


def test_preflight_from_allowed_origin(client):
    r = client.options("/api/properties", headers={
        "Origin": ALLOWED_ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_preflight_from_other_origin_is_rejected(client):
    r = client.options("/api/properties", headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in r.headers


def test_normalize_strips_dashboard_comment_and_pgbouncer():
    raw = "# Connect via transaction pooler\\npostgresql://u:p%40ss@host:6543/db?pgbouncer=true&sslmode=require"
    assert normalize_database_url(raw) == "postgresql+psycopg://u:p%40ss@host:6543/db?sslmode=require"


def test_normalize_encodes_special_password_chars():
    assert normalize_database_url("postgres://user:p@ss#1/x@host/db") == "postgresql+psycopg://user:p%40ss%231%2Fx@host/db"


def test_normalize_leaves_sqlite_alone():
    assert normalize_database_url("sqlite://") == "sqlite://"


def test_mask_never_prints_password():
    assert "secret" not in mask_database_url("postgresql+psycopg://u:secret@host/db")
    assert "secret" not in mask_database_url("postgresql://u:secret")
    assert "secret" not in mask_database_url("secret")
