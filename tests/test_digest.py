from datetime import date, timedelta

from app.digest import send_digest


def test_digest_sends_only_to_staff_with_items(client, db, staff_headers, staff_user, pipelines, settings):
    settings.email_provider = "log"
    try:
        assert send_digest(db, settings)["sent"] == []  # nothing due
        p = pipelines["property"]
        client.post("/api/deals", json={"title": "12 Pine St", "pipeline_id": p.id, "next_action_at": (date.today() - timedelta(days=1)).isoformat()}, headers=staff_headers)
        client.post("/api/activities", json={"subject": "Call owner", "due_at": "2026-01-01T09:00:00Z"}, headers=staff_headers)
        out = send_digest(db, settings)
        assert out["sent"] == [staff_user.id] and out["failed"] == []
    finally:
        settings.email_provider = "resend"
