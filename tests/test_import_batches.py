"""Comparison item 4: every import is a batch; duplicates go to a review list; an admin can undo a batch."""
import io
from datetime import date

from sqlalchemy import select

from app.legacy_migration import run_legacy_migration
from app.models import AuditLog, Contact, Deal, ImportBatch, Prospect


def _upload(client, headers, text, name="c.csv"):
    return client.post("/api/contacts/import", files={"file": (name, io.BytesIO(text.encode()), "text/csv")},
                       headers=headers)


def test_contact_import_creates_batch_and_lists_duplicates(client, db, staff_headers):
    client.post("/api/contacts", json={"display_name": "Broker B", "email": "b@example.com", "kind": "broker"},
                headers=staff_headers)
    csv_text = ("display_name,email,phone,kind\n"
                "Broker B,B@EXAMPLE.COM,,broker\n"          # duplicate by email of an existing contact
                "Case Manager C,,(423) 555-0100,case_manager\n"
                "Case Manager C,,423-555-0100,case_manager\n"  # duplicate by phone and name of row 3
                "Landlord D,,,landlord\n")
    r = _upload(client, staff_headers, csv_text)
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 2 and body["errors"] == []
    assert body["batch_id"] is not None
    dups = sorted((d["row"], d["reason"]) for d in body["duplicates"])
    assert dups == [(2, "email"), (2, "name"), (4, "name"), (4, "phone")]
    assert next(d for d in body["duplicates"] if d["row"] == 4)["matches_row"] == 3
    assert all(d["existing_contact_id"] is not None for d in body["duplicates"] if d["row"] == 2)

    batch = db.get(ImportBatch, body["batch_id"])
    assert batch.source == "csv" and batch.entity == "contact" and batch.created_count == 2
    assert batch.duplicate_count == 2 and batch.filename == "c.csv"
    made = db.scalars(select(Contact).where(Contact.import_batch_id == batch.id)).all()
    assert sorted(c.display_name for c in made) == ["Case Manager C", "Landlord D"]
    assert client.get("/api/imports", headers=staff_headers).json()[0]["id"] == batch.id


def test_force_inserts_duplicates_anyway(client, staff_headers):
    _upload(client, staff_headers, "display_name,email\nA,a@example.com\n")
    r = client.post("/api/contacts/import", params={"allow_duplicates": "true"},
                    files={"file": ("d.csv", io.BytesIO(b"display_name,email\nA,a@example.com\n"), "text/csv")},
                    headers=staff_headers)
    assert r.json()["created"] == 1 and r.json()["duplicates"] == []


def test_admin_undo_removes_batch_rows_once(client, db, staff_headers, admin_headers, pipelines):
    r = _upload(client, staff_headers, "display_name,email\nA,a@example.com\nB,b@example.com\n")
    batch_id = r.json()["batch_id"]
    kept = client.post("/api/contacts", json={"display_name": "Kept"}, headers=staff_headers).json()
    assert client.post(f"/api/imports/{batch_id}/undo", headers=staff_headers).status_code == 403

    r = client.post(f"/api/imports/{batch_id}/undo", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] == {"contacts": 2, "companies": 0, "deals": 0}
    names = [c["display_name"] for c in client.get("/api/contacts", headers=staff_headers).json()]
    assert names == ["Kept"] and db.get(Contact, kept["id"]) is not None
    assert db.get(ImportBatch, batch_id).undone_at is not None
    assert client.post(f"/api/imports/{batch_id}/undo", headers=admin_headers).status_code == 409
    assert db.scalar(select(AuditLog).where(AuditLog.action == "import.undo")) is not None


def test_legacy_migration_writes_a_batch_and_requires_an_actor(db):
    db.add(Prospect(initials="AB", status="Screened", deposit="300"))
    db.commit()
    try:
        run_legacy_migration(db, apply=True, actor_id=None)
        raised = False
    except ValueError as exc:
        raised = "actor" in str(exc)
    assert raised

    rep = run_legacy_migration(db, apply=True, actor_id="u1")
    assert not rep.dry_run and rep.batch_id is not None
    batch = db.get(ImportBatch, rep.batch_id)
    assert batch.source == "legacy" and batch.created_count == 2
    deal = db.scalar(select(Deal))
    assert deal.import_batch_id == batch.id and deal.owner_id == "u1" and deal.next_action_at == date.today()
    assert db.scalar(select(Contact)).import_batch_id == batch.id
    # The dry run writes no batch.
    before = len(db.scalars(select(ImportBatch)).all())
    run_legacy_migration(db, apply=False)
    assert len(db.scalars(select(ImportBatch)).all()) == before
