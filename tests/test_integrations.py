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
