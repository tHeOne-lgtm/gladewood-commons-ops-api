from decimal import Decimal

import pytest
from sqlalchemy import select

from app.legacy_migration import parse_date, parse_money, run_legacy_migration
from app.models import Contact, Deal, Property, Prospect, Resident


def test_parsers():
    assert parse_money("$1,250.5") == Decimal("1250.50")
    assert parse_money("") is None
    assert parse_money("(200)") == Decimal("-200.00")
    with pytest.raises(ValueError):
        parse_money("TBD")
    assert parse_date("2026-03-01").isoformat() == "2026-03-01"
    assert parse_date("3/1/26").isoformat() == "2026-03-01"
    with pytest.raises(ValueError):
        parse_date("spring")


def _seed_legacy(db):
    """Returns the seeded rows. Tests must use their ids: on Postgres the sequences
    keep counting across tests, so ids are not 1..n."""
    rows = {
        "ab": Prospect(initials="AB", source="Case manager", room_type="Private", status="Screened", deposit="$300"),
        "cd": Prospect(initials="CD", status="Confirmed", income_verified="Verified", deposit="300"),
        "ef": Prospect(initials="EF", status="Ghosted", deposit="n/a"),
        "gh": Resident(initials="GH", room="2B", lease_start="2026-01-15", rent_status="Current"),
        "pine": Property(address="12 Pine St", area="Brainerd", rent="2,100", status="Negotiating"),
        "vine": Property(address="88 Vine St", rent="call", status="Contacted"),
    }
    db.add_all(rows.values())
    db.commit()
    return rows


def test_dry_run_reports_rejections_and_writes_nothing(db):
    rows = _seed_legacy(db)
    rep = run_legacy_migration(db, apply=False)
    assert rep.dry_run and rep.scanned == {"prospects": 3, "residents": 1, "properties": 2}
    rej = sorted((r.table, r.id, r.field) for r in rep.rejections)
    assert rej == [("properties", rows["vine"].id, "rent"), ("prospects", rows["ef"].id, "deposit"),
                   ("prospects", rows["ef"].id, "status")]
    assert rep.would_create == {"contacts": 3, "deals": 3}
    assert db.scalar(select(Contact)) is None and db.scalar(select(Deal)) is None


def test_apply_refuses_with_rejections_unless_partial_then_idempotent(db):
    rows = _seed_legacy(db)
    rep = run_legacy_migration(db, apply=True)
    assert rep.dry_run and db.scalar(select(Contact)) is None

    rep = run_legacy_migration(db, apply=True, allow_partial=True, actor_id="u1")
    assert not rep.dry_run
    contacts = db.scalars(select(Contact).order_by(Contact.id)).all()
    assert [(c.display_name, c.kind) for c in contacts] == [("AB", "prospect"), ("CD", "prospect"), ("GH", "resident")]
    assert contacts[2].extra["lease_start"] == "2026-01-15"
    deals = db.scalars(select(Deal).order_by(Deal.id)).all()
    assert [d.title for d in deals] == ["Inquiry: AB", "Inquiry: CD", "12 Pine St"]
    assert deals[0].amount == Decimal("300.00") and deals[0].stage.name == "Screened" and deals[0].contact_id == contacts[0].id
    assert deals[2].amount == Decimal("2100.00") and deals[2].property_id == rows["pine"].id and deals[2].owner_id == "u1"
    assert all(d.status == "open" for d in deals)

    again = run_legacy_migration(db, apply=True, allow_partial=True)
    assert again.would_create == {"contacts": 0, "deals": 0}
    assert again.skipped_existing == {"contacts": 3, "deals": 3}
    assert len(db.scalars(select(Deal)).all()) == 3
