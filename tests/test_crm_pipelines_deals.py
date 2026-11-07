from sqlalchemy import select

from app.models import AuditLog, DealStageHistory


def _stage(p, name):
    return next(s for s in p.stages if s.name == name)


def test_default_pipelines_seeded(client, staff_headers, pipelines):
    got = client.get("/api/pipelines", headers=staff_headers).json()
    assert [p["slug"] for p in got] == ["property", "resident-inquiry", "referral-partner"]
    inquiry = next(p for p in got if p["slug"] == "resident-inquiry")
    assert inquiry["stages"][0]["name"] == "Inquiry" and inquiry["stages"][-2]["is_won"] and inquiry["stages"][-1]["is_lost"]


def test_deal_create_move_win_and_summary(client, db, staff_headers, staff_user, pipelines):
    p = pipelines["resident-inquiry"]
    contact = client.post("/api/contacts", json={"display_name": "Resident A", "kind": "prospect"}, headers=staff_headers).json()
    r = client.post("/api/deals", json={"title": "Inquiry: Resident A", "pipeline_id": p.id, "contact_id": contact["id"],
                                        "amount": "650.00"}, headers=staff_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["stage_name"] == "Inquiry" and d["status"] == "open" and d["owner_id"] == staff_user.id
    did = d["id"]

    r = client.post(f"/api/deals/{did}/move", json={"stage_id": _stage(p, "Deposit received").id}, headers=staff_headers)
    assert r.json()["stage_name"] == "Deposit received"
    s = client.get(f"/api/pipelines/{p.id}/summary", headers=staff_headers).json()
    assert s["open_count"] == 1 and s["open_amount"] == "650.00"
    assert next(x for x in s["stages"] if x["name"] == "Deposit received")["open_count"] == 1

    r = client.post(f"/api/deals/{did}/move", json={"stage_id": _stage(p, "Moved in").id}, headers=staff_headers)
    assert r.json()["status"] == "won" and r.json()["closed_at"]
    assert client.get("/api/deals", params={"pipeline_id": p.id}, headers=staff_headers).json() == []
    assert len(client.get("/api/deals", params={"status": "won"}, headers=staff_headers).json()) == 1
    s = client.get(f"/api/pipelines/{p.id}/summary", headers=staff_headers).json()
    assert s["won_count"] == 1 and s["open_count"] == 0

    assert db.scalar(select(DealStageHistory).where(DealStageHistory.deal_id == did)) is not None
    assert len(db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id == did)).all()) == 3
    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "deal")).all()]
    assert actions == ["deal.create", "deal.move", "deal.move"]


def test_deal_lost_with_reason_and_stage_validation(client, staff_headers, pipelines):
    p, other = pipelines["property"], pipelines["referral-partner"]
    d = client.post("/api/deals", json={"title": "123 Main", "pipeline_id": p.id}, headers=staff_headers).json()
    bad = client.post(f"/api/deals/{d['id']}/move", json={"stage_id": other.stages[0].id}, headers=staff_headers)
    assert bad.status_code == 422
    r = client.post(f"/api/deals/{d['id']}/move", json={"stage_id": _stage(p, "Passed").id, "lost_reason": "Zoning"},
                    headers=staff_headers)
    assert r.json()["status"] == "lost" and r.json()["lost_reason"] == "Zoning"
    assert client.post("/api/deals", json={"title": "x", "pipeline_id": 999}, headers=staff_headers).status_code == 404
    assert client.post("/api/deals", json={"title": "x", "pipeline_id": p.id, "property_id": 999},
                       headers=staff_headers).status_code == 422


def test_admin_creates_and_edits_pipeline_stage_in_use_protected(client, admin_headers, staff_headers, pipelines):
    body = {"name": "Vendors", "slug": "vendors", "stages": [{"name": "New"}, {"name": "Approved", "is_won": True}]}
    assert client.post("/api/pipelines", json=body, headers=staff_headers).status_code == 403
    r = client.post("/api/pipelines", json=body, headers=admin_headers)
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post("/api/pipelines", json=body, headers=admin_headers).status_code == 409
    client.post("/api/deals", json={"title": "Plumber", "pipeline_id": pid}, headers=staff_headers)
    r = client.put(f"/api/pipelines/{pid}", json={**body, "stages": [{"name": "Approved", "is_won": True}]},
                   headers=admin_headers)
    assert r.status_code == 409
    r = client.put(f"/api/pipelines/{pid}", json={**body, "stages": [{"name": "New"}, {"name": "Vetting"},
                                                                     {"name": "Approved", "is_won": True}]},
                   headers=admin_headers)
    assert [s["name"] for s in r.json()["stages"]] == ["New", "Vetting", "Approved"]


def test_deal_export_csv(client, staff_headers, pipelines):
    p = pipelines["property"]
    client.post("/api/deals", json={"title": "45 Oak St", "pipeline_id": p.id, "amount": "1800"}, headers=staff_headers)
    r = client.get("/api/deals/export", headers=staff_headers)
    assert "45 Oak St" in r.text and "Not sourced yet" in r.text
