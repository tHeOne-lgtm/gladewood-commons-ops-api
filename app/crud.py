"""Generic staff-only CRUD router factory with audit logging and pagination."""
from typing import Type

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.db import get_db
from app.models import Base, User
from app.schemas import DeleteResult


def _snapshot(row: Base, fields: list[str]) -> dict:
    return {f: getattr(row, f) for f in fields}


def build_crud_router(
    *,
    prefix: str,
    tag: str,
    entity: str,
    model: Type[Base],
    schema_in: Type[BaseModel],
    schema_out: Type[BaseModel],
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])
    fields = list(schema_in.model_fields)

    def _get_or_404(db: Session, row_id: int) -> Base:
        row = db.get(model, row_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Not found")
        return row

    @router.get("", response_model=list[schema_out])
    def list_rows(
        limit: int = Query(500, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        _: User = Depends(require_staff),
    ):
        stmt = select(model).order_by(model.id).limit(limit).offset(offset)
        return db.scalars(stmt).all()

    @router.post("", response_model=schema_out, status_code=201)
    def create_row(item: schema_in, db: Session = Depends(get_db), user: User = Depends(require_staff)):
        row = model(**item.model_dump())
        db.add(row)
        db.flush()
        write_audit(db, actor=user, action=f"{entity}.create", entity=entity, entity_id=row.id,
                    details=_snapshot(row, fields))
        db.commit()
        db.refresh(row)
        return row

    @router.put("/{row_id}", response_model=schema_out)
    def update_row(row_id: int, item: schema_in, db: Session = Depends(get_db),
                   user: User = Depends(require_staff)):
        row = _get_or_404(db, row_id)
        before = _snapshot(row, fields)
        for f, v in item.model_dump().items():
            setattr(row, f, v)
        changes = {f: [before[f], getattr(row, f)] for f in fields if before[f] != getattr(row, f)}
        write_audit(db, actor=user, action=f"{entity}.update", entity=entity, entity_id=row_id,
                    details={"changes": changes})
        db.commit()
        db.refresh(row)
        return row

    @router.delete("/{row_id}", response_model=DeleteResult)
    def delete_row(row_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
        row = _get_or_404(db, row_id)
        write_audit(db, actor=user, action=f"{entity}.delete", entity=entity, entity_id=row_id,
                    details=_snapshot(row, fields))
        db.delete(row)
        db.commit()
        return DeleteResult(deleted=row_id)

    return router
