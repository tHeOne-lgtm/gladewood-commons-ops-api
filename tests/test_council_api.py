from datetime import date, timedelta

from sqlalchemy import select

from app.models import AuditLog

SESSION = {"mode": "Major Decision", "door": "one-way",
           "brief": "DECISION: commit to the next property\nDEADLINE: 2026-12-15\nCONSTRAINT: no new lease before zoning is confirmed",
           "verdict_call": "Go with conditions", "verdict_text": "Commit only after three conditions clear.",
           "conditions": ["Paul: send the zoning question to an attorney", "Paul: confirm referral counts in writing"],
           "split": "Accounts and Ops agreed on fill speed as the risk; Relations assumed low owner burden.",
           "human_check": "An attorney reviews the lease and zoning."}


def test_routes_need_staff(client, pending_headers):
    assert client.get("/api/council").status_code == 401
    assert client.post("/api/council", json=SESSION, headers=pending_headers).status_code == 403


def test_create_list_get_and_decide(client, db, staff_headers, staff_user):
    pid = client.post("/api/properties", json={"address": "12 Example St"}, headers=staff_headers).json()["id"]
    r = client.post("/api/council", json={**SESSION, "property_id": pid, "commitment_ref": "cc-item-42"}, headers=staff_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created_by"] == staff_user.id and body["decision"] is None and body["conditions"] == SESSION["conditions"]
    sid = body["id"]
    assert [s["id"] for s in client.get(f"/api/council?property_id={pid}", headers=staff_headers).json()] == [sid]
    assert [s["id"] for s in client.get("/api/council?commitment_ref=cc-item-42", headers=staff_headers).json()] == [sid]
    assert client.get("/api/council?undecided=true", headers=staff_headers).json()[0]["id"] == sid
    assert client.get(f"/api/council/{sid}", headers=staff_headers).json()["verdict_call"] == "Go with conditions"
    assert client.get("/api/council/999", headers=staff_headers).status_code == 404

    due = (date.today() - timedelta(days=1)).isoformat()
    r = client.put(f"/api/council/{sid}/decision", json={"decision": "adopted with changes", "decision_reason": "Zoning first, then the lease.",
                                                        "review_date": due}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["decided_by"] == staff_user.id and r.json()["review_date"] == due
    assert client.get("/api/council?due=true", headers=staff_headers).json()[0]["id"] == sid
    assert client.get("/api/council?undecided=true", headers=staff_headers).json() == []
    # a decision is recorded once
    assert client.put(f"/api/council/{sid}/decision", json={"decision": "declined"}, headers=staff_headers).status_code == 409
    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "council_session")).all()]
    assert actions == ["council.create", "council.decide"]


def test_links_must_exist_and_text_is_guarded(client, staff_headers):
    # ensure_exists answers 422 for a link to a missing row (the CRM convention)
    assert client.post("/api/council", json={**SESSION, "property_id": 999}, headers=staff_headers).status_code == 422
    assert client.post("/api/council", json={**SESSION, "deal_id": 999}, headers=staff_headers).status_code == 422
    r = client.post("/api/council", json={**SESSION, "brief": "Resident with a disability asked about rent"}, headers=staff_headers)
    assert r.status_code == 422 and r.json()["detail"]["terms"] == ["disability"]
    r = client.post("/api/council", json={**SESSION, "conditions": ["ask about the support animal"]}, headers=staff_headers)
    assert r.status_code == 422 and r.json()["detail"]["terms"] == ["support animal"]
    assert client.post("/api/council", json={**SESSION, "door": "revolving"}, headers=staff_headers).status_code == 422
    assert client.post("/api/council", json={**SESSION, "verdict_call": "Maybe"}, headers=staff_headers).status_code == 422
    assert client.post("/api/council", json={**SESSION, "panel": "B"}, headers=staff_headers).status_code == 422
    sid = client.post("/api/council", json=SESSION, headers=staff_headers).json()["id"]
    r = client.put(f"/api/council/{sid}/decision", json={"decision": "declined", "decision_reason": "medical reasons"}, headers=staff_headers)
    assert r.status_code == 422
