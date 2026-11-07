import uuid

from sqlalchemy import select

from app.models import AuditLog, User
from tests.conftest import ADMIN_EMAIL, auth, make_token


def test_missing_token_is_401(client):
    r = client.get("/api/properties")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_bad_signature_is_401(client):
    r = client.get("/api/properties", headers=auth(make_token("x", "x@example.com", secret="wrong-secret-that-is-also-thirty-two-bytes")))
    assert r.status_code == 401


def test_expired_token_is_401(client):
    r = client.get("/api/properties", headers=auth(make_token("x", "x@example.com", exp_offset=-10)))
    assert r.status_code == 401


def test_wrong_audience_is_401(client):
    r = client.get("/api/properties", headers=auth(make_token("x", "x@example.com", aud="other")))
    assert r.status_code == 401


def test_unknown_user_gets_pending_role_and_403(client, db, pending_headers):
    r = client.get("/api/properties", headers=pending_headers)
    assert r.status_code == 403
    me = client.get("/api/me", headers=pending_headers).json()
    assert me["role"] == "pending"
    assert db.get(User, me["id"]) is not None
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "user.first_login")).all()
    assert len(audit) == 1 and audit[0].entity_id == me["id"]


def test_bootstrap_admin_email_gets_admin_role(client, admin_headers):
    me = client.get("/api/me", headers=admin_headers).json()
    assert me["role"] == "admin"
    assert me["email"] == ADMIN_EMAIL


def test_bootstrap_email_match_is_case_insensitive(client):
    headers = auth(make_token(str(uuid.uuid4()), ADMIN_EMAIL.upper()))
    assert client.get("/api/me", headers=headers).json()["role"] == "admin"


def test_staff_can_list(client, staff_headers):
    assert client.get("/api/properties", headers=staff_headers).status_code == 200


def test_existing_role_is_not_overwritten_by_bootstrap_list(client, db):
    user = User(id=str(uuid.uuid4()), email=ADMIN_EMAIL, role="staff")
    db.add(user)
    db.commit()
    me = client.get("/api/me", headers=auth(make_token(user.id, ADMIN_EMAIL))).json()
    assert me["role"] == "staff"
