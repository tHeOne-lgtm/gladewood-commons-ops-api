import io


def test_company_and_contact_lifecycle(client, staff_headers):
    c = client.post("/api/companies", json={"name": "Erlanger Case Mgmt", "kind": "hospital",
                                            "email": "CM@Example.org"}, headers=staff_headers)
    assert c.status_code == 201 and c.json()["email"] == "cm@example.org"
    cid = c.json()["id"]

    r = client.post("/api/contacts", json={"display_name": "Case Manager A", "kind": "case_manager",
                                           "company_id": cid, "extra": {"caseload": 12}}, headers=staff_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["company_name"] == "Erlanger Case Mgmt" and body["extra"] == {"caseload": 12} and body["tags"] == []
    rid = body["id"]

    r = client.put(f"/api/contacts/{rid}/tags", json={"tags": ["referral", " voucher ", "referral"]}, headers=staff_headers)
    assert r.json()["tags"] == ["referral", "voucher"]

    assert [x["id"] for x in client.get("/api/contacts", params={"tag": "voucher"}, headers=staff_headers).json()] == [rid]
    assert client.get("/api/contacts", params={"q": "manager a"}, headers=staff_headers).json()[0]["id"] == rid
    assert client.get("/api/contacts", params={"kind": "resident"}, headers=staff_headers).json() == []

    r = client.put(f"/api/contacts/{rid}", json={**body, "status": "archived"}, headers=staff_headers)
    assert r.status_code == 200
    assert client.get("/api/contacts", headers=staff_headers).json() == []
    assert len(client.get("/api/contacts", params={"status": "all"}, headers=staff_headers).json()) == 1

    assert client.delete(f"/api/contacts/{rid}", headers=staff_headers).json() == {"deleted": rid}
    assert client.get(f"/api/contacts/{rid}", headers=staff_headers).status_code == 404


def test_contact_rejects_unknown_company_and_bad_extra(client, staff_headers):
    r = client.post("/api/contacts", json={"display_name": "X", "company_id": 999}, headers=staff_headers)
    assert r.status_code == 422
    r = client.post("/api/contacts", json={"display_name": "X", "extra": {"Bad Key": 1}}, headers=staff_headers)
    assert r.status_code == 422
    r = client.post("/api/contacts", json={"display_name": "X", "extra": {f"k{i}": i for i in range(31)}},
                    headers=staff_headers)
    assert r.status_code == 422


def test_duplicates_by_email_phone_name(client, staff_headers):
    for payload in ({"display_name": "Sam Lee", "email": "sam@example.com"},
                    {"display_name": "sam lee", "email": "SAM@example.com", "phone": "(423) 555-0100"},
                    {"display_name": "Other", "phone": "423-555-0100"}):
        client.post("/api/contacts", json=payload, headers=staff_headers)
    groups = client.get("/api/contacts/duplicates", headers=staff_headers).json()
    reasons = sorted((g["reason"], len(g["contact_ids"])) for g in groups)
    assert reasons == [("email", 2), ("name", 2), ("phone", 2)]


def test_csv_export_and_import_roundtrip(client, staff_headers):
    client.post("/api/companies", json={"name": "Acme Realty", "kind": "brokerage"}, headers=staff_headers)
    exp = client.get("/api/companies/export", headers=staff_headers)
    assert exp.status_code == 200 and exp.headers["content-type"].startswith("text/csv")
    assert "Acme Realty" in exp.text

    csv_text = "display_name,email,kind,tags,company_id\nBroker B,b@example.com,broker,hot|q4,\n,bad,other,,\n"
    r = client.post("/api/contacts/import", files={"file": ("c.csv", io.BytesIO(csv_text.encode()), "text/csv")},
                    headers=staff_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1 and len(body["errors"]) == 1 and body["errors"][0]["row"] == 3
    got = client.get("/api/contacts", headers=staff_headers).json()
    assert got[0]["display_name"] == "Broker B" and got[0]["tags"] == ["hot", "q4"]
    exp = client.get("/api/contacts/export", headers=staff_headers)
    assert "hot|q4" in exp.text


def test_pending_user_blocked_from_crm(client, pending_headers):
    assert client.get("/api/contacts", headers=pending_headers).status_code == 403
    assert client.get("/api/pipelines", headers=pending_headers).status_code == 403
