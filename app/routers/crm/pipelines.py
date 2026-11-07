from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_admin, require_staff
from app.crm_common import get_or_404
from app.db import get_db
from app.models import Deal, Pipeline, PipelineStage, User
from app.schemas_crm import PipelineIn, PipelineOut, PipelineSummary, StageIn, StageSummary

router = APIRouter(prefix="/api/pipelines", tags=["crm: pipelines"])


def _check_stages(stages: list[StageIn]) -> None:
    names = [s.name for s in stages]
    if len(set(names)) != len(names):
        raise HTTPException(status_code=422, detail="Stage names must be unique within a pipeline")
    if any(s.is_won and s.is_lost for s in stages):
        raise HTTPException(status_code=422, detail="A stage cannot be both won and lost")


@router.get("", response_model=list[PipelineOut])
def list_pipelines(include_inactive: bool = False, db: Session = Depends(get_db),
                   _: User = Depends(require_staff)):
    stmt = select(Pipeline).order_by(Pipeline.position, Pipeline.id)
    if not include_inactive:
        stmt = stmt.where(Pipeline.is_active.is_(True))
    return db.scalars(stmt).all()


@router.get("/{pipeline_id}", response_model=PipelineOut)
def get_pipeline(pipeline_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return get_or_404(db, Pipeline, pipeline_id, "Pipeline")


@router.post("", response_model=PipelineOut, status_code=201)
def create_pipeline(item: PipelineIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    _check_stages(item.stages)
    if db.scalar(select(Pipeline).where(Pipeline.slug == item.slug)):
        raise HTTPException(status_code=409, detail="A pipeline with that slug already exists")
    position = (db.scalar(select(func.max(Pipeline.position))) or 0) + 1
    p = Pipeline(name=item.name, slug=item.slug, description=item.description,
                 is_active=item.is_active, position=position)
    for i, s in enumerate(item.stages):
        p.stages.append(PipelineStage(position=i, **s.model_dump()))
    db.add(p)
    db.flush()
    write_audit(db, actor=user, action="pipeline.create", entity="pipeline", entity_id=p.id,
                details={"slug": p.slug, "stages": [s.name for s in item.stages]})
    db.commit()
    db.refresh(p)
    return p


@router.put("/{pipeline_id}", response_model=PipelineOut)
def update_pipeline(pipeline_id: int, item: PipelineIn, db: Session = Depends(get_db),
                    user: User = Depends(require_admin)):
    """Replace name, description, active flag, and the stage list. Existing stages are
    matched by name and keep their id; a stage that still holds deals cannot be removed."""
    _check_stages(item.stages)
    p = get_or_404(db, Pipeline, pipeline_id, "Pipeline")
    if item.slug != p.slug and db.scalar(select(Pipeline).where(Pipeline.slug == item.slug)):
        raise HTTPException(status_code=409, detail="A pipeline with that slug already exists")
    wanted = {s.name: s for s in item.stages}
    for stage in list(p.stages):
        if stage.name not in wanted:
            in_use = db.scalar(select(func.count()).select_from(Deal).where(Deal.stage_id == stage.id))
            if in_use:
                raise HTTPException(status_code=409,
                                    detail=f"Stage '{stage.name}' still holds {in_use} deal(s); move them first")
            p.stages.remove(stage)
    existing = {s.name: s for s in p.stages}
    new_list = []
    for i, s in enumerate(item.stages):
        stage = existing.get(s.name) or PipelineStage(name=s.name)
        stage.position, stage.probability, stage.is_won, stage.is_lost = i, s.probability, s.is_won, s.is_lost
        new_list.append(stage)
    p.stages = new_list
    p.name, p.slug, p.description, p.is_active = item.name, item.slug, item.description, item.is_active
    write_audit(db, actor=user, action="pipeline.update", entity="pipeline", entity_id=p.id,
                details={"stages": [s.name for s in item.stages]})
    db.commit()
    db.refresh(p)
    return p


@router.get("/{pipeline_id}/summary", response_model=PipelineSummary)
def pipeline_summary(pipeline_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    p = get_or_404(db, Pipeline, pipeline_id, "Pipeline")
    rows = db.execute(
        select(Deal.stage_id, func.count(Deal.id), func.coalesce(func.sum(Deal.amount), 0))
        .where(Deal.pipeline_id == pipeline_id, Deal.status == "open").group_by(Deal.stage_id)
    ).all()
    by_stage = {r[0]: (r[1], Decimal(str(r[2]))) for r in rows}
    stages = [StageSummary(stage_id=s.id, name=s.name, open_count=by_stage.get(s.id, (0, Decimal(0)))[0],
                           open_amount=by_stage.get(s.id, (0, Decimal(0)))[1]) for s in p.stages]
    counts = dict(db.execute(select(Deal.status, func.count(Deal.id))
                             .where(Deal.pipeline_id == pipeline_id).group_by(Deal.status)).all())
    return PipelineSummary(
        pipeline_id=pipeline_id,
        open_count=sum(s.open_count for s in stages),
        open_amount=sum((s.open_amount for s in stages), Decimal(0)),
        won_count=counts.get("won", 0), lost_count=counts.get("lost", 0), stages=stages,
    )
