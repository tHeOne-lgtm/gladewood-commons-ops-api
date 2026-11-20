from app.models import Pipeline, PipelineStage
from app.seed import seed_default_pipelines, sync_default_pipelines
from sqlalchemy import select


def test_sync_renames_adds_and_reorders_without_losing_deal_stage_ids(client, db, staff_headers):
    # Old shape of the property pipeline, as created by migration 0002
    old = Pipeline(slug="property", name="Property and landlord", description="", position=1)
    for i, (n, pr, flag) in enumerate([("Not sourced yet", 5, ""), ("Contacted", 15, ""), ("Touring", 35, ""),
                                       ("Negotiating", 60, ""), ("Master lease signed", 100, "won"), ("Passed", 0, "lost")]):
        old.stages.append(PipelineStage(name=n, position=i, probability=pr, is_won=flag == "won", is_lost=flag == "lost"))
    db.add(old)
    db.commit()
    touring_id = next(s.id for s in old.stages if s.name == "Touring")
    deal = client.post("/api/deals", json={"title": "12 Pine", "pipeline_id": old.id, "stage_id": touring_id}, headers=staff_headers).json()

    changed = sync_default_pipelines(db)
    db.commit()
    assert changed["renamed_stages"] == 1 and changed["added_stages"] == 4
    p = db.scalar(select(Pipeline).where(Pipeline.slug == "property"))
    db.refresh(p)
    names = [s.name for s in sorted(p.stages, key=lambda s: s.position)]
    assert names == ["Not sourced yet", "Contacted", "Fact sheet sent", "Tour scheduled", "Toured", "Proposal sent",
                     "Negotiating", "Master lease signed", "Passed", "No response"]
    assert p.name == "Property owner and property manager"
    got = client.get(f"/api/deals/{deal['id']}", headers=staff_headers).json()
    assert got["stage_id"] == touring_id and got["stage_name"] == "Toured"
    # running again changes nothing
    assert sync_default_pipelines(db) == {"renamed_stages": 0, "added_stages": 0, "updated_pipelines": 1}


def test_fresh_seed_matches_sync_spec(db):
    seed_default_pipelines(db)
    p = db.scalar(select(Pipeline).where(Pipeline.slug == "referral-partner"))
    assert [s.name for s in p.stages] == ["Not contacted", "Contacted", "Fact sheet sent", "Engaged", "MOA sent", "MOA signed", "Referring", "Dormant"]
    assert sync_default_pipelines(db)["added_stages"] == 0
