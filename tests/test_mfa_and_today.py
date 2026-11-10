"""Decision 2026-11-09: staff and admin tokens must carry aal2 when REQUIRE_STAFF_MFA is on.
Comparison item 2: GET /api/today returns counts for the signed-in staff member."""
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_db
from app.main import create_app
from app.models import User
from tests.conftest import ADMIN_EMAIL, ALLOWED_ORIGIN, TEST_SECRET, auth


def token_with_aal(sub: str, email: str, aal: str | None) -> str:
    now = int(time.time())
    claims = {"sub": sub, "email": email, "aud": "authenticated", "iat": now, "exp": now + 3600,
              "role": "authenticated"}
    if aal:
        claims["aal"] = aal
    return jwt.encode(claims, TEST_SECRET, algorithm="HS256")


@pytest.fixture
def mfa_client(db):
    settings = Settings(_env_file=None, env="test", database_url="sqlite://", supabase_jwt_secret=TEST_SECRET,
                        cors_origins=ALLOWED_ORIGIN, bootstrap_admin_emails=ADMIN_EMAIL, require_staff_mfa=True)
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c


def test_staff_without_aal2_is_refused_when_mfa_required(mfa_client, db, staff_user):
    r = mfa_client.get("/api/contacts", headers=auth(token_with_aal(staff_user.id, staff_user.email, "aal1")))
    assert r.status_code == 403 and "authentication" in r.json()["detail"].lower()
    r = mfa_client.get("/api/contacts", headers=auth(token_with_aal(staff_user.id, staff_user.email, None)))
    assert r.status_code == 403
    r = mfa_client.get("/api/contacts", headers=auth(token_with_aal(staff_user.id, staff_user.email, "aal2")))
    assert r.status_code == 200


def test_me_still_works_without_aal2_so_the_ui_can_prompt_for_mfa(mfa_client, staff_user):
    r = mfa_client.get("/api/me", headers=auth(token_with_aal(staff_user.id, staff_user.email, "aal1")))
    assert r.status_code == 200 and r.json()["mfa_required"] is True
    r = mfa_client.get("/api/me", headers=auth(token_with_aal(staff_user.id, staff_user.email, "aal2")))
    assert r.json()["mfa_required"] is False


def test_mfa_off_by_default_accepts_aal1(client, staff_user):
    r = client.get("/api/contacts", headers=auth(token_with_aal(staff_user.id, staff_user.email, "aal1")))
    assert r.status_code == 200
    assert client.get("/api/me", headers=auth(token_with_aal(staff_user.id, staff_user.email, "aal1"))).json()["mfa_required"] is False


def test_today_counts(client, db, staff_headers, staff_user, pipelines):
    other = User(id=str(uuid.uuid4()), email="other@example.com", role="staff")
    db.add(other)
    db.commit()
    p = pipelines["property"]
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    for title, nxt, owner in (("Overdue", yesterday, None), ("Due today", today.isoformat(), None),
                              ("Later", tomorrow, None), ("Someone else's", yesterday, other.id)):
        body = {"title": title, "pipeline_id": p.id, "next_action_at": nxt}
        if owner:
            body["owner_id"] = owner
        assert client.post("/api/deals", json=body, headers=staff_headers).status_code == 201
    now = datetime.now(timezone.utc)
    # "Tour" is one minute ahead so it stays inside today (UTC) except in the last minute of the day.
    for subject, due, who in (("Call back", now - timedelta(hours=2), staff_user.id),
                              ("Tour", now + timedelta(minutes=1), staff_user.id),
                              ("Next week", now + timedelta(days=5), staff_user.id),
                              ("Theirs", now - timedelta(hours=1), other.id)):
        r = client.post("/api/activities", json={"subject": subject, "due_at": due.isoformat(), "assigned_to": who},
                        headers=staff_headers)
        assert r.status_code == 201

    t = client.get("/api/today", headers=staff_headers).json()
    assert t["date"] == today.isoformat()
    assert t["mine"] == {"deals_overdue": 1, "deals_due_today": 1, "activities_overdue": 1,
                         "activities_due_today": 1, "open_deals": 3}
    assert t["all"] == {"deals_overdue": 2, "deals_due_today": 1, "activities_overdue": 2,
                       "activities_due_today": 1, "open_deals": 4}
    assert [d["title"] for d in t["deals"]] == ["Overdue", "Due today"]
    assert [a["subject"] for a in t["activities"]] == ["Call back", "Tour"]
    assert "display_name" not in str(t)  # counts and titles only, never contact records
