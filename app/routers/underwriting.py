"""Underwriting per property: the Prospect Hub view ported to the CRM (backlog item 2 and Atlas gap 6,
2026-11-21). Inputs are stored; every number is computed on read by app/underwriting.py."""
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import underwriting as uw
from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import csv_response, get_or_404
from app.db import get_db
from app.models import Property, Underwriting, UnderwritingSetting, User
from app.schemas_underwriting import (SettingsIn, StageIn, UnderwritingIn, UnderwritingOut, UnderwritingSummary)

router = APIRouter(prefix="/api/underwriting", tags=["underwriting"])

STORED_FIELDS = ("deal_type", "private_rooms", "shared_rooms", "bedrooms", "lease_cost", "sale_price", "utilities",
                 "inputs", "notes")


def _settings(db: Session) -> dict[str, float]:
    stored = {r.key: r.value for r in db.scalars(select(UnderwritingSetting)).all()}
    return uw.settings_with_defaults(stored)


def _f(v):
    return None if v is None else float(v)


def _record(row: Underwriting | None) -> dict:
    if row is None:
        return {}
    return {"privateRooms": row.private_rooms, "sharedRooms": row.shared_rooms, "bedrooms": row.bedrooms,
            "leaseCost": _f(row.lease_cost), "utilities": _f(row.utilities), "salePrice": _f(row.sale_price)}


def _overrides(row: Underwriting | None) -> dict:
    if row is None:
        return {}
    inputs = dict(row.inputs or {})
    inputs["mode"] = row.deal_type
    return inputs


def _compute(row: Underwriting | None, st: dict[str, float], occ: float | None = None) -> dict:
    overrides = _overrides(row)
    if occ is not None:
        overrides["occ"] = occ   # the page's occupancy slider: a what-if, never stored
    i = uw.resolve_inputs(_record(row), overrides, st)
    miss = uw.missing(i)
    if miss:
        return {"resolved": i, "missing": miss, "calc": None, "checks": None, "scenarios": None, "projection": None}
    c = uw.calc(i)
    return {"resolved": i, "missing": [], "calc": c, "checks": uw.checks(i, c, st), "scenarios": uw.scenarios(i),
            "projection": uw.project(i)}


def _row_for(db: Session, property_id: int) -> tuple[Property, Underwriting | None]:
    prop = get_or_404(db, Property, property_id, "Property")
    row = db.scalar(select(Underwriting).where(Underwriting.property_id == property_id))
    return prop, row


def _out(prop: Property, row: Underwriting | None, st: dict[str, float], occ: float | None = None) -> UnderwritingOut:
    base = {"property_id": prop.id, "address": prop.address, "exists": row is not None,
            "stage": row.stage if row else "Found", "deal_type": row.deal_type if row else "lease",
            "private_rooms": row.private_rooms if row else None, "shared_rooms": row.shared_rooms if row else None,
            "bedrooms": row.bedrooms if row else None, "lease_cost": row.lease_cost if row else None,
            "sale_price": row.sale_price if row else None, "utilities": row.utilities if row else None,
            "inputs": dict(row.inputs or {}) if row else {}, "market": dict(row.market or {}) if row else {},
            "notes": row.notes if row else "", "stage_changed_at": row.stage_changed_at if row else None,
            "updated_at": row.updated_at if row else None}
    return UnderwritingOut(**base, **_compute(row, st, occ))


def _snapshot(row: Underwriting) -> dict:
    return {f: (float(v) if isinstance(v, Decimal) else v) for f, v in ((f, getattr(row, f)) for f in STORED_FIELDS)}


# ---- settings ----
@router.get("/settings", response_model=dict[str, float])
def get_settings(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return _settings(db)


@router.put("/settings", response_model=dict[str, float])
def put_settings(payload: SettingsIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    before = _settings(db)
    for k, v in payload.values.items():
        row = db.get(UnderwritingSetting, k)
        if row is None:
            db.add(UnderwritingSetting(key=k, value=v))
        else:
            row.value = v
    db.flush()
    after = _settings(db)
    changes = {k: [before[k], after[k]] for k in after if before[k] != after[k]}
    write_audit(db, actor=user, action="underwriting.settings", entity="underwriting_settings", entity_id=None,
                details={"changes": changes})
    db.commit()
    return after


# ---- per property ----
@router.get("", response_model=list[UnderwritingSummary])
def list_underwriting(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    st = _settings(db)
    rows = {r.property_id: r for r in db.scalars(select(Underwriting)).all()}
    out = []
    for prop in db.scalars(select(Property).order_by(Property.address, Property.id)).all():
        row = rows.get(prop.id)
        c = _compute(row, st)
        calc = c["calc"]
        out.append(UnderwritingSummary(
            property_id=prop.id, address=prop.address, stage=row.stage if row else "Found",
            deal_type=row.deal_type if row else "lease", beds=c["resolved"]["beds"], missing=c["missing"],
            cash=calc["cash"] if calc else None, coverage=calc["coverage"] if calc else None,
            breakeven=calc["breakeven"] if calc else None, coc=calc["coc"] if calc else None,
            targets_met=sum(1 for x in c["checks"] if x["ok"]) if calc else None,
            targets=len(c["checks"]) if calc else None))
    return out


@router.get("/{property_id}", response_model=UnderwritingOut)
def get_underwriting(property_id: int, occ: float | None = Query(None, ge=0, le=100), db: Session = Depends(get_db),
                     _: User = Depends(require_staff)):
    """The full view. `occ` is the page's occupancy slider: the numbers are recomputed at that occupancy and
    nothing is stored."""
    prop, row = _row_for(db, property_id)
    return _out(prop, row, _settings(db), occ)


@router.put("/{property_id}", response_model=UnderwritingOut)
def put_underwriting(property_id: int, payload: UnderwritingIn, db: Session = Depends(get_db),
                     user: User = Depends(require_staff)):
    prop, row = _row_for(db, property_id)
    created = row is None
    if created:
        row = Underwriting(property_id=prop.id)
        db.add(row)
        db.flush()
    before = _snapshot(row)
    for f, v in payload.model_dump(exclude_unset=True).items():
        if v is None and f != "notes":
            setattr(row, f, None)
        else:
            setattr(row, f, v if v is not None else "")
    db.flush()
    after = _snapshot(row)
    changes = {f: [before[f], after[f]] for f in STORED_FIELDS if before[f] != after[f]}
    write_audit(db, actor=user, action="underwriting.create" if created else "underwriting.update",
                entity="underwriting", entity_id=row.id, details={"property_id": prop.id, "changes": changes})
    db.commit()
    db.refresh(row)
    return _out(prop, row, _settings(db))


@router.post("/{property_id}/stage", response_model=UnderwritingOut)
def set_stage(property_id: int, payload: StageIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    """A stage change from the drop-down. It is logged as a stage change (audit action underwriting.stage) so a
    later rule engine can act on it; nothing else fires today."""
    prop, row = _row_for(db, property_id)
    if row is None:
        row = Underwriting(property_id=prop.id)
        db.add(row)
        db.flush()
    if payload.stage != row.stage:
        from_stage = row.stage
        row.stage = payload.stage
        row.stage_changed_at = datetime.now(timezone.utc)
        write_audit(db, actor=user, action="underwriting.stage", entity="underwriting", entity_id=row.id,
                    details={"property_id": prop.id, "changes": {"stage": [from_stage, payload.stage]}})
        db.commit()
        db.refresh(row)
    return _out(prop, row, _settings(db))


@router.get("/{property_id}/summary.txt", response_class=PlainTextResponse)
def summary_text(property_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    prop, row = _row_for(db, property_id)
    st = _settings(db)
    c = _compute(row, st)
    if c["calc"] is None:
        raise HTTPException(status_code=409, detail="Add " + " and ".join(c["missing"]) + " to model this property")
    return uw.summary_text(prop.address, c["resolved"], c["calc"], c["checks"], date.today().isoformat())


@router.get("/{property_id}/export.csv")
def export_csv(property_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    prop, row = _row_for(db, property_id)
    c = _compute(row, _settings(db))
    if c["calc"] is None:
        raise HTTPException(status_code=409, detail="Add " + " and ".join(c["missing"]) + " to model this property")
    rows = uw.csv_rows(prop.address, c["resolved"], c["calc"])
    return csv_response(f"underwriting-{prop.id}.csv", ["Item", "Value"], [{"Item": r[0], "Value": r[1]} for r in rows[1:]])
