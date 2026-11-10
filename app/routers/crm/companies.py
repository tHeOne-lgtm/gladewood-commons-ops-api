from fastapi import APIRouter, Depends, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import csv_response, diff, get_or_404, read_csv_upload, snapshot
from app.db import get_db
from app.imports import start_batch
from app.models import Company, User
from app.schemas import DeleteResult
from app.schemas_crm import CompanyIn, CompanyOut, ImportError_, ImportResult

router = APIRouter(prefix="/api/companies", tags=["crm: companies"])
FIELDS = list(CompanyIn.model_fields)
CSV_FIELDS = ["id"] + [f for f in FIELDS if f != "extra"]


def _query(q: str | None, kind: str | None):
    stmt = select(Company)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.email.ilike(like), Company.phone.ilike(like)))
    if kind:
        stmt = stmt.where(Company.kind == kind)
    return stmt.order_by(Company.name)


@router.get("", response_model=list[CompanyOut])
def list_companies(q: str | None = None, kind: str | None = None,
                   limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                   db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return db.scalars(_query(q, kind).limit(limit).offset(offset)).all()


@router.get("/export")
def export_companies(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows = (snapshot(c, CSV_FIELDS) for c in db.scalars(_query(None, None)).all())
    return csv_response("companies.csv", CSV_FIELDS, rows)


@router.post("/import", response_model=ImportResult)
async def import_companies(file: UploadFile, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    rows = await read_csv_upload(file)
    batch = start_batch(db, source="csv", entity="company", filename=file.filename or "", actor=user)
    created, errors = 0, []
    for i, raw in enumerate(rows, start=2):
        try:
            item = CompanyIn(**{k: v for k, v in raw.items() if k in FIELDS and k != "extra"})
        except ValidationError as exc:
            errors.append(ImportError_(row=i, error="; ".join(e["msg"] for e in exc.errors())))
            continue
        db.add(Company(**item.model_dump(), import_batch_id=batch.id))
        created += 1
    batch.row_count, batch.created_count, batch.error_count = len(rows), created, len(errors)
    write_audit(db, actor=user, action="company.import", entity="company", entity_id=batch.id,
                details={"batch_id": batch.id, "created": created, "errors": len(errors)})
    db.commit()
    return ImportResult(batch_id=batch.id, created=created, errors=errors)


@router.get("/{row_id}", response_model=CompanyOut)
def get_company(row_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return get_or_404(db, Company, row_id, "Company")


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(item: CompanyIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = Company(**item.model_dump())
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="company.create", entity="company", entity_id=row.id,
                details=snapshot(row, FIELDS))
    db.commit()
    db.refresh(row)
    return row


@router.put("/{row_id}", response_model=CompanyOut)
def update_company(row_id: int, item: CompanyIn, db: Session = Depends(get_db),
                   user: User = Depends(require_staff)):
    row = get_or_404(db, Company, row_id, "Company")
    before = snapshot(row, FIELDS)
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    write_audit(db, actor=user, action="company.update", entity="company", entity_id=row_id,
                details={"changes": diff(before, snapshot(row, FIELDS))})
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{row_id}", response_model=DeleteResult)
def delete_company(row_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Company, row_id, "Company")
    write_audit(db, actor=user, action="company.delete", entity="company", entity_id=row_id,
                details=snapshot(row, FIELDS))
    db.delete(row)
    db.commit()
    return DeleteResult(deleted=row_id)
