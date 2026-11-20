from datetime import date, datetime, timedelta, timezone


from app.models import Deal, Message


def _deal(client, headers, p, title, stage=None, next_action=None, **extra):
    body = {"title": title, "pipeline_id": p.id, "next_action_at": (next_action or date.today()).isoformat(), **extra}
    if stage:
        body["stage_id"] = next(s.id for s in p.stages if s.name == stage)
    r = client.post("/api/deals", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_dashboard_counts(client, db, staff_headers, pipelines, settings):
    res, prop, part = pipelines["resident-inquiry"], pipelines["property"], pipelines["referral-partner"]
    web = client.post("/api/contacts", json={"display_name": "S. L.", "email": "s@x.test", "source": "web"}, headers=staff_headers).json()
    wa = client.post("/api/contacts", json={"display_name": "T. M.", "phone": "+14235550100", "source": "whatsapp"}, headers=staff_headers).json()
    d1 = _deal(client, staff_headers, res, "Inquiry: S. L.", contact_id=web["id"])
    d2 = _deal(client, staff_headers, res, "Inquiry: T. M.", contact_id=wa["id"], stage="Deposit received")
    _deal(client, staff_headers, res, "Inquiry: U. V.")
    client.post(f"/api/deals/{d1['id']}/move", json={"stage_id": next(s.id for s in res.stages if s.name == "Screened")}, headers=staff_headers)
    client.post(f"/api/deals/{d2['id']}/move", json={"stage_id": next(s.id for s in res.stages if s.is_won)}, headers=staff_headers)
    _deal(client, staff_headers, prop, "12 Pine St", next_action=date.today() - timedelta(days=3))
    quiet = _deal(client, staff_headers, part, "Partner: Bridge", next_action=date.today() + timedelta(days=30))
    row = db.get(Deal, quiet["id"])
    row.updated_at = datetime.now(timezone.utc) - timedelta(days=40)
    db.add(Message(channel="whatsapp", direction="in", phone="+14235550100", body="hi", contact_id=wa["id"]))
    client.post("/api/activities", json={"subject": "Old call", "due_at": "2026-01-01T09:00:00Z"}, headers=staff_headers)
    db.commit()
    r = client.get("/api/dashboard?days=30", headers=staff_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["inquiries_total"] == 3
    assert {x["source"]: x["count"] for x in d["inquiries_by_source"]} == {"web": 1, "whatsapp": 1, "other": 1}
    funnel = {f["stage"]: f for f in d["funnel"]}
    assert funnel["Inquiry"]["reached"] == 2 and funnel["Inquiry"]["open_now"] == 1
    assert funnel["Screened"]["reached"] == 1 and funnel["Screened"]["open_now"] == 1 and funnel["Screened"]["median_days_open"] == 0.0
    assert funnel["Moved in"]["reached"] == 1 and funnel["Moved in"]["open_now"] == 0
    assert d["conversion"] == {"inquiries": 3, "moved_in": 1, "closed_no_move_in": 0, "rate": 0.333}
    assert d["overdue_deals"] == 1 and d["overdue_deal_list"][0]["title"] == "12 Pine St" and d["overdue_deal_list"][0]["days"] == 3
    assert d["overdue_deal_list"][0]["pipeline"] == "property"
    assert d["overdue_activities"] == 1
    assert d["quiet_partners"] == 1 and d["quiet_partner_list"][0]["days"] >= 40
    assert d["channels"]["whatsapp_in"] == 1 and d["channels"]["emails_sent"] == 0
    assert d["demand"] == {"target": 6, "deposits": 0, "income_verified": 0, "moved_in": 1}
    assert client.get("/api/dashboard?days=0", headers=staff_headers).status_code == 422


def test_saved_views_crud_sharing_and_key_allowlist(client, db, staff_headers, admin_headers):
    client.get("/api/me", headers=admin_headers)
    r = client.post("/api/views", json={"entity": "contacts", "name": "Hot prospects", "filters": {"kind": "prospect", "tag": "hot"}}, headers=staff_headers)
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert r.json()["mine"] is True and r.json()["shared"] is True
    r = client.post("/api/views", json={"entity": "contacts", "name": "Bad", "filters": {"health": "x"}}, headers=staff_headers)
    assert r.status_code == 422 and "health" in r.text
    r = client.post("/api/views", json={"entity": "deals", "name": "My overdue", "filters": {"mine": True, "overdue": True}, "shared": False}, headers=admin_headers)
    assert r.status_code == 201
    private_id = r.json()["id"]
    names = [v["name"] for v in client.get("/api/views", headers=staff_headers).json()]
    assert names == ["Hot prospects"]  # the admin's private view is hidden from staff
    assert [v["mine"] for v in client.get("/api/views?entity=deals", headers=admin_headers).json()] == [True]
    r = client.put(f"/api/views/{vid}", json={"entity": "contacts", "name": "Hot", "filters": {"tag": "hot"}}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["name"] == "Hot" and r.json()["mine"] is False  # admin may edit anyone's
    assert client.delete(f"/api/views/{private_id}", headers=staff_headers).status_code == 404  # not visible, not deletable
    assert client.delete(f"/api/views/{vid}", headers=staff_headers).json() == {"deleted": 1}
