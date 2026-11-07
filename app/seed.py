"""Default Gladewood pipelines. Idempotent by slug."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pipeline, PipelineStage

DEFAULT_PIPELINES = [
    {
        "slug": "property", "name": "Property and landlord", "position": 1,
        "description": "Houses sourced for master leases.",
        "stages": [
            ("Not sourced yet", 5), ("Contacted", 15), ("Touring", 35), ("Negotiating", 60),
            ("Master lease signed", 100, "won"), ("Passed", 0, "lost"),
        ],
    },
    {
        "slug": "resident-inquiry", "name": "Resident inquiry", "position": 2,
        "description": "Inquiry to move-in for independent shared housing.",
        "stages": [
            ("Inquiry", 10), ("Screened", 30), ("Income verified", 50), ("Deposit received", 80),
            ("Confirmed", 90), ("Moved in", 100, "won"), ("Closed, no move-in", 0, "lost"),
        ],
    },
    {
        "slug": "referral-partner", "name": "Referral partner outreach", "position": 3,
        "description": "Case managers, agencies, employers, and hospitals that refer residents.",
        "stages": [
            ("Not contacted", 5), ("Contacted", 20), ("Engaged", 50), ("Referring", 100, "won"),
            ("Dormant", 0, "lost"),
        ],
    },
]


def seed_default_pipelines(db: Session) -> int:
    created = 0
    for spec in DEFAULT_PIPELINES:
        if db.scalar(select(Pipeline).where(Pipeline.slug == spec["slug"])):
            continue
        p = Pipeline(slug=spec["slug"], name=spec["name"], description=spec["description"],
                     position=spec["position"])
        for i, s in enumerate(spec["stages"]):
            name, prob = s[0], s[1]
            flag = s[2] if len(s) > 2 else ""
            p.stages.append(PipelineStage(name=name, position=i, probability=prob,
                                          is_won=(flag == "won"), is_lost=(flag == "lost")))
        db.add(p)
        created += 1
    db.flush()
    return created
