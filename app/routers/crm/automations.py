from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.automations import RULES, run_automations
from app.db import get_db
from app.models import AutomationRun, User
from app.schemas_crm import AutomationReport

router = APIRouter(prefix="/api/automations", tags=["crm: automations"])


@router.get("/rules", response_model=list[dict])
def rules(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    out = []
    for r in RULES:
        last = db.scalar(select(AutomationRun).where(AutomationRun.rule == r).order_by(AutomationRun.ran_at.desc()))
        out.append({"rule": r, "last_fired_at": last.ran_at if last else None})
    return out


@router.post("/run", response_model=AutomationReport)
def run(dry_run: bool = False, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return run_automations(db, dry_run=dry_run)
