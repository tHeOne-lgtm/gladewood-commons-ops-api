"""Demand KPIs derived from prospects."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_staff
from app.db import get_db
from app.models import Prospect, User
from app.routers.financials import read_financials
from app.schemas import DemandSummary

SCREENED_STATUSES = {"Screened", "Income-verified", "Deposit received", "Confirmed"}
DEPOSIT_STATUSES = {"Deposit received", "Confirmed"}
DEFAULT_TARGET = 6

router = APIRouter(prefix="/api/demand-summary", tags=["demand"])


@router.get("", response_model=DemandSummary)
def demand_summary(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows = db.scalars(select(Prospect)).all()
    target_raw = read_financials(db).get("demand_target", "")
    try:
        target = int(target_raw) if target_raw else DEFAULT_TARGET
    except ValueError:
        target = DEFAULT_TARGET
    return DemandSummary(
        raw_inquiries=len(rows),
        screened=sum(1 for r in rows if r.status in SCREENED_STATUSES),
        income_verified=sum(1 for r in rows if r.income_verified == "Verified"),
        holding_deposit=sum(1 for r in rows if r.status in DEPOSIT_STATUSES),
        target=target,
    )
