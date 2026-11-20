import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from sqlalchemy import select

from app.emailing import lint, parse_unsubscribe_token, render_text, unknown_fields, unsubscribe_token
from app.models import Consent, Contact, Email, EmailTemplate
from app.seed import seed_default_email_templates

SECRET = "whsec_dGVzdC1zZWNyZXQtdGVzdC1zZWNyZXQtdGVzdA=="


class FakeResend(httpx.MockTransport):
    """Records every send; returns a fresh id. Fails when the subject contains 'FAIL'."""
    def __init__(self):
        self.sent: list[dict] = []
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.headers["authorization"] == "Bearer re_test"
        self.sent.append(body)
        if "FAIL" in body["subject"]:
            return httpx.Response(422, json={"message": "bad address"})
        return httpx.Response(200, json={"id": f"re_{len(self.sent)}"})


@pytest.fixture
def resend(app):
    t = FakeResend()
    app.state.email_transport = t
    return t


def _contact(client, headers, email="sam@x.test", **kw):
    body = {"display_name": "S. L.", "first_name": "Sam", "email": email, "kind": "prospect", **kw}
    r = client.post("/api/contacts", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _consent(client, headers, contact_id):
    assert client.post("/api/consents", json={"contact_id": contact_id, "consent_type": "email", "source": "form"}, headers=headers).status_code == 201


def test_render_lint_and_tokens(settings):
    assert render_text("Hi {{first_name}}, {{ unknown }}!", {"first_name": "Sam"}) == "Hi Sam, !"
    assert unknown_fields("{{first_name}} {{foo}}", "{{bar}}") == ["foo", "bar"]
    assert lint("Room open", "no care needed here") == ["care"]
    tok = unsubscribe_token(settings, 42)
    assert parse_unsubscribe_token(settings, tok) == 42
    assert parse_unsubscribe_token(settings, "42.deadbeef") is None and parse_unsubscribe_token(settings, "junk") is None


def test_templates_crud_refuses_protected_terms_and_unknown_fields(client, staff_headers):
    r = client.post("/api/email/templates", json={"name": "T1", "subject": "Hello {{first_name}}", "body_text": "Body {{deal_title}}"}, headers=staff_headers)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert client.post("/api/email/templates", json={"name": "T1", "subject": "x", "body_text": "y"}, headers=staff_headers).status_code == 409
    r = client.post("/api/email/templates", json={"name": "T2", "subject": "x", "body_text": "Wheelchair access"}, headers=staff_headers)
    assert r.status_code == 422 and "wheelchair" in r.json()["detail"]
    r = client.post("/api/email/templates", json={"name": "T3", "subject": "{{nope}}", "body_text": "y"}, headers=staff_headers)
    assert r.status_code == 422 and "nope" in r.json()["detail"]
    r = client.put(f"/api/email/templates/{tid}", json={"name": "T1", "subject": "Hello", "body_text": "Body", "is_active": False}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/email/templates", headers=staff_headers).json() == []
    assert len(client.get("/api/email/templates?include_inactive=true", headers=staff_headers).json()) == 1


def test_default_templates_pass_the_lint(db):
    added = seed_default_email_templates(db)
    assert len(added) == 5 and seed_default_email_templates(db) == []
    for t in db.scalars(select(EmailTemplate)).all():
        assert lint(t.subject, t.body_text) == [], t.name
        assert unknown_fields(t.subject, t.body_text) == []


def test_preview_and_send_transactional_with_footer(client, db, staff_headers, pipelines, resend, settings):
    c = _contact(client, staff_headers)
    p = pipelines["resident-inquiry"]
    d = client.post("/api/deals", json={"title": "Inquiry: S. L.", "pipeline_id": p.id, "contact_id": c["id"], "next_action_at": "2026-12-01",
                                         "extra": {"room_preference": "Private"}}, headers=staff_headers).json()
    r = client.post("/api/email/preview", json={"subject": "Tour on {{next_action_at}}", "body_text": "Hi {{first_name}}, {{room_preference}} room.", "contact_id": c["id"], "deal_id": d["id"]}, headers=staff_headers)
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["subject"] == "Tour on 2026-12-01" and pv["can_send"] and "Hi Sam, Private room." in pv["body_text"]
    assert "PO Box 1, Chattanooga" in pv["body_text"] and "Equal Housing Opportunity." in pv["body_text"]
    assert "/api/email/unsubscribe/" in pv["body_text"] and "<a href=" in pv["body_html"]
    r = client.post("/api/email/send", json={"contact_id": c["id"], "deal_id": d["id"], "subject": "Tour on {{next_action_at}}", "body_text": "Hi {{first_name}}"}, headers=staff_headers)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "sent" and r.json()["to_email"] == "sam@x.test"
    sent = resend.sent[0]
    assert sent["to"] == ["sam@x.test"] and sent["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert sent["from"] == settings.email_from and "<!doctype html>" in sent["html"]
    row = db.scalar(select(Email))
    assert row.provider_message_id == "re_1" and row.deal_id == d["id"] and row.sent_by
    tl = client.get(f"/api/timeline?entity=contact&entity_id={c['id']}", headers=staff_headers).json()
    assert any(i["type"] == "email.out" and i["summary"] == "Tour on 2026-12-01" for i in tl)
    assert client.get(f"/api/email/log?contact_id={c['id']}", headers=staff_headers).json()[0]["id"] == row.id


def test_send_gates_marketing_consent_unsubscribe_and_bounce(client, db, staff_headers, resend, settings):
    c = _contact(client, staff_headers)
    body = {"contact_id": c["id"], "subject": "News", "body_text": "Rooms open", "marketing": True}
    r = client.post("/api/email/send", json=body, headers=staff_headers)
    assert r.status_code == 409 and r.json()["detail"]["skip_reason"] == "no_consent"
    _consent(client, staff_headers, c["id"])
    assert client.post("/api/email/send", json=body, headers=staff_headers).status_code == 201
    # the unsubscribe link withdraws consent; transactional mail is then blocked too
    tok = unsubscribe_token(settings, c["id"])
    r = client.post(f"/api/email/unsubscribe/{tok}")
    assert r.status_code == 200 and "unsubscribed" in r.text
    assert client.get("/api/email/unsubscribe/1.bad").status_code == 404
    assert db.scalar(select(Consent).where(Consent.contact_id == c["id"])).withdrawn_at is not None
    r = client.post("/api/email/send", json={**body, "marketing": False}, headers=staff_headers)
    assert r.status_code == 409 and r.json()["detail"]["skip_reason"] == "unsubscribed"
    # a send failure is logged as failed and reported as 502
    c2 = _contact(client, staff_headers, email="jo@x.test")
    r = client.post("/api/email/send", json={"contact_id": c2["id"], "subject": "FAIL this", "body_text": "x"}, headers=staff_headers)
    assert r.status_code == 502
    assert db.scalar(select(Email).where(Email.contact_id == c2["id"])).status == "failed"


def _svix(body: bytes, secret=SECRET, ts=None):
    ts = str(ts or int(time.time()))
    mid = "msg_1"
    key = base64.b64decode(secret.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, f"{mid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": mid, "svix-timestamp": ts, "svix-signature": f"v1,{sig}", "content-type": "application/json"}


def test_resend_webhook_updates_rows_and_marks_bounces(client, db, staff_headers, resend):
    c = _contact(client, staff_headers)
    client.post("/api/email/send", json={"contact_id": c["id"], "subject": "Hi", "body_text": "x"}, headers=staff_headers)
    row = db.scalar(select(Email))
    ev = json.dumps({"type": "email.delivered", "created_at": "2026-11-20T10:00:00Z", "data": {"email_id": row.provider_message_id, "to": ["sam@x.test"]}}).encode()
    assert client.post("/api/webhooks/resend", content=ev, headers={"content-type": "application/json"}).status_code == 403
    bad = _svix(ev, secret="whsec_b3RoZXI=")
    assert client.post("/api/webhooks/resend", content=ev, headers=bad).status_code == 403
    stale = _svix(ev, ts=int(time.time()) - 3600)
    assert client.post("/api/webhooks/resend", content=ev, headers=stale).status_code == 403
    assert client.post("/api/webhooks/resend", content=ev, headers=_svix(ev)).status_code == 204
    db.refresh(row)
    assert row.status == "delivered" and row.delivered_at is not None
    for kind in ("email.opened", "email.clicked"):
        ev = json.dumps({"type": kind, "data": {"email_id": row.provider_message_id}}).encode()
        assert client.post("/api/webhooks/resend", content=ev, headers=_svix(ev)).status_code == 204
    db.refresh(row)
    assert row.opened_at and row.clicked_at
    ev = json.dumps({"type": "email.bounced", "data": {"email_id": row.provider_message_id, "bounce": {"type": "Permanent"}}}).encode()
    assert client.post("/api/webhooks/resend", content=ev, headers=_svix(ev)).status_code == 204
    db.refresh(row)
    assert row.status == "bounced"
    contact = db.get(Contact, c["id"])
    db.refresh(contact)
    assert contact.extra["email_bounced_at"]
    r = client.post("/api/email/send", json={"contact_id": c["id"], "subject": "Again", "body_text": "x"}, headers=staff_headers)
    assert r.status_code == 409 and r.json()["detail"]["skip_reason"] == "bounced"
    ev = json.dumps({"type": "email.delivered", "data": {"email_id": "unknown"}}).encode()
    assert client.post("/api/webhooks/resend", content=ev, headers=_svix(ev)).status_code == 204
