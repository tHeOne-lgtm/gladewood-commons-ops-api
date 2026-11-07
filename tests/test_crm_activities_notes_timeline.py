from datetime import datetime, timedelta, timezone


def test_activity_lifecycle_and_filters(client, staff_headers, staff_user, pipelines):
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    a = client.post("/api/activities", json={"subject": "Call landlord", "kind": "call", "due_at": past},
                    headers=staff_headers).json()
    b = client.post("/api/activities", json={"subject": "Tour", "kind": "event", "due_at": future},
                    headers=staff_headers).json()
    assert a["assigned_to"] == staff_user.id
    assert [x["id"] for x in client.get("/api/activities", params={"overdue": True}, headers=staff_headers).json()] == [a["id"]]
    assert len(client.get("/api/activities", params={"mine": True}, headers=staff_headers).json()) == 2

    r = client.post(f"/api/activities/{a['id']}/complete", headers=staff_headers)
    assert r.json()["completed_at"]
    assert [x["id"] for x in client.get("/api/activities", headers=staff_headers).json()] == [b["id"]]
    r = client.post(f"/api/activities/{a['id']}/complete", params={"undo": True}, headers=staff_headers)
    assert r.json()["completed_at"] is None
    assert client.post("/api/activities", json={"subject": "x", "deal_id": 999}, headers=staff_headers).status_code == 422


def test_notes_author_protection_and_timeline(client, db, admin_headers, staff_headers, pipelines):
    p = pipelines["property"]
    deal = client.post("/api/deals", json={"title": "9 Elm", "pipeline_id": p.id}, headers=staff_headers).json()
    n = client.post("/api/notes", json={"entity": "deal", "entity_id": deal["id"], "body": "Owner open to 2 year term"},
                    headers=staff_headers)
    assert n.status_code == 201
    nid = n.json()["id"]
    assert client.put(f"/api/notes/{nid}", json={"body": "edit"}, headers=admin_headers).status_code == 200
    assert client.post("/api/notes", json={"entity": "deal", "entity_id": 999, "body": "x"}, headers=staff_headers).status_code == 422

    client.post("/api/activities", json={"subject": "Send LOI", "deal_id": deal["id"]}, headers=staff_headers)
    client.post(f"/api/deals/{deal['id']}/move", json={"stage_id": p.stages[1].id}, headers=staff_headers)

    tl = client.get("/api/timeline", params={"entity": "deal", "entity_id": deal["id"]}, headers=staff_headers).json()
    types = sorted(set(i["type"] for i in tl))
    assert types == ["activity.task", "deal.create", "deal.move", "note", "note.create", "note.update", "stage"]
    assert any("Not sourced yet → Contacted" == i["summary"] for i in tl)
    assert tl == sorted(tl, key=lambda i: i["at"], reverse=True)
    assert client.get("/api/timeline", params={"entity": "bogus", "entity_id": 1}, headers=staff_headers).status_code == 422
