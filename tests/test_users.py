def test_admin_can_change_roles_and_it_is_audited(client, db, admin_headers, pending_headers):
    pending = client.get("/api/me", headers=pending_headers).json()
    r = client.put(f"/api/users/{pending['id']}/role", json={"role": "staff"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["role"] == "staff"
    assert client.get("/api/properties", headers=pending_headers).status_code == 200


def test_invalid_role_rejected(client, admin_headers, pending_headers):
    pending = client.get("/api/me", headers=pending_headers).json()
    r = client.put(f"/api/users/{pending['id']}/role", json={"role": "superuser"}, headers=admin_headers)
    assert r.status_code == 422


def test_admin_cannot_change_own_role(client, admin_headers):
    me = client.get("/api/me", headers=admin_headers).json()
    r = client.put(f"/api/users/{me['id']}/role", json={"role": "staff"}, headers=admin_headers)
    assert r.status_code == 400


def test_staff_cannot_manage_users(client, staff_headers):
    assert client.get("/api/users", headers=staff_headers).status_code == 403
