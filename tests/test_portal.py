"""Portal v1 (decisions 2026-11-20): six roles, tenancies, documents on the Mac mini file service,
maintenance requests through the Rule 11 router (hold when unreachable), case manager grants."""
import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.files import verify
from app.models import AuditLog, Contact, MaintenanceRequest, User
from tests.conftest import auth, make_token

RESIDENT_EMAIL = "resident.a@example.test"
CM_EMAIL = "cm@agency.test"


def _user(db, role, email):
    u = User(id=str(uuid.uuid4()), email=email, role=role)
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def people(db):
    return {r: _user(db, r, f"{r}@example.test") for r in ("owner", "management", "ops_staff", "audit")} | \
        {"resident": _user(db, "resident", RESIDENT_EMAIL), "case_manager": _user(db, "case_manager", CM_EMAIL)}


def hdr(u):
    return auth(make_token(u.id, u.email))


class Router(httpx.MockTransport):
    """Fake n8n Rule 11 router: flags text containing 'FLAGME', fails when `down`."""
    def __init__(self):
        self.down = False
        self.calls = []
        super().__init__(self.handle)

    def handle(self, request):
        self.calls.append(json.loads(request.content))
        if self.down:
            raise httpx.ConnectError("router down")
        assert request.headers["x-rule11-secret"] == "r11-secret"
        return httpx.Response(200, json={"flagged": "FLAGME" in self.calls[-1]["text"], "reason": "test"})


@pytest.fixture
def router(app):
    app.state.settings.rule11_router_url = "https://n8n.example.test/webhook/gc/rule11"
    app.state.settings.rule11_secret = "r11-secret"
    r = Router()
    app.state.rule11_transport = r
    yield r
    app.state.settings.rule11_router_url = ""


@pytest.fixture
def housing(client, db, people):
    """A property, a room, a resident contact matching the resident login, and an active tenancy."""
    h = hdr(people["ops_staff"])
    prop = client.post("/api/properties", json={"address": "12 Pine St", "status": "Master lease signed"}, headers=h).json()
    room = client.post("/api/housing/rooms", json={"property_id": prop["id"], "name": "Room 2", "monthly_rent": "650"}, headers=h).json()
    contact = client.post("/api/contacts", json={"display_name": "Resident A", "first_name": "Resident", "email": RESIDENT_EMAIL, "kind": "prospect"}, headers=h).json()
    t = client.post("/api/housing/tenancies", json={"contact_id": contact["id"], "property_id": prop["id"], "room_id": room["id"], "start_date": "2026-11-01", "rent_amount": "650"}, headers=h)
    assert t.status_code == 201, t.text
    return {"property": prop, "room": room, "contact": contact, "tenancy": t.json()}


def test_role_matrix(client, db, people, housing):
    # audit: reads work and are logged; writes are refused
    a = hdr(people["audit"])
    assert client.get("/api/contacts", headers=a).status_code == 200
    assert client.post("/api/contacts", json={"display_name": "X"}, headers=a).status_code == 403
    assert db.scalar(select(AuditLog).where(AuditLog.action == "audit.read")).details["path"] == "/api/contacts"
    # management may assign roles but not grant owner; owner may
    m, o = hdr(people["management"]), hdr(people["owner"])
    target = people["case_manager"]
    assert client.put(f"/api/users/{target.id}/role", json={"role": "owner"}, headers=m).status_code == 403
    assert client.put(f"/api/users/{target.id}/role", json={"role": "case_manager"}, headers=m).status_code == 200
    assert client.get("/api/users", headers=hdr(people["ops_staff"])).status_code == 403
    me = client.get("/api/me", headers=o).json()
    assert me["role"] == "owner" and me["is_staff"] is True
    assert client.get("/api/me", headers=hdr(people["resident"])).json()["is_staff"] is False
    # residents and case managers cannot reach the CRM or staff housing routes
    for who in ("resident", "case_manager"):
        assert client.get("/api/contacts", headers=hdr(people[who])).status_code == 403
        assert client.get("/api/housing/tenancies", headers=hdr(people[who])).status_code == 403
    assert client.get("/api/portal/me", headers=hdr(people["ops_staff"])).status_code == 403


def test_resident_profile_links_by_email_and_sees_own_tenancy(client, db, people, housing):
    r = hdr(people["resident"])
    me = client.get("/api/portal/me", headers=r).json()
    assert me["role"] == "resident" and me["display_name"] == "Resident A" and len(me["tenancies"]) == 1
    assert me["tenancies"][0]["property_address"] == "12 Pine St" and me["tenancies"][0]["room_name"] == "Room 2"
    assert db.get(Contact, housing["contact"]["id"]).portal_user_id == people["resident"].id
    assert db.get(Contact, housing["contact"]["id"]).kind == "resident"
    assert client.put("/api/portal/me", json={"phone": "423-555-0100"}, headers=r).json()["phone"] == "423-555-0100"
    # a second resident login with no contact sees nothing and cannot update
    other = _user(db, "resident", "nobody@example.test")
    assert client.get("/api/portal/me", headers=hdr(other)).json()["tenancies"] == []
    assert client.put("/api/portal/me", json={"phone": "1"}, headers=hdr(other)).status_code == 404


def test_documents_metadata_upload_link_stored_callback_and_visibility(client, db, people, housing, settings):
    h = hdr(people["ops_staff"])
    tid = housing["tenancy"]["id"]
    r = client.post("/api/housing/documents", json={"tenancy_id": tid, "title": "Lease", "category": "lease", "shared_with_resident": True}, headers=h)
    assert r.status_code == 201, r.text
    doc, up = r.json()["document"], r.json()["upload"]
    assert doc["status"] == "pending_upload" and up["url"].endswith("/upload")
    tok = verify(settings, up["token"])
    assert tok["doc"] == doc["id"] and tok["op"] == "upload"
    assert verify(settings, up["token"] + "x") is None
    # not visible to the resident until the file service confirms storage
    res = hdr(people["resident"])
    assert client.get("/api/portal/documents", headers=res).json() == []
    key = {"X-Api-Key": settings.integration_api_key}
    r = client.post(f"/api/integrations/documents/{doc['id']}/stored", json={"storage_key": "tenancies/1/lease.pdf", "size_bytes": 12345, "content_type": "application/pdf", "drive_file_id": "drv1"}, headers=key)
    assert r.status_code == 200 and r.json()["status"] == "stored"
    docs = client.get("/api/portal/documents", headers=res).json()
    assert [d["title"] for d in docs] == ["Lease"]
    link = client.get(f"/api/portal/documents/{doc['id']}/link", headers=res).json()
    assert link["url"].startswith("https://files.example.test/webhook/gc/files/download?token=")
    payload = verify(settings, link["url"].split("token=")[1])
    assert payload["op"] == "download" and payload["key"] == "tenancies/1/lease.pdf"
    # the case manager has no grant yet, so nothing
    cm = hdr(people["case_manager"])
    assert client.get("/api/portal/documents", headers=cm).json() == []
    assert client.get(f"/api/portal/documents/{doc['id']}/link", headers=cm).status_code == 404
    # unshare: the resident loses it
    client.put(f"/api/housing/documents/{doc['id']}", json={"tenancy_id": tid, "title": "Lease", "category": "lease", "shared_with_resident": False}, headers=h)
    assert client.get("/api/portal/documents", headers=res).json() == []


def test_maintenance_clear_flagged_and_staff_queue(client, db, people, housing, router):
    res, h = hdr(people["resident"]), hdr(people["ops_staff"])
    r = client.post("/api/portal/maintenance", json={"category": "plumbing", "title": "Sink drains slowly", "description": "Kitchen sink backs up after dishes."}, headers=res)
    assert r.status_code == 201, r.text
    ok = r.json()
    assert ok["status"] == "open" and ok["screening_status"] == "clear" and ok["description"].startswith("Kitchen")
    assert router.calls[-1]["channel"] == "portal.maintenance" and router.calls[-1]["ref"] == f"maintenance_requests:{ok['id']}"
    r = client.post("/api/portal/maintenance", json={"category": "other", "title": "Please read", "description": "FLAGME this text must not be stored"}, headers=res)
    flagged = r.json()
    assert flagged["status"] == "withheld" and flagged["screening_status"] == "flagged" and flagged["description"] == "" and flagged["title"] == ""
    row = db.get(MaintenanceRequest, flagged["id"])
    assert row.description == "" and row.title == ""
    assert db.scalar(select(AuditLog).where(AuditLog.action == "rule11.flagged")).details["category"] == "other"
    # staff queue: the open one carries text, the withheld one is a marker only
    q = {x["id"]: x for x in client.get("/api/housing/maintenance", headers=h).json()}
    assert q[ok["id"]]["description"].startswith("Kitchen") and q[ok["id"]]["resident_name"] == "Resident A"
    assert q[flagged["id"]]["status"] == "withheld" and q[flagged["id"]]["description"] == ""
    assert client.put(f"/api/housing/maintenance/{flagged['id']}", json={"status": "open"}, headers=h).status_code == 409
    # staff progress, comment (guarded), resident comment (screened), redact
    r = client.put(f"/api/housing/maintenance/{ok['id']}", json={"status": "in_progress", "assigned_to": people["ops_staff"].id, "priority": "high"}, headers=h)
    assert r.json()["status"] == "in_progress" and r.json()["priority"] == "high"
    assert client.post(f"/api/housing/maintenance/{ok['id']}/comments", json={"body": "needs supervision"}, headers=h).status_code == 422
    assert client.post(f"/api/housing/maintenance/{ok['id']}/comments", json={"body": "Plumber booked for Monday."}, headers=h).status_code == 201
    r = client.post(f"/api/portal/maintenance/{ok['id']}/comments", json={"body": "Thanks, mornings work."}, headers=res)
    assert r.status_code == 201 and [c["body"] for c in r.json()["comments"]] == ["Plumber booked for Monday.", "Thanks, mornings work."]
    assert r.json()["comments"][1]["mine"] is True
    mine = client.get("/api/portal/maintenance", headers=res).json()
    assert {m["id"]: m["status"] for m in mine} == {ok["id"]: "in_progress", flagged["id"]: "withheld"}
    assert client.post(f"/api/housing/maintenance/{ok['id']}/redact", headers=h).json()["description"] == ""
    r = client.put(f"/api/housing/maintenance/{ok['id']}", json={"status": "done"}, headers=h)
    assert r.json()["resolved_at"] is not None


def test_router_unreachable_holds_logs_alerts_and_retries(client, db, people, housing, router, app, settings):
    from app.rule11 import retry_held
    res, h = hdr(people["resident"]), hdr(people["ops_staff"])
    settings.email_provider = "log"
    try:
        router.down = True
        r = client.post("/api/portal/maintenance", json={"category": "hvac", "title": "No heat", "description": "Heater stopped overnight."}, headers=res)
        assert r.status_code == 201, r.text
        held = r.json()
        assert held["status"] == "pending_screening" and held["screening_status"] == "unreachable" and held["description"] == ""
        row = db.get(MaintenanceRequest, held["id"])
        assert row.description == "Heater stopped overnight." and row.screening_attempts == 1  # held, unread
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "rule11.router_unreachable"))
        assert audit.details["ref"] == f"maintenance_requests:{held['id']}" and audit.details["attempt"] == 1
        q = client.get("/api/housing/maintenance", headers=h).json()
        assert q[0]["status"] == "pending_screening" and q[0]["description"] == ""  # staff cannot read held text
        assert client.post(f"/api/portal/maintenance/{held['id']}/comments", json={"body": "x"}, headers=res).status_code == 409
        # still down: retry keeps holding and does not alert twice
        assert retry_held(db, settings, transport=router) == {"retried": 1, "cleared": 0, "flagged": 0, "still_held": 1}
        assert db.scalar(select(AuditLog).where(AuditLog.action == "rule11.router_unreachable").order_by(AuditLog.id.desc())).details["attempt"] == 2
        # router back: the text clears and the request opens
        router.down = False
        assert retry_held(db, settings, transport=router) == {"retried": 1, "cleared": 1, "flagged": 0, "still_held": 0}
        db.refresh(row)
        assert row.status == "open" and row.description == "Heater stopped overnight."
    finally:
        settings.email_provider = "resend"


def test_case_manager_grant_scopes_revoke_and_read_logging(client, db, people, housing, router):
    res, cm, h = hdr(people["resident"]), hdr(people["case_manager"]), hdr(people["ops_staff"])
    tid = housing["tenancy"]["id"]
    # a stored, shared document and an open request
    doc = client.post("/api/housing/documents", json={"tenancy_id": tid, "title": "Voucher letter", "category": "voucher", "shared_with_resident": True, "shared_with_case_manager": True}, headers=h).json()["document"]
    client.post(f"/api/integrations/documents/{doc['id']}/stored", json={"storage_key": "k", "size_bytes": 1}, headers={"X-Api-Key": "cc-test-key-0123456789abcdef0123456789"})
    req = client.post("/api/portal/maintenance", json={"category": "pest", "title": "Ants", "description": "Ants in the pantry."}, headers=res).json()
    assert client.get("/api/portal/me", headers=cm).json()["tenancies"] == []
    # resident grants documents only
    assert client.post("/api/portal/grants", json={"case_manager_email": CM_EMAIL, "scopes": ["documents"]}, headers=cm).status_code == 403
    r = client.post("/api/portal/grants", json={"case_manager_email": CM_EMAIL.upper(), "scopes": ["documents"]}, headers=res)
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    me = client.get("/api/portal/me", headers=cm).json()
    assert [t["id"] for t in me["tenancies"]] == [tid] and me["grants"][0]["case_manager_user_id"] == people["case_manager"].id
    assert [d["title"] for d in client.get("/api/portal/documents", headers=cm).json()] == ["Voucher letter"]
    assert client.get("/api/portal/maintenance", headers=cm).json() == []  # no maintenance scope
    assert client.get(f"/api/portal/maintenance/{req['id']}", headers=cm).status_code == 404
    reads = db.scalars(select(AuditLog).where(AuditLog.action == "portal.grant_read")).all()
    assert len(reads) == 1 and reads[0].actor_id == people["case_manager"].id and reads[0].entity == "document"
    # management widens the grant; the case manager sees the request status but never the resident's text
    r = client.post("/api/housing/grants", json={"tenancy_id": tid, "case_manager_email": CM_EMAIL, "scopes": ["documents", "maintenance"]}, headers=hdr(people["management"]))
    assert r.status_code == 201
    seen = client.get("/api/portal/maintenance", headers=cm).json()
    assert len(seen) == 1 and seen[0]["status"] == "open" and seen[0]["description"] == ""
    assert client.post("/api/housing/grants", json={"tenancy_id": tid, "case_manager_email": CM_EMAIL}, headers=h).status_code == 403
    # the resident revokes their own grant; the management one stays
    assert client.post(f"/api/portal/grants/{gid}/revoke", headers=res).json()["revoked_at"] is not None
    assert len(client.get("/api/portal/grants", headers=cm).json()) == 1
    assert client.post(f"/api/portal/grants/{gid}/revoke", headers=cm).status_code == 404
    assert len(client.get("/api/housing/grants", headers=h).json()) == 2
