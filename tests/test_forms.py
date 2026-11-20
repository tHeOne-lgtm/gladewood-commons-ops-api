import hashlib
import json

import jwt
from sqlalchemy import select

from app.forms import initials, map_fields
from app.models import Activity, Company, Consent, Contact, Deal, Note
from app.routers.crm import forms as forms_router

NETLIFY_SECRET = "netlify-test-secret-at-least-32-bytes-long"


def setup_function():
    forms_router._buckets.clear()


def test_map_fields_aliases_and_names():
    m = map_fields({"Full Name": "Sam Lee", "E-mail": " Sam@X.test ", "tel": "423-555-0100", "Comments": "hi", "Room Type": "Private",
                    "bot-field": "", "consent": "yes"})
    assert m["name"] == "Sam Lee" and m["email"] == "Sam@X.test" and m["phone"] == "423-555-0100"
    assert m["message"] == "hi" and m["room_preference"] == "Private" and m["contact_ok"] is True and "website" not in m
    assert map_fields({"first_name": "Sam", "last_name": "Lee"})["name"] == "Sam Lee"
    assert initials("sam lee") == "S. L." and initials("") == "Web inquiry"


def test_inquiry_form_creates_contact_deal_note_task(client, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    r = client.post("/api/forms/inquiry", json={"name": "Sam Lee", "email": "sam@x.test", "phone": "(423) 555-0100",
                                                "message": "Is a private room open in December?", "room": "Private",
                                                "move_in": "2026-12-01", "consent": "yes", "page": "/rooms"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["created_contact"] and out["deal_id"]
    c = db.get(Contact, out["contact_id"])
    assert c.display_name == "S. L." and c.first_name == "Sam" and c.email == "sam@x.test" and c.phone == "+14235550100"
    assert c.kind == "prospect" and c.source == "web"
    assert client.get(f"/api/contacts/{c.id}", headers=staff_headers).json()["tags"] == ["src-web"]
    d = db.get(Deal, out["deal_id"])
    assert d.stage.name == "Inquiry" and d.status == "open" and d.extra["room_preference"] == "Private" and d.next_action_at
    assert db.scalar(select(Note).where(Note.entity_id == c.id)).body.startswith("Web form:")
    assert db.scalar(select(Activity).where(Activity.deal_id == d.id)).subject == "Call back new web inquiry"
    assert db.scalar(select(Consent).where(Consent.contact_id == c.id)).consent_type == "email"


def test_inquiry_matches_existing_contact_and_does_not_duplicate_deal(client, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    client.post("/api/forms/inquiry", data={"name": "Sam Lee", "email": "sam@x.test"})
    r = client.post("/api/forms/inquiry", data={"name": "Samuel Lee", "email": "SAM@x.test", "phone": "4235550100"})
    assert r.status_code == 201 and r.json()["created_contact"] is False and r.json()["deal_id"] is None
    assert len(db.scalars(select(Contact)).all()) == 1 and len(db.scalars(select(Deal)).all()) == 1
    assert db.scalar(select(Contact)).phone == "+14235550100"  # filled in from the second submission


def test_honeypot_and_rate_limit(client, db, admin_headers, settings, pipelines):
    client.get("/api/me", headers=admin_headers)
    r = client.post("/api/forms/inquiry", json={"name": "Bot", "email": "b@x.test", "website": "http://spam"})
    assert r.status_code == 204 and db.scalar(select(Contact)) is None
    for i in range(settings.forms_rate_limit_per_hour - 1):  # the honeypot hit used one slot
        assert client.post("/api/forms/inquiry", json={"name": f"P{i}", "email": f"p{i}@x.test"}).status_code == 201
    assert client.post("/api/forms/inquiry", json={"name": "P", "email": "p@x.test"}).status_code == 429


def test_referral_form_creates_company_case_manager_and_partner_deal(client, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    r = client.post("/api/forms/referral", json={"name": "Jo Park", "organization": "Erlanger Case Mgmt", "organization_type": "hospital",
                                                 "role": "Discharge planner", "email": "jo@erlanger.test", "message": "We place 3 to 5 clients a month."})
    assert r.status_code == 201, r.text
    co = db.scalar(select(Company))
    assert co.name == "Erlanger Case Mgmt" and co.kind == "hospital"
    c = db.get(Contact, r.json()["contact_id"])
    assert c.kind == "case_manager" and c.company_id == co.id and c.display_name == "Jo Park"
    assert sorted(client.get(f"/api/contacts/{c.id}", headers=staff_headers).json()["tags"]) == ["referral", "src-web"]
    d = db.get(Deal, r.json()["deal_id"])
    assert d.stage.name == "Contacted" and d.company_id == co.id and d.title == "Partner: Erlanger Case Mgmt"
    assert db.scalar(select(Activity).where(Activity.deal_id == d.id)).subject == "Send partner fact sheet"


def test_netlify_webhook_requires_valid_signature_and_routes_by_form_name(client, app, db, admin_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    app.state.settings.forms_webhook_secret = NETLIFY_SECRET
    body = json.dumps({"form_name": "tour-request", "site_url": "https://gladewoodcommons.com",
                       "data": {"name": "Ana Ruiz", "email": "ana@x.test", "phone": "4235550111", "message": "Tour this week?"}}).encode()
    good = jwt.encode({"iss": "netlify", "sha256": hashlib.sha256(body).hexdigest()}, NETLIFY_SECRET, algorithm="HS256")
    bad = jwt.encode({"iss": "netlify", "sha256": "0" * 64}, NETLIFY_SECRET, algorithm="HS256")
    assert client.post("/api/forms/netlify", content=body, headers={"content-type": "application/json", "x-webhook-signature": bad}).status_code == 403
    assert client.post("/api/forms/netlify", content=body, headers={"content-type": "application/json"}).status_code == 403
    r = client.post("/api/forms/netlify", content=body, headers={"content-type": "application/json", "x-webhook-signature": good})
    assert r.status_code == 201, r.text
    assert db.get(Contact, r.json()["contact_id"]).display_name == "A. R."
    ref = json.dumps({"form_name": "referral-inquiry", "data": {"name": "Jo Park", "organization": "Bridge Agency", "email": "jo@b.test"}}).encode()
    sig = jwt.encode({"iss": "netlify", "sha256": hashlib.sha256(ref).hexdigest()}, NETLIFY_SECRET, algorithm="HS256")
    r = client.post("/api/forms/netlify", content=ref, headers={"content-type": "application/json", "x-webhook-signature": sig})
    assert r.status_code == 201 and db.scalar(select(Company).where(Company.name == "Bridge Agency")) is not None
