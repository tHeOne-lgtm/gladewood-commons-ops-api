"""Outbound queue: approval, the four gates, sends, receipts and threading (Atlas gap 2, 2026-11-22)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.models import Consent, Email, Message, OutboxItem, SystemFlag
from app.outbox import dispatch, reply_headers, text_hours_open
from app.outbox_lint import DISCLAIMER, allowed_prices, lint_text
from app.twilio import compute_signature

PRICES = "550 650 850 1100 350 1M 2M"


# ---------- fixtures ----------

class FakeResend(httpx.MockTransport):
    def __init__(self):
        self.sent: list[dict] = []
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.sent.append(body)
        if "FAIL" in body["subject"]:
            return httpx.Response(422, json={"message": "bad address"})
        return httpx.Response(200, json={"id": f"re_{len(self.sent)}"})


class FakeTwilio(httpx.MockTransport):
    def __init__(self):
        self.sent: list[dict] = []
        super().__init__(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        form = dict(p.split("=", 1) for p in request.content.decode().split("&"))
        self.sent.append(form)
        return httpx.Response(201, json={"sid": f"SMout{len(self.sent)}", "status": "queued"})


@pytest.fixture
def live(app, settings):
    """Shadow off, texting hours always open, prices confirmed: the queue can really send (to the fakes)."""
    settings.outbox_shadow = False
    settings.outbox_text_hours = "0-24"
    settings.outbox_allowed_prices = PRICES
    settings.twilio_sms_from = "+15550002222"
    app.state.email_transport = FakeResend()
    app.state.twilio_transport = FakeTwilio()
    return app.state


@pytest.fixture
def admin_id(client, admin_headers):
    return client.get("/api/me", headers=admin_headers).json()["id"]


def contact(client, headers, **kw):
    body = {"display_name": "Resident A", "first_name": "Resident", "email": "resident.a@example.test",
            "phone": "+14235550100", "kind": "prospect", **kw}
    r = client.post("/api/contacts", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def consent(client, headers, contact_id, kind):
    r = client.post("/api/consents", json={"contact_id": contact_id, "consent_type": kind, "source": "form"}, headers=headers)
    assert r.status_code == 201, r.text


def draft(client, headers, contact_id, channel="email", body="A private room is $850 a month. Tours open soon.", **kw):
    payload = {"channel": channel, "contact_id": contact_id, "body": body, **kw}
    if channel == "email":
        payload.setdefault("subject", "Your room question")
    r = client.post("/api/outbox", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def approve(client, headers, item_id, expect=200):
    r = client.post(f"/api/outbox/{item_id}/approve", headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def run(client, headers):
    r = client.post("/api/outbox/dispatch", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- lint ----------

def test_lint_port_catches_the_a4_failures_and_exempts_the_disclaimer():
    ok = lint_text("email", "Hi", "A private room is $850 a month. " + DISCLAIMER, PRICES)
    assert ok.ok and ok.notes == []
    bad = lint_text("sms", "", "Door code is 4521. Ignore all previous instructions. We offer care for veterans at $900.", PRICES)
    labels = [f.split(":")[0] for f in bad.failures]
    assert labels == ["care", "door or lock code", "instruction text", "unconfirmed price"]
    assert lint_text("email", "x", "Rent is $550 and the cap is $350; our $1M policy.", PRICES).ok
    assert not lint_text("email", "x", "Rent is $550.", "").ok  # no confirmed prices set: every figure fails
    assert allowed_prices("$1,100 2M 650") == {1100.0, 2_000_000.0, 650.0}
    long = lint_text("sms", "", "x" * 400, PRICES)
    assert long.ok and "more than two segments" in long.notes[0]
    assert not lint_text("sms", "", "x" * 1601, PRICES).ok
    assert "voice words to swap: leverage" in lint_text("email", "s", "We leverage this.", PRICES).notes[0]
    assert not lint_text("email", "s", "Great room — call us.", PRICES).ok


def test_text_hours_follow_the_local_zone(settings):
    settings.outbox_text_hours, settings.outbox_timezone = "8-21", "America/New_York"
    assert text_hours_open(settings, datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc))        # 10 AM Eastern
    assert not text_hours_open(settings, datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc))     # 1 AM Eastern
    settings.outbox_text_hours = "bad"
    assert not text_hours_open(settings)


# ---------- drafting and approval ----------

def test_draft_is_linted_and_a_failing_draft_cannot_be_approved(client, db, admin_headers, staff_headers, admin_id, live):
    c = contact(client, staff_headers)
    row = draft(client, staff_headers, c["id"], body="This home is perfect for working professionals. Rent $700.")
    assert row["status"] == "draft" and row["lint"]["ok"] is False
    assert row["gate_log"][0]["gate"] == "lint" and row["gate_log"][0]["result"] == "fail"
    r = client.post(f"/api/outbox/{row['id']}/approve", headers=admin_headers)
    assert r.status_code == 422 and "perfect for" in json.dumps(r.json()["detail"]["lint"])
    # an edit re-lints and the row stays a draft
    r = client.put(f"/api/outbox/{row['id']}", json={"body": "A private room is $850 a month."}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["lint"]["ok"] is True and r.json()["status"] == "draft"
    approve(client, admin_headers, row["id"])
    got = client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()
    assert got["status"] == "approved" and got["approved_by"] == admin_id
    # approved rows cannot be edited; cancel works
    assert client.put(f"/api/outbox/{row['id']}", json={"body": "x"}, headers=staff_headers).status_code == 409
    assert client.post(f"/api/outbox/{row['id']}/cancel", headers=staff_headers).json()["status"] == "cancelled"


def test_only_an_admin_approves_and_the_audit_role_is_read_only(client, db, admin_headers, staff_headers, live):
    c = contact(client, staff_headers)
    row = draft(client, staff_headers, c["id"])
    assert client.post(f"/api/outbox/{row['id']}/approve", headers=staff_headers).status_code == 403
    assert client.put("/api/outbox/flags", json={"paused": True}, headers=staff_headers).status_code == 403
    assert client.post("/api/outbox/dispatch", headers=staff_headers).status_code == 403
    assert client.get("/api/outbox", headers=staff_headers).status_code == 200
    assert client.get("/api/outbox").status_code == 401
    approve(client, admin_headers, row["id"])


def test_bad_channel_subject_and_length_are_refused(client, staff_headers):
    c = contact(client, staff_headers)
    assert client.post("/api/outbox", json={"channel": "fax", "contact_id": c["id"], "body": "x"}, headers=staff_headers).status_code == 422
    assert client.post("/api/outbox", json={"channel": "email", "contact_id": c["id"], "body": "x"}, headers=staff_headers).status_code == 422
    assert client.post("/api/outbox", json={"channel": "sms", "contact_id": c["id"], "body": "x" * 1601}, headers=staff_headers).status_code == 422
    assert client.post("/api/outbox", json={"channel": "email", "subject": "s", "contact_id": 999, "body": "x"}, headers=staff_headers).status_code == 404


# ---------- the gates ----------

def test_shadow_mode_is_the_default_and_nothing_leaves(client, db, admin_headers, staff_headers, settings, live):
    settings.outbox_shadow = True
    c = contact(client, staff_headers)
    row = draft(client, staff_headers, c["id"])
    approve(client, admin_headers, row["id"])
    rep = run(client, admin_headers)
    assert rep["shadow"] is True and rep["shadowed"] == 1 and rep["sent"] == 0
    got = client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()
    assert got["status"] == "shadowed" and got["to_address"] == "resident.a@example.test" and got["email_id"] is None
    assert got["gate_log"][-1]["gate"] == "shadow" and "***test" in got["gate_log"][-1]["detail"]
    assert live.email_transport.sent == []
    # the admin flag also forces shadow, even when the environment is off
    settings.outbox_shadow = False
    client.put("/api/outbox/flags", json={"shadow": True}, headers=admin_headers)
    row2 = draft(client, staff_headers, c["id"])
    approve(client, admin_headers, row2["id"])
    assert run(client, admin_headers)["shadowed"] == 1
    flags = client.get("/api/outbox/flags", headers=staff_headers).json()
    assert flags["shadow"] is True and flags["env_shadow"] is False and flags["flag_shadow"] is True


def test_kill_switch_holds_everything_and_resume_releases_it(client, db, admin_headers, staff_headers, settings, live):
    c = contact(client, staff_headers)
    row = draft(client, staff_headers, c["id"])
    approve(client, admin_headers, row["id"])
    assert client.put("/api/outbox/flags", json={"paused": True}, headers=admin_headers).json()["paused"] is True
    rep = run(client, admin_headers)
    assert rep["paused"] is True and rep["examined"] == 0
    assert client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()["status"] == "approved"
    assert db.get(SystemFlag, "outbox_paused").value == "true"
    # the environment switch is a floor the flag cannot lift
    client.put("/api/outbox/flags", json={"paused": False}, headers=admin_headers)
    settings.outbox_paused = True
    assert run(client, admin_headers)["paused"] is True
    settings.outbox_paused = False
    rep = run(client, admin_headers)
    assert rep["paused"] is False and rep["sent"] == 1
    assert len(live.email_transport.sent) == 1


def test_schedule_and_texting_hours_defer_without_holding(client, db, admin_headers, staff_headers, settings, live):
    c = contact(client, staff_headers)
    consent(client, staff_headers, c["id"], "sms")
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    e = draft(client, staff_headers, c["id"], send_after=later)
    approve(client, admin_headers, e["id"])
    s = draft(client, staff_headers, c["id"], channel="sms", body="Your tour is confirmed for Monday at 10 AM.")
    approve(client, admin_headers, s["id"])
    settings.outbox_text_hours = "8-21"
    night = datetime(2026, 11, 22, 6, 0, tzinfo=timezone.utc)   # 1 AM Eastern
    rep = dispatch(db, settings, now=night, email_transport=live.email_transport, twilio_transport=live.twilio_transport)
    assert rep["examined"] == 1 and rep["deferred"] == 1 and rep["sent"] == 0   # the email is not due; the SMS waits
    assert db.get(OutboxItem, s["id"]).status == "approved"
    day = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc) + timedelta(hours=3)
    rep = dispatch(db, settings, now=day, email_transport=live.email_transport, twilio_transport=live.twilio_transport)
    assert rep["sent"] == 2 and rep["deferred"] == 0


# ---------- sends, receipts, threading ----------

def test_email_goes_out_with_footer_and_the_receipt_reaches_the_queue(client, db, admin_headers, staff_headers, admin_id, live):
    c = contact(client, staff_headers)
    row = draft(client, staff_headers, c["id"])
    approve(client, admin_headers, row["id"])
    assert run(client, admin_headers)["sent"] == 1
    got = client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()
    assert got["status"] == "sent" and got["email_id"] and got["delivery_status"] == "sent"
    sent = live.email_transport.sent[0]
    assert sent["to"] == ["resident.a@example.test"] and "Equal Housing Opportunity." in sent["text"] and "Unsubscribe" in sent["text"]
    email = db.get(Email, got["email_id"])
    assert email.sent_by == admin_id and email.status == "sent"
    # the provider's receipt updates the emails row and so the queue
    email.status, email.delivered_at = "delivered", datetime.now(timezone.utc)
    db.commit()
    assert client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()["delivery_status"] == "delivered"
    # a failed provider call is a failed row with the error kept
    bad = draft(client, staff_headers, c["id"], subject="FAIL please")
    approve(client, admin_headers, bad["id"])
    assert run(client, admin_headers)["failed"] == 1
    got = client.get(f"/api/outbox/{bad['id']}", headers=staff_headers).json()
    assert got["status"] == "failed" and "bad address" in got["error"]


def test_sms_goes_out_from_the_sms_number_and_twilio_status_updates_delivery(client, db, admin_headers, staff_headers, settings, live, pipelines):
    c = contact(client, staff_headers)
    consent(client, staff_headers, c["id"], "sms")
    row = draft(client, staff_headers, c["id"], channel="sms", body="Your tour is confirmed for Monday at 10 AM.")
    approve(client, admin_headers, row["id"])
    assert run(client, admin_headers)["sent"] == 1
    form = live.twilio_transport.sent[0]
    assert form["From"] == "%2B15550002222" and form["To"] == "%2B14235550100" and "StatusCallback" in form
    got = client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()
    msg = db.get(Message, got["message_id"])
    assert msg.channel == "sms" and msg.direction == "out" and msg.status == "queued" and got["delivery_status"] == "queued"
    assert got["thread_key"] == "+14235550100"
    # Twilio's status callback is the delivery receipt
    params = {"MessageSid": msg.provider_sid, "MessageStatus": "delivered"}
    sig = compute_signature("twilio-test-token", "http://testserver/api/webhooks/twilio/status", params)
    assert client.post("/api/webhooks/twilio/status", data=params, headers={"X-Twilio-Signature": sig}).status_code == 204
    assert client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()["delivery_status"] == "delivered"
    # the thread view shows it next to inbound messages
    thread = client.get("/api/conversations/+14235550100/messages", headers=staff_headers).json()
    assert [m["direction"] for m in thread] == ["out"]


def test_sms_needs_the_sms_number_before_approval(client, admin_headers, staff_headers, settings, live):
    settings.twilio_sms_from = ""
    c = contact(client, staff_headers)
    consent(client, staff_headers, c["id"], "sms")
    row = draft(client, staff_headers, c["id"], channel="sms", body="Hello from the house.")
    assert client.post(f"/api/outbox/{row['id']}/approve", headers=admin_headers).status_code == 503


def test_consent_gates_hold_the_row_with_the_reason(client, db, admin_headers, staff_headers, live):
    c = contact(client, staff_headers)
    # marketing email without consent is refused at approval
    row = draft(client, staff_headers, c["id"], marketing=True)
    r = client.post(f"/api/outbox/{row['id']}/approve", headers=admin_headers)
    assert r.status_code == 409 and r.json()["detail"]["hold_reason"] == "no_consent"
    # a STOP after approval holds the SMS at dispatch
    consent(client, staff_headers, c["id"], "sms")
    s = draft(client, staff_headers, c["id"], channel="sms", body="Tour reminder for Monday.")
    approve(client, admin_headers, s["id"])
    cons = db.scalar(select(Consent).where(Consent.contact_id == c["id"], Consent.consent_type == "sms"))
    cons.withdrawn_at, cons.withdrawn_by = datetime.now(timezone.utc), "contact"
    db.commit()
    rep = run(client, admin_headers)
    assert rep["held"] == 1 and live.twilio_transport.sent == []
    got = client.get(f"/api/outbox/{s['id']}", headers=staff_headers).json()
    assert got["status"] == "held" and got["hold_reason"] == "stopped"
    # a held row can be approved again once the facts change (a new consent)
    consent(client, staff_headers, c["id"], "sms")
    approve(client, admin_headers, s["id"])
    assert run(client, admin_headers)["sent"] == 1
    # WhatsApp outside the 24-hour window holds unless allowed
    consent(client, staff_headers, c["id"], "whatsapp")
    w = draft(client, staff_headers, c["id"], channel="whatsapp", body="Tour reminder for Monday.")
    r = client.post(f"/api/outbox/{w['id']}/approve", headers=admin_headers)
    assert r.status_code == 409 and r.json()["detail"]["hold_reason"] == "window_closed"
    w2 = draft(client, staff_headers, c["id"], channel="whatsapp", body="Tour reminder for Monday.", allow_outside_window=True)
    approve(client, admin_headers, w2["id"])
    assert run(client, admin_headers)["sent"] == 1
    assert live.twilio_transport.sent[-1]["From"] == "whatsapp%3A%2B15550001111"


def test_lint_runs_again_at_dispatch_on_the_current_text(client, db, admin_headers, staff_headers, settings, live):
    c = contact(client, staff_headers)
    row = draft(client, staff_headers, c["id"], body="A private room is $850 a month.")
    approve(client, admin_headers, row["id"])
    settings.outbox_allowed_prices = "550"     # the confirmed list changed after approval
    rep = run(client, admin_headers)
    assert rep["held"] == 1 and live.email_transport.sent == []
    got = client.get(f"/api/outbox/{row['id']}", headers=staff_headers).json()
    assert got["status"] == "held" and got["hold_reason"] == "lint" and "unconfirmed price" in got["gate_log"][-1]["detail"]


def test_reply_threading_headers_only_for_smtp_message_ids(client, db, admin_headers, staff_headers, admin_id, live):
    c = contact(client, staff_headers)
    first = draft(client, staff_headers, c["id"])
    approve(client, admin_headers, first["id"])
    run(client, admin_headers)
    email_id = client.get(f"/api/outbox/{first['id']}", headers=staff_headers).json()["email_id"]
    reply = draft(client, staff_headers, c["id"], subject="Re: Your room question", body="Yes, Monday at 10 AM works.", in_reply_to_email_id=email_id)
    assert reply["thread_key"] == f"email:{email_id}"
    row = db.get(OutboxItem, reply["id"])
    assert reply_headers(db, row) == {}                      # Resend ids are not Message-IDs
    prior = db.get(Email, email_id)
    prior.provider, prior.provider_message_id = "smtp", "abc@gladewoodcommons.com"
    db.commit()
    assert reply_headers(db, row) == {"In-Reply-To": "<abc@gladewoodcommons.com>", "References": "<abc@gladewoodcommons.com>"}
    # a reply must point at the same contact's email
    other = contact(client, staff_headers, display_name="Resident B", email="b@example.test", phone="+14235550199")
    r = client.post("/api/outbox", json={"channel": "email", "contact_id": other["id"], "subject": "s", "body": "x", "in_reply_to_email_id": email_id}, headers=staff_headers)
    assert r.status_code == 422
    assert client.post("/api/outbox", json={"channel": "sms", "contact_id": c["id"], "body": "x", "in_reply_to_email_id": email_id}, headers=staff_headers).status_code == 422


def test_agents_can_only_draft_through_the_integration_key(client, db, admin_headers, staff_headers, settings, live):
    c = contact(client, staff_headers)
    body = {"channel": "email", "contact_id": c["id"], "subject": "Tour", "body": "A private room is $850 a month.", "agent": "Claude lane"}
    assert client.post("/api/integrations/outbox", json=body).status_code == 401
    r = client.post("/api/integrations/outbox", json=body, headers={"X-Api-Key": settings.integration_api_key})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft" and r.json()["lint"]["ok"] is True
    row = client.get(f"/api/outbox/{r.json()['id']}", headers=staff_headers).json()
    assert row["created_by"] == "agent:Claude lane" and row["approved_by"] is None
    # the key reaches nothing else on the queue
    assert client.post(f"/api/outbox/{row['id']}/approve", headers={"X-Api-Key": settings.integration_api_key}).status_code == 401
    assert run(client, admin_headers)["examined"] == 0          # a draft is never dispatched
    assert live.email_transport.sent == []


def test_list_filters_and_audit_rows_carry_no_text(client, db, admin_headers, staff_headers, live):
    c = contact(client, staff_headers)
    a = draft(client, staff_headers, c["id"])
    b = draft(client, staff_headers, c["id"], channel="sms", body="Short note.")
    approve(client, admin_headers, a["id"])
    assert [r["id"] for r in client.get("/api/outbox", params={"status": "approved"}, headers=staff_headers).json()] == [a["id"]]
    assert len(client.get("/api/outbox", params={"open_only": "true"}, headers=staff_headers).json()) == 2
    assert [r["id"] for r in client.get("/api/outbox", params={"thread_key": "+14235550100"}, headers=staff_headers).json()] == [b["id"]]
    run(client, admin_headers)
    from app.models import AuditLog
    rows = db.scalars(select(AuditLog).where(AuditLog.action.like("outbox.%"))).all()
    assert {r.action for r in rows} >= {"outbox.create", "outbox.approve", "outbox.sent"}
    for r in rows:
        assert "private room" not in json.dumps(r.details or {})
