from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import csv_response, diff, ensure_exists, get_or_404, snapshot
from app.db import get_db
from app.models import Company, Contact, Deal, DealStageHistory, Pipeline, PipelineStage, Property, User, utcnow
from app.schemas import DeleteResult
from app.schemas_crm import DealIn, DealMove, DealOut

router = APIRouter(prefix="/api/deals", tags=["crm: deals"])
FIELDS = [f for f in DealIn.model_fields] + ["status", "closed_at"]
CSV_FIELDS = ["id", "title", "pipeline_id", "stage_id", "stage_name", "status", "contact_id", "company_id",
              "property_id", "amount", "expected_close", "next_action_at", "owner_id", "lost_reason", "closed_at",
              "import_batch_id", "created_at"]


def _out(row: Deal) -> DealOut:
    o = DealOut.model_validate(row)
    o.stage_name = row.stage.name if row.stage else None
    return o


def _stage_for(db: Session, pipeline_id: int, stage_id: int | None) -> PipelineStage:
    pipeline = get_or_404(db, Pipeline, pipeline_id, "Pipeline")
    if stage_id is None:
        if not pipeline.stages:
            raise HTTPException(status_code=422, detail="Pipeline has no stages")
        return pipeline.stages[0]
    stage = db.get(PipelineStage, stage_id)
    if stage is None or stage.pipeline_id != pipeline_id:
        raise HTTPException(status_code=422, detail="Stage does not belong to that pipeline")
    return stage


def _apply_stage(deal: Deal, stage: PipelineStage, lost_reason: str = "") -> None:
    deal.stage_id = stage.id
    deal.stage = stage
    if stage.is_won:
        deal.status, deal.closed_at, deal.lost_reason = "won", utcnow(), ""
    elif stage.is_lost:
        deal.status, deal.closed_at, deal.lost_reason = "lost", utcnow(), lost_reason
    else:
        deal.status, deal.closed_at, deal.lost_reason = "open", None, ""


def _validate_links(db: Session, item: DealIn) -> None:
    ensure_exists(db, Contact, item.contact_id, "Contact")
    ensure_exists(db, Company, item.company_id, "Company")
    ensure_exists(db, Property, item.property_id, "Property")
    if item.owner_id is not None and db.get(User, item.owner_id) is None:
        raise HTTPException(status_code=422, detail="owner_id is not a known user")


def _require_open_fields(stage: PipelineStage, owner_id: str | None, next_action_at) -> None:
    """Comparison item 1: an open deal carries an owner and a next-action date.
    Checked before the row is changed, so a refused request leaves nothing dirty in the session."""
    if stage.is_won or stage.is_lost:
        return
    if owner_id is None:
        raise HTTPException(status_code=422, detail="owner_id is required while a deal is open")
    if next_action_at is None:
        raise HTTPException(status_code=422, detail="next_action_at is required while a deal is open")


def _query(pipeline_id, stage_id, status, contact_id, company_id, property_id, owner_id, q):
    stmt = select(Deal)
    for col, val in ((Deal.pipeline_id, pipeline_id), (Deal.stage_id, stage_id), (Deal.contact_id, contact_id),
                     (Deal.company_id, company_id), (Deal.property_id, property_id), (Deal.owner_id, owner_id)):
        if val is not None:
            stmt = stmt.where(col == val)
    if status and status != "all":
        stmt = stmt.where(Deal.status == status)
    if q:
        stmt = stmt.where(or_(Deal.title.ilike(f"%{q}%"), Deal.lost_reason.ilike(f"%{q}%")))
    return stmt.order_by(Deal.updated_at.desc(), Deal.id.desc())


@router.get("", response_model=list[DealOut])
def list_deals(pipeline_id: int | None = None, stage_id: int | None = None, status: str | None = "open",
               contact_id: int | None = None, company_id: int | None = None, property_id: int | None = None,
               owner_id: str | None = None, q: str | None = None,
               limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows = db.scalars(_query(pipeline_id, stage_id, status, contact_id, company_id, property_id,
                             owner_id, q).limit(limit).offset(offset)).all()
    return [_out(r) for r in rows]


@router.get("/export")
def export_deals(pipeline_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows = db.scalars(_query(pipeline_id, None, "all", None, None, None, None, None)).all()
    return csv_response("deals.csv", CSV_FIELDS,
                        ({**snapshot(r, [f for f in CSV_FIELDS if f != "stage_name"]),
                          "stage_name": r.stage.name if r.stage else ""} for r in rows))


@router.get("/{row_id}", response_model=DealOut)
def get_deal(row_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return _out(get_or_404(db, Deal, row_id, "Deal"))


@router.post("", response_model=DealOut, status_code=201)
def create_deal(item: DealIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    _validate_links(db, item)
    stage = _stage_for(db, item.pipeline_id, item.stage_id)
    owner_id = item.owner_id or user.id
    _require_open_fields(stage, owner_id, item.next_action_at)
    row = Deal(**item.model_dump(exclude={"stage_id", "lost_reason", "owner_id"}), owner_id=owner_id)
    _apply_stage(row, stage, item.lost_reason)
    db.add(row)
    db.flush()
    db.add(DealStageHistory(deal_id=row.id, from_stage_id=None, to_stage_id=stage.id, actor_id=user.id))
    write_audit(db, actor=user, action="deal.create", entity="deal", entity_id=row.id, details=snapshot(row, FIELDS))
    db.commit()
    db.refresh(row)
    return _out(row)


@router.put("/{row_id}", response_model=DealOut)
def update_deal(row_id: int, item: DealIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Deal, row_id, "Deal")
    _validate_links(db, item)
    if item.pipeline_id != row.pipeline_id:
        raise HTTPException(status_code=422, detail="Use a new deal to change pipelines")
    stage_changes = item.stage_id is not None and item.stage_id != row.stage_id
    stage = _stage_for(db, row.pipeline_id, item.stage_id) if stage_changes else row.stage
    owner_id = item.owner_id or row.owner_id   # the owner of an open deal cannot be cleared, only changed
    _require_open_fields(stage, owner_id, item.next_action_at)
    before = snapshot(row, FIELDS)
    for k, v in item.model_dump(exclude={"stage_id", "lost_reason", "pipeline_id", "owner_id"}).items():
        setattr(row, k, v)
    row.owner_id = owner_id
    if stage_changes:
        db.add(DealStageHistory(deal_id=row.id, from_stage_id=row.stage_id, to_stage_id=stage.id,
                                actor_id=user.id))
        _apply_stage(row, stage, item.lost_reason)
    write_audit(db, actor=user, action="deal.update", entity="deal", entity_id=row_id,
                details={"changes": diff(before, snapshot(row, FIELDS))})
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/{row_id}/move", response_model=DealOut)
def move_deal(row_id: int, payload: DealMove, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Deal, row_id, "Deal")
    stage = _stage_for(db, row.pipeline_id, payload.stage_id)
    if stage.id == row.stage_id:
        return _out(row)
    owner_id = row.owner_id or user.id
    next_action_at = payload.next_action_at or row.next_action_at
    _require_open_fields(stage, owner_id, next_action_at)
    from_name = row.stage.name
    db.add(DealStageHistory(deal_id=row.id, from_stage_id=row.stage_id, to_stage_id=stage.id, actor_id=user.id))
    _apply_stage(row, stage, payload.lost_reason)
    row.owner_id = owner_id
    row.next_action_at = next_action_at if row.status == "open" else None
    write_audit(db, actor=user, action="deal.move", entity="deal", entity_id=row_id,
                details={"changes": {"stage": [from_name, stage.name]}, "status": row.status})
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{row_id}", response_model=DeleteResult)
def delete_deal(row_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Deal, row_id, "Deal")
    write_audit(db, actor=user, action="deal.delete", entity="deal", entity_id=row_id, details=snapshot(row, FIELDS))
    db.delete(row)
    db.commit()
    return DeleteResult(deleted=row_id)
