from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.campaigns import send_due
from app.models import Campaign, Email
from app.seed import seed_default_email_templates
from tests.test_email import FakeResend, _consent, _contact


@pytest.fixture
def resend(app):
    t = FakeResend()
    app.state.email_transport = t
    return t


@pytest.fixture
def partner_template(db):
    seed_default_email_templates(db)
    db.commit()
    from app.models import EmailTemplate
    return db.scalar(select(EmailTemplate).where(EmailTemplate.name == "Monthly partner update"))


def _partners(client, headers):
    co = client.post("/api/companies", json={"name": "Bridge Agency", "kind": "agency"}, headers=headers).json()
    a = _contact(client, headers, email="a@b.test", kind="case_manager", company_id=co["id"])
    b = _contact(client, headers, email="b@b.test", kind="case_manager", company_id=co["id"])
    c = _contact(client, headers, email="", kind="case_manager", company_id=co["id"])      # no email
    d = _contact(client, headers, email="d@x.test", kind="prospect")                        # not a partner
    client.put(f"/api/contacts/{a['id']}/tags", json={"tags": ["referral"]}, headers=headers)
    client.put(f"/api/contacts/{b['id']}/tags", json={"tags": ["referral", "do-not-email"]}, headers=headers)
    _consent(client, headers, a["id"])
    _consent(client, headers, d["id"])
    return a, b, c, d


def test_segment_forbids_unknown_keys(client, staff_headers, partner_template):
    r = client.post("/api/campaigns", json={"name": "x", "template_id": partner_template.id, "segment": {"health": ["x"]}}, headers=staff_headers)
    assert r.status_code == 422
    r = client.post("/api/campaigns", json={"name": "x", "template_id": partner_template.id, "segment": {"contact_kind": ["case_manager"], "tags_none": ["do-not-email"]}}, headers=staff_headers)
    assert r.status_code == 201 and r.json()["status"] == "draft" and r.json()["template_name"] == "Monthly partner update"


def test_campaign_preview_send_report_and_idempotent_rerun(client, db, staff_headers, partner_template, resend, settings):
    a, b, c, d = _partners(client, staff_headers)
    r = client.post("/api/campaigns", json={"name": "November partners", "template_id": partner_template.id,
                                             "segment": {"contact_kind": ["case_manager"], "company_kind": ["agency"]}}, headers=staff_headers)
    cid = r.json()["id"]
    pv = client.post(f"/api/campaigns/{cid}/preview", headers=staff_headers).json()
    assert pv["total"] == 3 and pv["sendable"] == 1 and pv["skipped"] == {"no_consent": 1, "no_email": 1}
    assert "Hi Sam" in pv["body_text"] and "Unsubscribe:" in pv["body_text"]
    rep = client.post(f"/api/campaigns/{cid}/send", headers=staff_headers).json()
    assert rep["status"] == "sent" and rep["counts"] == {"sent": 1, "skipped": 2}
    assert len(resend.sent) == 1 and resend.sent[0]["to"] == ["a@b.test"]
    assert client.post(f"/api/campaigns/{cid}/send", headers=staff_headers).status_code == 409
    rows = db.scalars(select(Email).where(Email.campaign_id == cid)).all()
    assert {r.contact_id: r.status for r in rows} == {a["id"]: "sent", b["id"]: "skipped", c["id"]: "skipped"}
    # unsubscribe after the send shows in the report
    from app.emailing import unsubscribe_token
    client.post(f"/api/email/unsubscribe/{unsubscribe_token(settings, a['id'])}")
    rep = client.get(f"/api/campaigns/{cid}/report", headers=staff_headers).json()
    assert rep["unsubscribed_after"] == 1
    assert client.put(f"/api/campaigns/{cid}", json={"name": "x", "template_id": partner_template.id}, headers=staff_headers).status_code == 409


def test_scheduled_campaign_sends_when_due_and_cancel(client, db, staff_headers, partner_template, resend, settings):
    a, b, c, d = _partners(client, staff_headers)
    r = client.post("/api/campaigns", json={"name": "Later", "template_id": partner_template.id, "scheduled_at": "2026-11-21T15:00:00Z",
                                             "segment": {"tags_any": ["referral"], "tags_none": ["do-not-email"]}}, headers=staff_headers)
    assert r.json()["status"] == "scheduled"
    cid = r.json()["id"]
    assert send_due(db, settings, now=datetime(2026, 11, 21, 14, 0, tzinfo=timezone.utc)) == []
    settings.email_provider = "log"  # the cron path has no app state to hold a fake transport
    out = send_due(db, settings, now=datetime(2026, 11, 21, 15, 1, tzinfo=timezone.utc))
    settings.email_provider = "resend"
    assert len(out) == 1 and out[0].counts == {"sent": 1}
    assert db.get(Campaign, cid).status == "sent"
    r = client.post("/api/campaigns", json={"name": "Cancel me", "template_id": partner_template.id}, headers=staff_headers)
    r = client.post(f"/api/campaigns/{r.json()['id']}/cancel", headers=staff_headers)
    assert r.json()["status"] == "cancelled"
