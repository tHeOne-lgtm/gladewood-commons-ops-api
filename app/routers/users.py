"""Current-user and admin role management."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import get_current_user, mfa_required, require_admin
from app.config import Settings, settings_dep
from app.db import get_db
from app.models import User
from app.schemas import RoleUpdate, UserOut

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/me", response_model=UserOut)
def me(request: Request, user: User = Depends(get_current_user), settings: Settings = Depends(settings_dep)):
    out = UserOut.model_validate(user)
    out.mfa_required = mfa_required(request, user, settings)
    return out


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.put("/users/{user_id}/role", response_model=UserOut)
def set_role(user_id: str, payload: RoleUpdate, db: Session = Depends(get_db),
             admin: User = Depends(require_admin)):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    before = target.role
    target.role = payload.role
    write_audit(db, actor=admin, action="user.role_change", entity="user", entity_id=user_id,
                details={"changes": {"role": [before, payload.role]}})
    db.commit()
    db.refresh(target)
    return target
