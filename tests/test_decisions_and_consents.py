"""Comparison item 5: append-only decision log with a protected-trait guard, and consents with withdraw."""
from datetime import date, timedelta

from sqlalchemy import select

from app.consents import has_consent
from app.fair_housing import protected_term_hits
from app.models import AuditLog, DecisionLog


def _contact(client, headers, name="Prospect P"):
    return client.post("/api/contacts", json={"display_name": name, "kind": "prospect"}, headers=headers).json()["id"]


def test_guard_matches_whole_words_only():
    assert protected_term_hits("income below the written 2.5x threshold; references not returned") == []
    assert protected_term_hits("terrace apartment, careful review") == []   # 'race' and 'care' inside words
    assert protected_term_hits("Declined: disability and no Voucher") == ["disability", "voucher"]
    assert protected_term_hits("needs emotional support animal") == ["emotional support"]


def test_decision_is_created_with_retention_and_audit(client, db, staff_headers, staff_user):
    cid = _contact(client, staff_headers)
    r = client.post("/api/decisions", json={"entity": "contact", "entity_id": cid, "criteria_version": "2026-11",
                                            "criteria_met": False, "outcome": "declined",
                                            "reason": "Income criterion not met per written criteria 2026-11"},
                    headers=staff_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decided_by"] == staff_user.id and body["outcome"] == "declined"
    assert date.fromisoformat(body["retain_until"]) >= date.today() + timedelta(days=730)
    assert client.get(f"/api/decisions?entity=contact&entity_id={cid}", headers=staff_headers).json()[0]["id"] == body["id"]
    assert client.get(f"/api/decisions/{body['id']}", headers=staff_headers).status_code == 200
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "decision.create")).all()
    assert len(audit) == 1 and audit[0].details["entity_id"] == cid


def test_decision_refuses_protected_trait_in_reason(client, db, staff_headers):
    cid = _contact(client, staff_headers)
    r = client.post("/api/decisions", json={"entity": "contact", "entity_id": cid, "criteria_version": "2026-11",
                                            "criteria_met": False, "outcome": "declined",
                                            "reason": "Declined because of a medical condition"},
                    headers=staff_headers)
    assert r.status_code == 422
    assert r.json()["detail"]["terms"] == ["medical"]
    assert db.scalar(select(DecisionLog)) is None


def test_decision_has_no_edit_or_delete_routes(client, staff_headers, admin_headers):
    cid = _contact(client, staff_headers)
    did = client.post("/api/decisions", json={"entity": "contact", "entity_id": cid, "criteria_version": "v1",
                                              "criteria_met": True, "outcome": "approved",
                                              "reason": "All written criteria met"}, headers=staff_headers).json()["id"]
    assert client.put(f"/api/decisions/{did}", json={}, headers=admin_headers).status_code == 405
    assert client.delete(f"/api/decisions/{did}", headers=admin_headers).status_code == 405
    assert client.patch(f"/api/decisions/{did}", json={}, headers=admin_headers).status_code == 405


def test_decision_needs_existing_record_and_staff(client, staff_headers, pending_headers):
    r = client.post("/api/decisions", json={"entity": "deal", "entity_id": 999, "criteria_version": "v1",
                                            "criteria_met": True, "outcome": "approved", "reason": "All criteria met"},
                    headers=staff_headers)
    assert r.status_code == 422 and "does not exist" in r.json()["detail"]
    assert client.get("/api/decisions", headers=pending_headers).status_code == 403


def test_consent_record_list_withdraw(client, db, staff_headers, staff_user):
    cid = _contact(client, staff_headers)
    r = client.post("/api/consents", json={"contact_id": cid, "consent_type": "sms", "source": "form"},
                    headers=staff_headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["active"] is True and body["recorded_by"] == staff_user.id
    assert has_consent(db, cid, "sms") and not has_consent(db, cid, "email")
    # a second active consent of the same type is refused
    dup = client.post("/api/consents", json={"contact_id": cid, "consent_type": "sms", "source": "phone"},
                      headers=staff_headers)
    assert dup.status_code == 409
    w = client.post(f"/api/consents/{body['id']}/withdraw", headers=staff_headers)
    assert w.status_code == 200 and w.json()["active"] is False and w.json()["withdrawn_by"] == staff_user.id
    assert not has_consent(db, cid, "sms")
    assert client.post(f"/api/consents/{body['id']}/withdraw", headers=staff_headers).status_code == 409
    # a new consent can be recorded after withdrawal; the history keeps both rows
    again = client.post("/api/consents", json={"contact_id": cid, "consent_type": "sms", "source": "phone"},
                        headers=staff_headers)
    assert again.status_code == 201
    rows = client.get(f"/api/consents?contact_id={cid}", headers=staff_headers).json()
    assert len(rows) == 2
    active = client.get(f"/api/consents?contact_id={cid}&active_only=true", headers=staff_headers).json()
    assert [r["id"] for r in active] == [again.json()["id"]]
    actions = sorted(a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "consent")).all())
    assert actions == ["consent.record", "consent.record", "consent.withdraw"]


def test_consent_needs_existing_contact(client, staff_headers):
    r = client.post("/api/consents", json={"contact_id": 999, "consent_type": "email", "source": "form"},
                    headers=staff_headers)
    assert r.status_code == 422
