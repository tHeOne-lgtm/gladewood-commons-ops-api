from sqlalchemy import select

from app.models import AuditLog


def test_property_lifecycle_with_audit(client, db, staff_headers, staff_user):
    r = client.post("/api/properties", json={"address": "123 Test St", "rent": "1500"}, headers=staff_headers)
    assert r.status_code == 201
    row = r.json()
    assert row["address"] == "123 Test St" and row["status"] == "Not sourced yet"
    rid = row["id"]

    r = client.put(f"/api/properties/{rid}", json={**row, "status": "Contacted"}, headers=staff_headers)
    assert r.status_code == 200 and r.json()["status"] == "Contacted"

    listed = client.get("/api/properties", headers=staff_headers).json()
    assert [p["id"] for p in listed] == [rid]

    r = client.delete(f"/api/properties/{rid}", headers=staff_headers)
    assert r.status_code == 200 and r.json() == {"deleted": rid}
    assert client.get("/api/properties", headers=staff_headers).json() == []

    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "property")).all()]
    assert actions == ["property.create", "property.update", "property.delete"]
    update = db.scalars(select(AuditLog).where(AuditLog.action == "property.update")).one()
    assert update.details == {"changes": {"status": ["Not sourced yet", "Contacted"]}}
    assert update.actor_id == staff_user.id


def test_update_missing_row_is_404(client, staff_headers):
    r = client.put("/api/properties/999", json={"address": "x"}, headers=staff_headers)
    assert r.status_code == 404


def test_delete_missing_row_is_404(client, staff_headers):
    assert client.delete("/api/properties/999", headers=staff_headers).status_code == 404


def test_pagination(client, staff_headers):
    for i in range(3):
        client.post("/api/prospects", json={"initials": f"P{i}"}, headers=staff_headers)
    page = client.get("/api/prospects", params={"limit": 2, "offset": 1}, headers=staff_headers).json()
    assert [p["initials"] for p in page] == ["P1", "P2"]
    assert client.get("/api/prospects", params={"limit": 0}, headers=staff_headers).status_code == 422


def test_all_legacy_routes_exist(client, staff_headers):
    for path in ("/api/properties", "/api/prospects", "/api/residents", "/api/conflict-log"):
        assert client.get(path, headers=staff_headers).status_code == 200, path


def test_pending_user_cannot_write(client, pending_headers):
    assert client.post("/api/residents", json={"initials": "ZZ"}, headers=pending_headers).status_code == 403
