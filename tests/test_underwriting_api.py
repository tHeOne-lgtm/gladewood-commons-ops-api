import math

from sqlalchemy import select

from app import underwriting as uw
from app.models import AuditLog, Underwriting


def _property(client, headers, address="12 Example St"):
    return client.post("/api/properties", json={"address": address}, headers=headers).json()["id"]


def test_routes_need_staff(client, pending_headers):
    assert client.get("/api/underwriting").status_code == 401
    assert client.get("/api/underwriting/settings", headers=pending_headers).status_code == 403
    assert client.put("/api/underwriting/1", json={}, headers=pending_headers).status_code == 403
    assert client.post("/api/underwriting/1/stage", json={"stage": "Toured"}, headers=pending_headers).status_code == 403


def test_settings_defaults_update_and_reject_unknown(client, staff_headers, db):
    s = client.get("/api/underwriting/settings", headers=staff_headers).json()
    assert s == uw.DEFAULT_SETTINGS
    r = client.put("/api/underwriting/settings", json={"values": {"planPrivate": 1000, "uwMinCash": 350}}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["planPrivate"] == 1000 and r.json()["uwMinCash"] == 350 and r.json()["planShared"] == 600
    assert client.put("/api/underwriting/settings", json={"values": {"nope": 1}}, headers=staff_headers).status_code == 422
    assert client.put("/api/underwriting/settings", json={"values": {"planPrivate": "abc"}}, headers=staff_headers).status_code == 422
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "underwriting.settings")).one()
    assert audit.details["changes"] == {"planPrivate": [950, 1000], "uwMinCash": [300, 350]}


def test_unknown_property_is_404(client, staff_headers):
    assert client.get("/api/underwriting/999", headers=staff_headers).status_code == 404
    assert client.put("/api/underwriting/999", json={"lease_cost": 1}, headers=staff_headers).status_code == 404
    assert client.post("/api/underwriting/999/stage", json={"stage": "Toured"}, headers=staff_headers).status_code == 404


def test_get_before_any_edit_shows_defaults_and_missing(client, staff_headers):
    pid = _property(client, staff_headers)
    r = client.get(f"/api/underwriting/{pid}", headers=staff_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False and body["stage"] == "Found" and body["deal_type"] == "lease"
    assert body["missing"] == ["planned rooms or bedrooms", "monthly lease cost"] and body["calc"] is None
    assert body["resolved"]["privRent"] == 950
    assert client.get(f"/api/underwriting/{pid}/summary.txt", headers=staff_headers).status_code == 409
    assert client.get(f"/api/underwriting/{pid}/export.csv", headers=staff_headers).status_code == 409


def test_upsert_computes_like_the_math_module(client, staff_headers, db):
    pid = _property(client, staff_headers)
    payload = {"private_rooms": 3, "shared_rooms": 1, "lease_cost": "1800", "inputs": {"occ": "85", "internet": 90, "makeReady": ""}}
    r = client.put(f"/api/underwriting/{pid}", json=payload, headers=staff_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True and body["inputs"] == {"occ": 85, "internet": 90} and body["missing"] == []
    i = uw.resolve_inputs({"privateRooms": 3, "sharedRooms": 1, "leaseCost": 1800}, {"occ": 85, "internet": 90})
    c = uw.calc(i)
    assert math.isclose(body["calc"]["cash"], c["cash"]) and body["resolved"]["beds"] == 5
    assert len(body["checks"]) == 4 and set(body["scenarios"]) == {"cons", "base", "up"} and len(body["projection"]) == 5
    # a second PUT updates in place and leaves untouched fields alone
    r = client.put(f"/api/underwriting/{pid}", json={"notes": "quote from owner pending"}, headers=staff_headers)
    assert r.json()["notes"] == "quote from owner pending" and r.json()["lease_cost"] == "1800.00"
    assert db.scalar(select(Underwriting).where(Underwriting.property_id == pid)).private_rooms == 3
    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "underwriting")).all()]
    assert actions == ["underwriting.create", "underwriting.update"]
    update = db.scalars(select(AuditLog).where(AuditLog.action == "underwriting.update")).one()
    assert update.details["changes"] == {"notes": ["", "quote from owner pending"]}


def test_inputs_are_filtered_and_validated(client, staff_headers):
    pid = _property(client, staff_headers)
    assert client.put(f"/api/underwriting/{pid}", json={"inputs": {"secret": 1}}, headers=staff_headers).status_code == 422
    assert client.put(f"/api/underwriting/{pid}", json={"inputs": {"occ": "high"}}, headers=staff_headers).status_code == 422
    assert client.put(f"/api/underwriting/{pid}", json={"deal_type": "rent"}, headers=staff_headers).status_code == 422
    assert client.put(f"/api/underwriting/{pid}", json={"private_rooms": -1}, headers=staff_headers).status_code == 422
    assert client.put(f"/api/underwriting/{pid}", json={"inputs": {"mode": "buy"}}, headers=staff_headers).status_code == 200


def test_buy_mode_uses_sale_price_and_cap_rate_check(client, staff_headers):
    pid = _property(client, staff_headers)
    r = client.put(f"/api/underwriting/{pid}", json={"deal_type": "buy", "bedrooms": 4, "sale_price": 285000,
                                                     "inputs": {"downPct": 20, "rate": 6.5, "taxAnnual": 2400, "insAnnual": 1800}},
                   headers=staff_headers)
    body = r.json()
    assert body["resolved"]["mode"] == "buy" and body["resolved"]["price"] == 285000 and body["resolved"]["beds"] == 4
    assert [c["label"] for c in body["checks"]][-1] == "Cap rate" and body["calc"]["pmt"] > 0


def test_stage_change_is_logged_and_validated(client, staff_headers, db):
    pid = _property(client, staff_headers)
    assert client.post(f"/api/underwriting/{pid}/stage", json={"stage": "Signed"}, headers=staff_headers).status_code == 422
    r = client.post(f"/api/underwriting/{pid}/stage", json={"stage": "Underwriting"}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["stage"] == "Underwriting" and r.json()["stage_changed_at"]
    r = client.post(f"/api/underwriting/{pid}/stage", json={"stage": "Underwriting"}, headers=staff_headers)
    assert r.status_code == 200
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "underwriting.stage")).all()
    assert len(logs) == 1 and logs[0].details["changes"] == {"stage": ["Found", "Underwriting"]}


def test_list_summaries_and_exports(client, staff_headers):
    a = _property(client, staff_headers, "9 Alpha Ave")
    b = _property(client, staff_headers, "4 Beta Blvd")
    client.put(f"/api/underwriting/{a}", json={"private_rooms": 3, "lease_cost": 1500}, headers=staff_headers)
    rows = client.get("/api/underwriting", headers=staff_headers).json()
    assert [r["address"] for r in rows] == ["4 Beta Blvd", "9 Alpha Ave"]
    beta, alpha = rows
    assert beta["property_id"] == b and beta["cash"] is None and beta["missing"]
    assert alpha["targets"] == 4 and alpha["cash"] is not None and alpha["missing"] == []
    txt = client.get(f"/api/underwriting/{a}/summary.txt", headers=staff_headers)
    assert txt.status_code == 200 and txt.text.startswith("Underwriting: 9 Alpha Ave (master lease, 3 beds)")
    csv_r = client.get(f"/api/underwriting/{a}/export.csv", headers=staff_headers)
    assert csv_r.status_code == 200 and csv_r.headers["content-type"].startswith("text/csv")
    lines = csv_r.text.strip().splitlines()
    assert lines[0] == "Item,Value" and lines[1] == "Property,9 Alpha Ave" and lines[-1].startswith("Upside cash flow / mo,")


def test_deleting_the_property_removes_its_underwriting(client, staff_headers, db):
    pid = _property(client, staff_headers)
    client.put(f"/api/underwriting/{pid}", json={"private_rooms": 2, "lease_cost": 900}, headers=staff_headers)
    assert client.delete(f"/api/properties/{pid}", headers=staff_headers).status_code == 200
    db.expire_all()
    assert db.scalar(select(Underwriting).where(Underwriting.property_id == pid)) is None


def test_occ_query_is_a_what_if_that_is_never_stored(client, staff_headers):
    prop = _property(client, staff_headers)
    client.put(f"/api/underwriting/{prop}", json={"private_rooms": 4, "lease_cost": 1800}, headers=staff_headers)
    saved = client.get(f"/api/underwriting/{prop}", headers=staff_headers).json()
    low = client.get(f"/api/underwriting/{prop}", params={"occ": 50}, headers=staff_headers).json()
    assert low["resolved"]["occ"] == 50 and low["calc"]["cash"] < saved["calc"]["cash"]
    assert client.get(f"/api/underwriting/{prop}", headers=staff_headers).json()["resolved"]["occ"] == saved["resolved"]["occ"]
    assert client.get(f"/api/underwriting/{prop}", params={"occ": 101}, headers=staff_headers).status_code == 422
