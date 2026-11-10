"""Comparison item 1: an open deal must carry an owner, a status, and a next-action date."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Deal


def _stage(p, name):
    return next(s for s in p.stages if s.name == name)


def test_open_deal_without_next_action_is_refused(client, staff_headers, pipelines):
    p = pipelines["resident-inquiry"]
    r = client.post("/api/deals", json={"title": "Inquiry: Resident A", "pipeline_id": p.id}, headers=staff_headers)
    assert r.status_code == 422
    assert "next_action_at" in r.json()["detail"]


def test_open_deal_with_next_action_and_default_owner(client, staff_headers, staff_user, pipelines):
    p = pipelines["resident-inquiry"]
    today = date.today().isoformat()
    r = client.post("/api/deals", json={"title": "Inquiry: Resident A", "pipeline_id": p.id, "next_action_at": today},
                    headers=staff_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["owner_id"] == staff_user.id and d["next_action_at"] == today and d["status"] == "open"


def test_closed_deal_needs_no_next_action_and_reopen_requires_one(client, staff_headers, pipelines):
    p = pipelines["property"]
    today = date.today().isoformat()
    d = client.post("/api/deals", json={"title": "12 Pine St", "pipeline_id": p.id, "next_action_at": today},
                    headers=staff_headers).json()
    r = client.post(f"/api/deals/{d['id']}/move", json={"stage_id": _stage(p, "Passed").id, "lost_reason": "Zoning"},
                    headers=staff_headers)
    assert r.status_code == 200 and r.json()["status"] == "lost" and r.json()["next_action_at"] is None

    # Reopening with no next action is refused; with one it works.
    r = client.post(f"/api/deals/{d['id']}/move", json={"stage_id": _stage(p, "Touring").id}, headers=staff_headers)
    assert r.status_code == 422 and "next_action_at" in r.json()["detail"]
    nxt = (date.today() + timedelta(days=3)).isoformat()
    r = client.post(f"/api/deals/{d['id']}/move", json={"stage_id": _stage(p, "Touring").id, "next_action_at": nxt},
                    headers=staff_headers)
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["next_action_at"] == nxt


def test_update_cannot_clear_next_action_on_open_deal(client, staff_headers, pipelines):
    p = pipelines["property"]
    today = date.today().isoformat()
    d = client.post("/api/deals", json={"title": "12 Pine St", "pipeline_id": p.id, "next_action_at": today},
                    headers=staff_headers).json()
    r = client.put(f"/api/deals/{d['id']}", json={"title": "12 Pine St", "pipeline_id": p.id}, headers=staff_headers)
    assert r.status_code == 422 and "next_action_at" in r.json()["detail"]


def test_database_constraint_backs_the_rule(db, pipelines):
    p = pipelines["property"]
    db.add(Deal(pipeline_id=p.id, stage_id=p.stages[0].id, title="x", status="open", owner_id=None,
                next_action_at=date.today()))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.add(Deal(pipeline_id=p.id, stage_id=p.stages[0].id, title="x", status="open", owner_id="u1",
                next_action_at=None))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.add(Deal(pipeline_id=p.id, stage_id=p.stages[-1].id, title="x", status="lost", owner_id=None,
                next_action_at=None))
    db.flush()
    assert db.scalar(select(Deal)) is not None
