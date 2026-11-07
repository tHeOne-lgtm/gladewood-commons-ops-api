"""Move legacy prospects, residents, and properties into the CRM.

Dry run by default: scans every row, parses money and dates, maps statuses to
pipeline stages, and reports every row it would reject. Nothing is written
unless apply=True and there are zero rejections (or allow_partial=True).
Idempotent: each created contact or deal carries legacy_ref="<table>:<id>".
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, Deal, DealStageHistory, Pipeline, Property, Prospect, Resident
from app.schemas_crm import MigrationRejection, MigrationReport
from app.seed import seed_default_pipelines

PROSPECT_STAGE = {
    "inquiry": "Inquiry", "screened": "Screened", "income-verified": "Income verified",
    "income verified": "Income verified", "deposit received": "Deposit received", "confirmed": "Confirmed",
    "moved in": "Moved in", "declined": "Closed, no move-in", "lost": "Closed, no move-in",
    "withdrawn": "Closed, no move-in",
}
PROPERTY_STAGE = {
    "not sourced yet": "Not sourced yet", "sourced": "Not sourced yet", "contacted": "Contacted",
    "touring": "Touring", "tour scheduled": "Touring", "toured": "Touring", "negotiating": "Negotiating",
    "offer sent": "Negotiating", "signed": "Master lease signed", "master lease signed": "Master lease signed",
    "leased": "Master lease signed", "passed": "Passed", "lost": "Passed", "declined": "Passed",
}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d")


def parse_money(text: str) -> Decimal | None:
    s = re.sub(r"[,$\s]", "", text or "")
    if not s:
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"not a money amount: {text!r}") from exc


def parse_date(text: str) -> date | None:
    s = (text or "").strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {text!r}")


def _stage(pipeline: Pipeline, mapping: dict[str, str], raw: str):
    key = (raw or "").strip().lower()
    name = mapping.get(key)
    if name is None:
        return None
    return next((s for s in pipeline.stages if s.name == name), None)


def run_legacy_migration(db: Session, *, apply: bool = False, allow_partial: bool = False,
                         actor_id: str | None = None) -> MigrationReport:
    seed_default_pipelines(db)
    pipelines = {p.slug: p for p in db.scalars(select(Pipeline)).all()}
    inquiry, property_pipe = pipelines["resident-inquiry"], pipelines["property"]
    existing = {r for r in db.scalars(select(Contact.legacy_ref).where(Contact.legacy_ref.is_not(None))).all()}
    existing |= {r for r in db.scalars(select(Deal.legacy_ref).where(Deal.legacy_ref.is_not(None))).all()}

    rejections: list[MigrationRejection] = []
    plan: list[tuple[str, object]] = []
    scanned = {"prospects": 0, "residents": 0, "properties": 0}
    skipped = {"contacts": 0, "deals": 0}

    def reject(table, row_id, field, value, reason):
        rejections.append(MigrationRejection(table=table, id=row_id, field=field, value=str(value), reason=reason))

    for p in db.scalars(select(Prospect).order_by(Prospect.id)).all():
        scanned["prospects"] += 1
        ref = f"prospects:{p.id}"
        ok = True
        try:
            deposit = parse_money(p.deposit)
        except ValueError as exc:
            reject("prospects", p.id, "deposit", p.deposit, str(exc)); ok = False; deposit = None
        stage = _stage(inquiry, PROSPECT_STAGE, p.status)
        if stage is None:
            reject("prospects", p.id, "status", p.status, "no matching stage in Resident inquiry pipeline"); ok = False
        if not (p.initials or "").strip():
            reject("prospects", p.id, "initials", p.initials, "blank; display_name is required"); ok = False
        if not ok:
            continue
        if ref in existing:
            skipped["contacts"] += 1; skipped["deals"] += 1
            continue
        contact = Contact(display_name=p.initials.strip(), kind="prospect", source=p.source or "",
                          notes=p.notes or "", legacy_ref=ref,
                          extra={"room_type": p.room_type or "", "income_verified": p.income_verified or "",
                                 "deposit": str(deposit) if deposit is not None else ""})
        plan.append(("contact", contact))
        plan.append(("deal", (contact, Deal(pipeline_id=inquiry.id, title=f"Inquiry: {p.initials.strip()}",
                                            legacy_ref=ref, amount=deposit, owner_id=actor_id,
                                            extra={"room_type": p.room_type or ""}), stage)))

    for r in db.scalars(select(Resident).order_by(Resident.id)).all():
        scanned["residents"] += 1
        ref = f"residents:{r.id}"
        ok = True
        try:
            lease_start = parse_date(r.lease_start)
        except ValueError as exc:
            reject("residents", r.id, "lease_start", r.lease_start, str(exc)); ok = False; lease_start = None
        if not (r.initials or "").strip():
            reject("residents", r.id, "initials", r.initials, "blank; display_name is required"); ok = False
        if not ok:
            continue
        if ref in existing:
            skipped["contacts"] += 1
            continue
        plan.append(("contact", Contact(
            display_name=r.initials.strip(), kind="resident", notes=r.notes or "", legacy_ref=ref,
            extra={"room": r.room or "", "lease_start": lease_start.isoformat() if lease_start else "",
                   "rent_status": r.rent_status or "", "house_rules": r.house_rules or ""})))

    for pr in db.scalars(select(Property).order_by(Property.id)).all():
        scanned["properties"] += 1
        ref = f"properties:{pr.id}"
        ok = True
        try:
            rent = parse_money(pr.rent)
        except ValueError as exc:
            reject("properties", pr.id, "rent", pr.rent, str(exc)); ok = False; rent = None
        stage = _stage(property_pipe, PROPERTY_STAGE, pr.status)
        if stage is None:
            reject("properties", pr.id, "status", pr.status, "no matching stage in Property pipeline"); ok = False
        if not ok:
            continue
        if ref in existing:
            skipped["deals"] += 1
            continue
        plan.append(("deal", (None, Deal(pipeline_id=property_pipe.id, property_id=pr.id, legacy_ref=ref,
                                         title=(pr.address or f"Property {pr.id}").strip(), amount=rent,
                                         owner_id=actor_id,
                                         extra={"area": pr.area or "", "beds": pr.beds or "", "baths": pr.baths or "",
                                                "zoning_fit": pr.zoning_fit or "", "next_action": pr.next_action or ""}),
                              stage)))

    would = {"contacts": sum(1 for k, _ in plan if k == "contact"), "deals": sum(1 for k, _ in plan if k == "deal")}
    report = MigrationReport(dry_run=not apply, scanned=scanned, would_create=would, skipped_existing=skipped,
                             rejections=rejections)
    if not apply or (rejections and not allow_partial):
        if apply:
            report.dry_run = True
        db.rollback()
        return report

    for kind, obj in plan:
        if kind == "contact":
            db.add(obj)
    db.flush()
    for kind, obj in plan:
        if kind == "deal":
            contact, deal, stage = obj
            if contact is not None:
                deal.contact_id = contact.id
            deal.stage_id = stage.id
            deal.status = "won" if stage.is_won else "lost" if stage.is_lost else "open"
            db.add(deal)
            db.flush()
            db.add(DealStageHistory(deal_id=deal.id, from_stage_id=None, to_stage_id=stage.id, actor_id=actor_id))
    db.commit()
    return report
