import io
import json

from sqlalchemy import select

from app.bigin_import import guess_company_kind, parse_rows
from app.models import Company, Consent, Contact

ACCOUNTS_CSV = """Account Id,Account Name,Phone,Website,Billing City,Description,Tag
7600294000000698026,Chattanooga Housing Authority,(423) 752-4893,,Chattanooga,Added from the Gladewood Prospect Hub,
7600294000000698031,VA Tennessee Valley - Chattanooga Clinic,(423) 855-6219,https://va.example.test,,Referral desk opens 8 am,
"""
CONTACTS_JSON = {"data": [
    {"id": "7600294000000717158", "First_Name": "Jo", "Last_Name": "Park", "Full_Name": "Jo Park", "Email": "Jo.Park@cha.test",
     "Phone": None, "Mobile": "423-555-0100", "Title": "Case Manager", "Description": "Direct line: (423) 555-0100",
     "Account_Name": {"name": "Chattanooga Housing Authority", "id": "7600294000000698026"}, "Email_Opt_Out": False, "Tag": []},
    {"id": "7600294000000769005", "Full_Name": "forwarding-noreply", "Email": "forwarding-noreply@google.com", "Account_Name": None, "Tag": []},
    {"id": "7600294000000717157", "Full_Name": "Ana Ruiz", "First_Name": "Ana", "Last_Name": "Ruiz", "Email": "ana@clinic.test",
     "Title": "Coordinator", "Account_Name": {"name": "VA Tennessee Valley - Chattanooga Clinic", "id": "7600294000000698031"},
     "Email_Opt_Out": True, "Tag": [{"name": "Hot"}]},
    {"id": "7600294000000717100", "Full_Name": "", "Email": "", "Tag": []},
]}


def _files():
    return {"accounts": ("accounts.csv", io.BytesIO(ACCOUNTS_CSV.encode()), "text/csv"),
            "contacts": ("contacts.json", io.BytesIO(json.dumps(CONTACTS_JSON).encode()), "application/json")}


def test_parse_and_kind_guess():
    assert parse_rows(ACCOUNTS_CSV.encode())[0]["Account Name"] == "Chattanooga Housing Authority"
    assert len(parse_rows(json.dumps(CONTACTS_JSON).encode())) == 4
    assert guess_company_kind("Chattanooga Housing Authority") == "agency"
    assert guess_company_kind("Erlanger Hospital") == "hospital"
    assert guess_company_kind("Smith Realty") == "brokerage"
    assert guess_company_kind("Acme") == "other"


def test_bigin_import_dry_run_then_apply_match_and_undo(client, db, admin_headers, staff_headers):
    client.get("/api/me", headers=admin_headers)
    assert client.post("/api/imports/bigin", files=_files(), headers=staff_headers).status_code == 403
    r = client.post("/api/imports/bigin", files=_files(), headers=admin_headers)
    assert r.status_code == 200, r.text
    dry = r.json()
    assert dry["dry_run"] and dry["batch_id"] is None
    assert dry["companies"] == {"created": 2} and dry["contacts"] == {"created": 2, "opted_out": 1}
    assert [(s["module"], s["reason"]) for s in dry["skipped"]] == [("contacts", "system_address"), ("contacts", "no_name")]
    assert db.scalar(select(Company)) is None  # nothing written
    # an existing company by name is matched, blanks filled, nothing overwritten
    existing = client.post("/api/companies", json={"name": "chattanooga housing authority", "kind": "agency", "phone": "423-000-0000"}, headers=staff_headers).json()
    r = client.post("/api/imports/bigin?dry_run=false", files=_files(), headers=admin_headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["batch_id"] and out["companies"] == {"created": 1, "matched": 1, "updated": 1}
    cha = db.get(Company, existing["id"])
    assert cha.phone == "423-000-0000" and cha.legacy_ref == "bigin:account:7600294000000698026" and cha.address == "Chattanooga"
    va = db.scalar(select(Company).where(Company.legacy_ref == "bigin:account:7600294000000698031"))
    assert va.kind == "hospital" and va.notes == "Referral desk opens 8 am" and va.website == "https://va.example.test"
    jo = db.scalar(select(Contact).where(Contact.legacy_ref == "bigin:contact:7600294000000717158"))
    assert jo.email == "jo.park@cha.test" and jo.phone == "+14235550100" and jo.company_id == cha.id and jo.kind == "case_manager"
    assert jo.extra["title"] == "Case Manager" and jo.notes.startswith("Direct line")
    assert client.get(f"/api/contacts/{jo.id}", headers=staff_headers).json()["tags"] == ["src-bigin"]
    ana = db.scalar(select(Contact).where(Contact.email == "ana@clinic.test"))
    assert ana.company_id == va.id and sorted(client.get(f"/api/contacts/{ana.id}", headers=staff_headers).json()["tags"]) == ["Hot", "src-bigin"]
    assert db.scalar(select(Consent).where(Consent.contact_id == ana.id)).withdrawn_at is not None
    assert db.scalar(select(Contact).where(Contact.email == "forwarding-noreply@google.com")) is None
    # a rerun matches everything and creates nothing
    again = client.post("/api/imports/bigin?dry_run=false", files=_files(), headers=admin_headers).json()
    assert again["companies"] == {"matched": 2} and again["contacts"] == {"matched": 2}
    # undo the first batch: its created rows go, the pre-existing company stays
    r = client.post(f"/api/imports/{out['batch_id']}/undo", headers=admin_headers)
    assert r.status_code == 200 and r.json()["deleted"] == {"contacts": 2, "companies": 1, "deals": 0}
    assert db.get(Company, existing["id"]) is not None and db.scalar(select(Contact)) is None


def test_tags_on_deals_and_companies_with_filters_and_bulk(client, db, staff_headers, pipelines):
    p = pipelines["property"]
    co = client.post("/api/companies", json={"name": "Bridge Agency", "kind": "agency"}, headers=staff_headers).json()
    d1 = client.post("/api/deals", json={"title": "12 Pine St", "pipeline_id": p.id, "next_action_at": "2026-12-01", "company_id": co["id"]}, headers=staff_headers).json()
    d2 = client.post("/api/deals", json={"title": "9 Oak Ave", "pipeline_id": p.id, "next_action_at": "2026-12-01"}, headers=staff_headers).json()
    assert d1["tags"] == []
    r = client.put(f"/api/deals/{d1['id']}/tags", json={"tags": ["hot", "section-a"]}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["tags"] == ["hot", "section-a"]
    assert [d["id"] for d in client.get("/api/deals?tag=hot", headers=staff_headers).json()] == [d1["id"]]
    assert client.get(f"/api/deals/{d1['id']}", headers=staff_headers).json()["tags"] == ["hot", "section-a"]
    r = client.put(f"/api/companies/{co['id']}/tags", json={"tags": ["referral"]}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["tags"] == ["referral"]
    assert [c["id"] for c in client.get("/api/companies?tag=referral", headers=staff_headers).json()] == [co["id"]]
    assert client.get("/api/companies?tag=none", headers=staff_headers).json() == []
    r = client.post("/api/tags/bulk", json={"entity": "deal", "ids": [d1["id"], d2["id"], 999], "add": ["q4"], "remove": ["section-a"]}, headers=staff_headers)
    assert r.status_code == 200 and r.json() == {"matched": 2, "changed": 2}
    assert client.get(f"/api/deals/{d1['id']}", headers=staff_headers).json()["tags"] == ["hot", "q4"]
    assert client.get(f"/api/deals/{d2['id']}", headers=staff_headers).json()["tags"] == ["q4"]
    counts = {t["name"]: t["count"] for t in client.get("/api/tags?entity=deal", headers=staff_headers).json()}
    assert counts == {"hot": 1, "q4": 2}
    assert {t["name"]: t["count"] for t in client.get("/api/tags", headers=staff_headers).json()} == {"hot": 1, "q4": 2, "referral": 1, "section-a": 0}
    assert client.post("/api/views", json={"entity": "deals", "name": "Hot", "filters": {"tag": "hot"}}, headers=staff_headers).status_code == 201
