from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.automations import run_automations
from app.models import Activity, AutomationRun, Deal


def _stage(p, name):
    return next(s for s in p.stages if s.name == name)


def _deal(client, headers, p, title, stage=None, next_action=None, **extra):
    body = {"title": title, "pipeline_id": p.id, "next_action_at": (next_action or date.today()).isoformat()}
    if stage:
        body["stage_id"] = _stage(p, stage).id
    body.update(extra)
    r = client.post("/api/deals", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_inquiry_callback_once_and_dry_run_writes_nothing(client, db, staff_headers, pipelines):
    p = pipelines["resident-inquiry"]
    d = _deal(client, staff_headers, p, "Inquiry: S. L.")
    rep = run_automations(db, dry_run=True)
    assert rep.counts["inquiry_callback"] == 1 and db.scalar(select(Activity)) is None and db.scalar(select(AutomationRun)) is None
    rep = run_automations(db)
    assert rep.counts["inquiry_callback"] == 1
    a = db.scalar(select(Activity))
    assert a.subject == "Call back new inquiry" and a.deal_id == d["id"] and a.assigned_to == d["owner_id"]
    assert run_automations(db).counts["inquiry_callback"] == 0  # idempotent
    # a deal that already has an open activity is left alone
    d2 = _deal(client, staff_headers, p, "Inquiry: T. M.")
    client.post("/api/activities", json={"subject": "Called already", "deal_id": d2["id"]}, headers=staff_headers)
    assert run_automations(db).counts["inquiry_callback"] == 0


def test_tour_event_and_application_review(client, db, staff_headers, pipelines):
    p = pipelines["resident-inquiry"]
    tour = _deal(client, staff_headers, p, "Inquiry: A. R.", stage="Tour scheduled", next_action=date.today() + timedelta(days=2))
    review = _deal(client, staff_headers, p, "Inquiry: B. K.", stage="Income verified")
    rep = run_automations(db)
    assert rep.counts["tour_event"] == 1 and rep.counts["application_review"] == 1
    ev = db.scalar(select(Activity).where(Activity.deal_id == tour["id"], Activity.kind == "event"))
    assert ev.subject.startswith("Tour:") and ev.due_at.date() == date.today() + timedelta(days=2)
    rv = db.scalar(select(Activity).where(Activity.deal_id == review["id"]))
    assert rv.subject.startswith("Review application")
    assert run_automations(db).counts["tour_event"] == 0


def test_stale_escalation_sets_flag_then_clears(client, db, staff_headers, pipelines):
    p = pipelines["property"]
    d = _deal(client, staff_headers, p, "12 Pine St", next_action=date.today() - timedelta(days=6))
    rep = run_automations(db)
    assert rep.counts["stale_escalation"] == 1
    row = db.get(Deal, d["id"])
    assert row.extra["escalation_flag"] is True
    task = db.scalar(select(Activity).where(Activity.deal_id == d["id"]))
    assert task.priority == "high" and "Escalation" in task.subject
    assert run_automations(db).counts["stale_escalation"] == 0  # not twice for the same overdue date
    # staff sets a new next action: the flag clears on the next run
    row.next_action_at = date.today() + timedelta(days=1)
    db.commit()
    rep = run_automations(db)
    assert [a.action for a in rep.actions if a.rule == "stale_escalation"] == ["clear_flag"]
    assert db.get(Deal, d["id"]).extra["escalation_flag"] is False


def test_partner_checkin_after_30_quiet_days(client, db, staff_headers, pipelines):
    p = pipelines["referral-partner"]
    d = _deal(client, staff_headers, p, "Partner: Bridge Agency", stage="Engaged", next_action=date.today() + timedelta(days=40))
    assert run_automations(db).counts["partner_checkin"] == 0  # fresh deal
    row = db.get(Deal, d["id"])
    row.updated_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    rep = run_automations(db)
    assert rep.counts["partner_checkin"] == 1
    assert db.scalar(select(Activity).where(Activity.deal_id == d["id"])).subject.startswith("Check in with partner")
    row.updated_at = datetime.now(timezone.utc) - timedelta(days=31)
    db.commit()
    assert run_automations(db).counts["partner_checkin"] == 0  # once per 30 days


def test_run_endpoint_and_rules_listing(client, db, staff_headers, pipelines):
    p = pipelines["resident-inquiry"]
    _deal(client, staff_headers, p, "Inquiry: C. D.")
    r = client.post("/api/automations/run", params={"dry_run": True}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["dry_run"] and r.json()["counts"]["inquiry_callback"] == 1
    r = client.post("/api/automations/run", headers=staff_headers)
    assert r.json()["counts"]["inquiry_callback"] == 1
    rules = client.get("/api/automations/rules", headers=staff_headers).json()
    assert next(x for x in rules if x["rule"] == "inquiry_callback")["last_fired_at"] is not None
