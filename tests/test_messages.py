import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.models import Consent, Contact, Deal, Message
from app.twilio import compute_signature, normalize_phone

TOKEN = "twilio-test-token"
IN_URL = "http://testserver/api/webhooks/twilio/whatsapp"
STATUS_URL = "http://testserver/api/webhooks/twilio/status"


def _post_twilio(client, url, params, sign=True):
    headers = {"X-Twilio-Signature": compute_signature(TOKEN, url, params)} if sign else {}
    return client.post(url.replace("http://testserver", ""), data=params, headers=headers)


def inbound(client, phone="+14235550100", body="Hi, is a private room available?", sid="SM1", profile="Sam"):
    return _post_twilio(client, IN_URL, {"From": f"whatsapp:{phone}", "To": "whatsapp:+15550001111", "Body": body,
                                        "MessageSid": sid, "NumMedia": "0", "ProfileName": profile})


def test_normalize_phone():
    assert normalize_phone("whatsapp:+1 (423) 555-0100") == "+14235550100"
    assert normalize_phone("423-555-0100") == "+14235550100"
    assert normalize_phone("14235550100") == "+14235550100"
    assert normalize_phone("") == ""


def test_bad_signature_is_rejected(client, db):
    r = _post_twilio(client, IN_URL, {"From": "whatsapp:+14235550100", "Body": "hi", "MessageSid": "SMx"}, sign=False)
    assert r.status_code == 403
    assert db.scalar(select(Message)) is None


def test_inbound_creates_contact_consent_message_and_inquiry(client, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)  # an admin exists to own automation-created deals
    r = inbound(client)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    c = db.scalar(select(Contact))
    assert c.phone == "+14235550100" and c.kind == "prospect" and c.source == "whatsapp" and c.display_name == "WhatsApp 0100"
    assert db.scalar(select(Consent).where(Consent.contact_id == c.id, Consent.consent_type == "whatsapp")).withdrawn_at is None
    m = db.scalar(select(Message))
    assert m.direction == "in" and m.contact_id == c.id and m.status == "received" and m.read_at is None
    d = db.scalar(select(Deal))
    assert d.contact_id == c.id and d.status == "open" and d.title.startswith("WhatsApp inquiry") and m.deal_id == d.id
    tags = client.get(f"/api/contacts/{c.id}", headers=staff_headers).json()["tags"]
    assert tags == ["src-whatsapp"]
    # Twilio retry with the same SID is a no-op
    assert inbound(client).status_code == 200
    assert len(db.scalars(select(Message)).all()) == 1


def test_inbound_matches_existing_contact_by_phone_and_does_not_duplicate_open_deal(client, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    existing = client.post("/api/contacts", json={"display_name": "Resident A", "phone": "(423) 555-0100"}, headers=staff_headers).json()
    inbound(client, sid="SM1")
    inbound(client, sid="SM2", body="Following up")
    assert len(db.scalars(select(Contact)).all()) == 1
    assert db.scalar(select(Message)).contact_id == existing["id"]
    assert len(db.scalars(select(Deal)).all()) == 1


def test_stop_withdraws_consent_and_blocks_sending(client, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    inbound(client, sid="SM1")
    inbound(client, sid="SM2", body="STOP")
    c = db.scalar(select(Contact))
    consent = db.scalar(select(Consent).where(Consent.contact_id == c.id))
    assert consent.withdrawn_at is not None and consent.withdrawn_by == "contact"
    r = client.post("/api/messages/whatsapp", json={"contact_id": c.id, "body": "Hello"}, headers=staff_headers)
    assert r.status_code == 409 and "STOP" in r.json()["detail"]


def test_conversations_thread_read_and_send(client, app, db, admin_headers, staff_headers, staff_user, pipelines):
    client.get("/api/me", headers=admin_headers)
    inbound(client, sid="SM1")
    inbound(client, phone="+14235550199", sid="SM2", body="Hello?", profile="Lee")
    convos = client.get("/api/conversations", headers=staff_headers).json()
    assert [c["phone"] for c in convos] == ["+14235550199", "+14235550100"]
    assert convos[0]["unread_count"] == 1 and convos[0]["window_open"] and convos[0]["consent_active"]

    thread = client.get("/api/conversations/+14235550100/messages", headers=staff_headers).json()
    assert [m["direction"] for m in thread] == ["in"]
    assert client.post("/api/conversations/+14235550100/read", headers=staff_headers).json() == {"marked": 1}

    sent = []
    def handler(req: httpx.Request):
        sent.append(req)
        return httpx.Response(201, json={"sid": "SMout1", "status": "queued"})
    app.state.twilio_transport = httpx.MockTransport(handler)
    r = client.post("/api/messages/whatsapp", json={"phone": "+14235550100", "body": "Yes, a private room opens Dec 1."}, headers=staff_headers)
    assert r.status_code == 201, r.text
    assert r.json()["direction"] == "out" and r.json()["status"] == "queued" and r.json()["sent_by"] == staff_user.id
    form = dict(x.split("=") for x in sent[0].content.decode().split("&"))
    assert form["From"] == "whatsapp%3A%2B15550001111" and form["To"] == "whatsapp%3A%2B14235550100"
    assert "StatusCallback" in form and sent[0].headers["authorization"].startswith("Basic ")

    # delivery status callback
    r = _post_twilio(client, STATUS_URL, {"MessageSid": "SMout1", "MessageStatus": "delivered"})
    assert r.status_code == 204
    assert db.scalar(select(Message).where(Message.provider_sid == "SMout1")).status == "delivered"

    # outbound shows on the contact timeline
    c = db.scalar(select(Contact).where(Contact.phone == "+14235550100"))
    types = [i["type"] for i in client.get("/api/timeline", params={"entity": "contact", "entity_id": c.id}, headers=staff_headers).json()]
    assert "message.in" in types and "message.out" in types


def test_send_outside_window_needs_opt_in_flag(client, app, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    inbound(client, sid="SM1")
    m = db.scalar(select(Message))
    m.created_at = datetime.now(timezone.utc) - timedelta(hours=30)
    db.commit()
    r = client.post("/api/messages/whatsapp", json={"phone": "+14235550100", "body": "Hi"}, headers=staff_headers)
    assert r.status_code == 409 and "24 hours" in r.json()["detail"]
    app.state.twilio_transport = httpx.MockTransport(lambda req: httpx.Response(201, json={"sid": "SMo", "status": "queued"}))
    r = client.post("/api/messages/whatsapp", json={"phone": "+14235550100", "body": "Hi", "allow_outside_window": True}, headers=staff_headers)
    assert r.status_code == 201


def test_twilio_error_is_reported(client, app, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    inbound(client, sid="SM1")
    app.state.twilio_transport = httpx.MockTransport(lambda req: httpx.Response(400, json={"message": "Not a valid WhatsApp number"}))
    r = client.post("/api/messages/whatsapp", json={"phone": "+14235550100", "body": "Hi"}, headers=staff_headers)
    assert r.status_code == 502 and "Not a valid WhatsApp number" in r.json()["detail"]
    assert json.dumps(r.json())  # body is JSON


# ---- plain SMS on the same route (Atlas gap 1, 2026-11-21) ----
def sms_inbound(client, phone="+14235550199", body="Is a room open?", sid="SMS1", path="/api/webhooks/twilio/sms"):
    return _post_twilio(client, "http://testserver" + path, {"From": phone, "To": "+15550001111", "Body": body, "MessageSid": sid, "NumMedia": "0"})


def test_sms_is_its_own_channel_on_either_path(client, db, admin_headers, staff_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    r = sms_inbound(client)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    c = db.scalar(select(Contact))
    assert c.source == "sms" and c.display_name == "SMS 0199" and c.extra == {}
    assert client.get(f"/api/contacts/{c.id}", headers=staff_headers).json()["tags"] == ["src-sms"]
    m = db.scalar(select(Message))
    assert m.channel == "sms" and m.direction == "in"
    assert db.scalar(select(Consent).where(Consent.contact_id == c.id)).consent_type == "sms"
    d = db.scalar(select(Deal))
    assert d.title.startswith("SMS inquiry") and d.extra["source"] == "sms"
    # the WhatsApp path accepts a plain number too, and the retry rule still holds
    assert sms_inbound(client, sid="SMS1", path="/api/webhooks/twilio/whatsapp").status_code == 200
    assert len(db.scalars(select(Message)).all()) == 1


def test_sms_stop_withdraws_only_the_sms_consent(client, db, admin_headers, pipelines):
    client.get("/api/me", headers=admin_headers)
    sms_inbound(client, sid="SMS1")
    inbound(client, phone="+14235550199", sid="WA1")      # the same person on WhatsApp
    sms_inbound(client, sid="SMS2", body="STOP")
    rows = {r.consent_type: r for r in db.scalars(select(Consent)).all()}
    assert rows["sms"].withdrawn_at is not None and rows["whatsapp"].withdrawn_at is None
