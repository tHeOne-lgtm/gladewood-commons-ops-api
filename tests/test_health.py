def test_health_reports_db_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "db": True}


def test_health_needs_no_auth(client):
    assert client.get("/api/health").status_code == 200
