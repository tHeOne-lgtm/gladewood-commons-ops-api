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


# ---- Email templates (Phase 2c). Plain text; {{field}} merge tags; no protected-trait language. ----
DEFAULT_EMAIL_TEMPLATES: list[dict] = [
    {"name": "Welcome and next steps", "kind": "transactional", "audience": "resident",
     "subject": "Thanks for reaching out to Gladewood Commons",
     "body_text": "Hi {{first_name}},\n\nThanks for your interest in Gladewood Commons. We offer furnished private rooms in shared homes in Chattanooga, with utilities, Wi-Fi, and shared spaces included in one monthly price.\n\nNext step: a short call or a tour. Reply to this email with two or three times that work for you, and I will confirm one.\n\nPaul\nGladewood Commons"},
    {"name": "Tour confirmation", "kind": "transactional", "audience": "resident",
     "subject": "Your Gladewood Commons tour is set for {{next_action_at}}",
     "body_text": "Hi {{first_name}},\n\nYour tour is confirmed for {{next_action_at}}. I will send the address and parking details the day before.\n\nBring a photo ID. Plan on about 30 minutes; you will see the room, the shared kitchen and living areas, and we will go over the house agreements and pricing.\n\nIf you need to change the time, reply here or text the number on our site.\n\nPaul\nGladewood Commons"},
    {"name": "Application received", "kind": "transactional", "audience": "resident",
     "subject": "We received your application",
     "body_text": "Hi {{first_name}},\n\nYour application is in. Management reviews applications in the order received using the written criteria on our site: verified income, rental history, and fit with shared living agreements. You will hear back within three business days.\n\nIf anything is missing, I will email you the exact item.\n\nPaul\nGladewood Commons"},
    {"name": "Partner fact sheet", "kind": "transactional", "audience": "partner",
     "subject": "Gladewood Commons fact sheet for {{company_name}}",
     "body_text": "Hi {{first_name}},\n\nThanks for the conversation. Attached below is the short version of what we offer your clients:\n\n- Furnished private rooms in shared homes in Chattanooga\n- One monthly price covering rent, utilities, and Wi-Fi\n- Independent living for working adults; no on-site services of any kind\n- Referral and tour requests go straight to me\n\nIf you send me the best way to reach your team, I will set up a 15 minute intro call.\n\nPaul\nGladewood Commons"},
    {"name": "Monthly partner update", "kind": "campaign", "audience": "partner",
     "subject": "Gladewood Commons: rooms open this month",
     "body_text": "Hi {{first_name}},\n\nA quick update for referral partners. Rooms are opening this month in Chattanooga; reply with a client's first name and a phone number and I will reach out the same day.\n\nWhat we provide: a furnished private room, shared kitchen and living areas, utilities and Wi-Fi in one monthly price, and a written set of shared living agreements every member signs.\n\nGladewood is housing only: residents live independently, and there are no on-site services or staff.\n\nThanks for the referrals this month.\n\nPaul\nGladewood Commons"},
]


def seed_default_email_templates(db: Session) -> list[str]:
    """Create the default templates that are missing (matched by name). Existing ones are left alone."""
    from app.models import EmailTemplate
    existing = {t.name for t in db.scalars(select(EmailTemplate)).all()}
    added = []
    for spec in DEFAULT_EMAIL_TEMPLATES:
        if spec["name"] in existing:
            continue
        db.add(EmailTemplate(**spec))
        added.append(spec["name"])
    db.flush()
    return added
