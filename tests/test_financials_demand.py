def test_financials_roundtrip_ignores_unknown_keys(client, staff_headers):
    r = client.put("/api/financials", json={"values": {"lease_rent": "2000", "bogus": "1"}}, headers=staff_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["lease_rent"] == "2000" and "bogus" not in body
    assert client.get("/api/financials", headers=staff_headers).json()["lease_rent"] == "2000"


def test_demand_summary_counts_screened_and_verified_separately(client, staff_headers):
    client.post("/api/prospects", json={"status": "Inquiry"}, headers=staff_headers)
    client.post("/api/prospects", json={"status": "Screened"}, headers=staff_headers)
    client.post("/api/prospects", json={"status": "Confirmed", "income_verified": "Verified"}, headers=staff_headers)
    s = client.get("/api/demand-summary", headers=staff_headers).json()
    assert s == {"raw_inquiries": 3, "screened": 2, "income_verified": 1, "holding_deposit": 1, "target": 6}


def test_demand_target_comes_from_financials(client, staff_headers):
    client.put("/api/financials", json={"values": {"demand_target": "9"}}, headers=staff_headers)
    assert client.get("/api/demand-summary", headers=staff_headers).json()["target"] == 9
