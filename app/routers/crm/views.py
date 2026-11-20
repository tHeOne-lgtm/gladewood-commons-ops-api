"""Saved views: named filter sets per list screen, shared by default, deletable by owner or admin."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import ADMIN_ROLES, require_staff
from app.crm_common import get_or_404
from app.db import get_db
from app.models import SavedView, User
from app.schemas import DeleteResult
from app.schemas_crm import SavedViewIn, SavedViewOut, ViewEntity

router = APIRouter(prefix="/api/views", tags=["crm: saved views"])


def _out(row: SavedView, user: User) -> SavedViewOut:
    o = SavedViewOut.model_validate(row)
    o.mine = row.owner_id == user.id
    return o


@router.get("", response_model=list[SavedViewOut])
def list_views(entity: ViewEntity | None = None, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    q = select(SavedView).where(or_(SavedView.owner_id == user.id, SavedView.shared.is_(True)))
    if entity:
        q = q.where(SavedView.entity == entity)
    return [_out(r, user) for r in db.scalars(q.order_by(SavedView.entity, SavedView.position, SavedView.name)).all()]


@router.post("", response_model=SavedViewOut, status_code=201)
def create_view(item: SavedViewIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = SavedView(**item.model_dump(), owner_id=user.id)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="view.create", entity="saved_view", entity_id=row.id, details={"name": row.name, "entity": row.entity})
    db.commit()
    return _out(row, user)


def _editable(row: SavedView, user: User) -> None:
    if row.owner_id != user.id and not row.shared and user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=404, detail="View not found")  # a private view is invisible to others
    if row.owner_id != user.id and user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only the owner or an admin can change this view")


@router.put("/{view_id}", response_model=SavedViewOut)
def update_view(view_id: int, item: SavedViewIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, SavedView, view_id, "View")
    _editable(row, user)
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    write_audit(db, actor=user, action="view.update", entity="saved_view", entity_id=row.id, details={"name": row.name})
    db.commit()
    return _out(row, user)


@router.delete("/{view_id}", response_model=DeleteResult)
def delete_view(view_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, SavedView, view_id, "View")
    _editable(row, user)
    write_audit(db, actor=user, action="view.delete", entity="saved_view", entity_id=row.id, details={"name": row.name})
    db.delete(row)
    db.commit()
    return DeleteResult(deleted=1)
