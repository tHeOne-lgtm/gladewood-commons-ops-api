"""Default Gladewood pipelines. Idempotent by slug."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pipeline, PipelineStage

DEFAULT_PIPELINES = [
    {
        "slug": "property", "name": "Property owner and property manager", "position": 1,
        "description": "Owners and management companies approached for master leases.",
        "stages": [
            ("Not sourced yet", 5), ("Contacted", 15), ("Fact sheet sent", 25), ("Tour scheduled", 35),
            ("Toured", 45), ("Proposal sent", 60), ("Negotiating", 75),
            ("Master lease signed", 100, "won"), ("Passed", 0, "lost"), ("No response", 0, "lost"),
        ],
        "renames": {"Touring": "Toured"},
    },
    {
        "slug": "resident-inquiry", "name": "Resident inquiry", "position": 2,
        "description": "Inquiry to move-in for independent shared housing.",
        "stages": [
            ("Inquiry", 10), ("Screened", 30), ("Tour scheduled", 40), ("Toured", 45), ("Income verified", 50),
            ("Deposit received", 80), ("Confirmed", 90), ("Moved in", 100, "won"), ("Closed, no move-in", 0, "lost"),
        ],
    },
    {
        "slug": "referral-partner", "name": "Referral partner outreach", "position": 3,
        "description": "Case managers, agencies, employers, and hospitals that refer residents.",
        "stages": [
            ("Not contacted", 5), ("Contacted", 20), ("Fact sheet sent", 35), ("Engaged", 50),
            ("MOA sent", 65), ("MOA signed", 80), ("Referring", 100, "won"), ("Dormant", 0, "lost"),
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


def sync_default_pipelines(db: Session) -> dict:
    """Bring existing default pipelines up to the current spec without removing anything:
    rename the pipeline, apply stage renames, add missing stages, and refresh position,
    probability, and won/lost flags by stage name. Deals keep their stage ids."""
    changed = {"renamed_stages": 0, "added_stages": 0, "updated_pipelines": 0}
    for spec in DEFAULT_PIPELINES:
        p = db.scalar(select(Pipeline).where(Pipeline.slug == spec["slug"]))
        if p is None:
            continue
        p.name, p.description, p.position = spec["name"], spec["description"], spec["position"]
        changed["updated_pipelines"] += 1
        by_name = {s.name: s for s in p.stages}
        for old, new in spec.get("renames", {}).items():
            if old in by_name and new not in by_name:
                by_name[old].name = new
                by_name[new] = by_name.pop(old)
                changed["renamed_stages"] += 1
        for i, s in enumerate(spec["stages"]):
            name, prob = s[0], s[1]
            flag = s[2] if len(s) > 2 else ""
            st = by_name.get(name)
            if st is None:
                st = PipelineStage(name=name)
                p.stages.append(st)
                by_name[name] = st
                changed["added_stages"] += 1
            st.position, st.probability, st.is_won, st.is_lost = i, prob, (flag == "won"), (flag == "lost")
        # stages not in the spec keep their ids and go to the end, in their old order
        extra = [s for s in p.stages if s.name not in {x[0] for x in spec["stages"]}]
        for j, s in enumerate(sorted(extra, key=lambda x: x.position)):
            s.position = len(spec["stages"]) + j
    db.flush()
    return changed
