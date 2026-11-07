from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import Health

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=Health)
def health(response: Response, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return Health(ok=True, db=True)
    except Exception:
        response.status_code = 503
        return Health(ok=False, db=False)
