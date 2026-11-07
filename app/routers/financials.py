"""Planning key/value store. This is not the ledger; it feeds the financial model only."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.db import get_db
from app.models import Financial, User
from app.schemas import FinancialsUpdate

FINANCIAL_KEYS = [
    "lease_rent", "utilities", "internet", "cleaning", "insurance", "furnishing",
    "private_room_rate", "shared_room_rate", "net_profit_target", "breakeven_occupancy",
    "demand_target",
]

router = APIRouter(prefix="/api/financials", tags=["financials"])


def read_financials(db: Session) -> dict[str, str]:
    result = {k: "" for k in FINANCIAL_KEYS}
    for row in db.scalars(select(Financial)).all():
        if row.key in result:
            result[row.key] = row.value
    return result


@router.get("", response_model=dict[str, str])
def get_financials(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return read_financials(db)


@router.put("", response_model=dict[str, str])
def put_financials(payload: FinancialsUpdate, db: Session = Depends(get_db),
                   user: User = Depends(require_staff)):
    changes = {}
    for k, v in payload.values.items():
        if k not in FINANCIAL_KEYS:
            continue
        row = db.get(Financial, k)
        if row is None:
            row = Financial(key=k, value=v)
            db.add(row)
            changes[k] = ["", v]
        elif row.value != v:
            changes[k] = [row.value, v]
            row.value = v
    if changes:
        write_audit(db, actor=user, action="financials.update", entity="financials",
                    details={"changes": changes})
    db.commit()
    return read_financials(db)
