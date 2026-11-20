from sqlalchemy import select

from app.models import Company

KEY = {"X-Api-Key": "cc-test-key-0123456789abcdef0123456789"}
PUSH = {"data": [{"Account_Name": "Bridge Agency", "Description": "Case management | CC: Engaged · last touch 2026-11-18", "Phone": "(423) 555-0100"},
                 {"Account_Name": "Erlanger Case Mgmt", "Description": "CC: Contacted"}],
        "duplicate_check_fields": ["Account_Name"]}


def test_key_required_and_scoped(client, staff_headers, app):
    assert client.get("/api/integrations/bigin-accounts").status_code == 401
    assert client.get("/api/integrations/bigin-accounts", headers={"X-Api-Key": "wrong"}).status_code == 401
    assert client.get("/api/integrations/bigin-accounts", headers=staff_headers).status_code == 401  # a staff token is not the key
    assert client.get("/api/contacts", headers=KEY).status_code == 401  # the key opens nothing else
    app.state.settings.integration_api_key = ""
    assert client.get("/api/integrations/bigin-accounts", headers=KEY).status_code == 503
    app.state.settings.integration_api_key = KEY["X-Api-Key"]


def test_upsert_then_list_in_bigin_shape(client, db, staff_headers):
    existing = client.post("/api/companies", json={"name": "erlanger case mgmt", "kind": "hospital", "phone": "423-000-0000", "notes": "staff note stays"}, headers=staff_headers).json()
    owner = client.post("/api/companies", json={"name": "Pine Street Holdings", "kind": "property_owner"}, headers=staff_headers).json()
    r = client.post("/api/integrations/bigin-accounts/upsert", json=PUSH, headers=KEY)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1 and r.json()["updated"] == 1
    assert [x["action"] for x in r.json()["data"]] == ["insert", "update"]
    bridge = db.scalar(select(Company).where(Company.name == "Bridge Agency"))
    assert bridge.kind == "agency" and bridge.phone == "+14235550100" and bridge.extra["cc_description"].startswith("Case management | CC: Engaged")
    erl = db.get(Company, existing["id"])
    db.refresh(erl)
    assert erl.notes == "staff note stays" and erl.phone == "423-000-0000" and erl.extra["cc_description"] == "CC: Contacted"
    # same push again changes nothing
    r = client.post("/api/integrations/bigin-accounts/upsert", json=PUSH, headers=KEY)
    assert r.json()["created"] == 0 and r.json()["updated"] == 0
    out = client.get("/api/integrations/bigin-accounts", headers=KEY).json()
    names = [a["Account_Name"] for a in out["data"]]
    assert names == ["Bridge Agency", "erlanger case mgmt"] and owner["name"] not in names  # property owners stay out
    row = out["data"][0]
    assert row["id"] == str(bridge.id) and row["Phone"] == "+14235550100" and row["Description"].startswith("Case management") and row["Modified_Time"]
    assert out["info"] == {"count": 2, "more_records": False}
    r = client.post("/api/integrations/bigin-accounts/upsert", json={"data": []}, headers=KEY)
    assert r.status_code == 422


def test_stuck_deals_notes_and_keyword_scan(client, db, staff_headers, pipelines):
    from datetime import datetime, timedelta, timezone
    p = pipelines["property"]
    quiet = client.post("/api/deals", json={"title": "12 Pine St", "pipeline_id": p.id, "next_action_at": "2026-12-01"}, headers=staff_headers).json()
    fresh = client.post("/api/deals", json={"title": "9 Oak Ave", "pipeline_id": p.id, "next_action_at": "2026-12-01"}, headers=staff_headers).json()
    from app.models import Deal
    db.get(Deal, quiet["id"]).created_at = datetime.now(timezone.utc) - timedelta(days=20)
    db.commit()
    out = client.get("/api/integrations/stuck-deals?days=14", headers=KEY).json()
    assert out["count"] == 1 and out["deals"][0]["deal_id"] == quiet["id"] and out["deals"][0]["days_quiet"] >= 20
    assert out["deals"][0]["pipeline"] == "property"
    # a note on the quiet deal counts as a touch
    r = client.post("/api/integrations/notes", json={"entity": "deal", "entity_id": quiet["id"], "body": "Draft: follow up on the master lease terms."}, headers=KEY)
    assert r.status_code == 201, r.text
    assert client.get("/api/integrations/stuck-deals?days=14", headers=KEY).json()["count"] == 0
    tl = client.get(f"/api/timeline?entity=deal&entity_id={quiet['id']}", headers=staff_headers).json()
    assert any(i["type"] == "note" and i["actor"] == "command-center:n8n" for i in tl)
    assert client.post("/api/integrations/notes", json={"entity": "deal", "entity_id": fresh["id"], "body": "needs supervision"}, headers=KEY).status_code == 422
    assert client.post("/api/integrations/notes", json={"entity": "deal", "entity_id": 999, "body": "x"}, headers=KEY).status_code == 404
    # keyword scan reports counts only
    client.post("/api/notes", json={"entity": "deal", "entity_id": fresh["id"], "body": "Owner prefers a longer term"}, headers=staff_headers)
    client.put(f"/api/deals/{fresh['id']}", json={**{k: v for k, v in fresh.items() if k in ("title", "pipeline_id", "stage_id", "contact_id", "company_id", "property_id", "amount", "expected_close", "next_action_at", "owner_id", "extra")}, "lost_reason": "wheelchair"}, headers=staff_headers)
    scan = client.get("/api/integrations/keyword-scan", headers=KEY).json()
    assert scan["fields"]["notes"]["scanned"] == 2 and scan["fields"]["notes"]["flagged"] == 0
    assert scan["fields"]["deal_lost_reasons"] == {"scanned": 1, "flagged": 1} and scan["flagged_total"] == 1
    assert "wheelchair" not in str(scan)
