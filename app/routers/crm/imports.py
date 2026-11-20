"""Import batch listing and undo (comparison item 4)."""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_admin, require_staff
from app.crm_common import get_or_404
from app.db import get_db
from app.bigin_import import parse_rows, run_import
from app.imports import undo_batch
from app.models import ImportBatch, User
from app.schemas_crm import BiginImportResult, ImportBatchOut, ImportUndoResult

router = APIRouter(prefix="/api/imports", tags=["crm: imports"])


@router.get("", response_model=list[ImportBatchOut])
def list_batches(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                 _: User = Depends(require_staff)):
    return db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(limit)).all()


@router.get("/{batch_id}", response_model=ImportBatchOut)
def get_batch(batch_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return get_or_404(db, ImportBatch, batch_id, "Import batch")


@router.post("/{batch_id}/undo", response_model=ImportUndoResult)
def undo(batch_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    batch = get_or_404(db, ImportBatch, batch_id, "Import batch")
    if batch.undone_at is not None:
        raise HTTPException(status_code=409, detail="This import was already undone")
    deleted = undo_batch(db, batch, actor=admin)
    write_audit(db, actor=admin, action="import.undo", entity="import_batch", entity_id=batch_id,
                details={"source": batch.source, "entity": batch.entity, "deleted": deleted})
    db.commit()
    return ImportUndoResult(batch_id=batch_id, deleted=deleted)


@router.post("/bigin", response_model=BiginImportResult)
async def import_bigin(accounts: UploadFile | None = None, contacts: UploadFile | None = None, dry_run: bool = True,
                       db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Upload Bigin's Accounts and Contacts exports (CSV from Settings, Data Administration, Export;
    or JSON from the API). Dry run by default: pass dry_run=false to write."""
    if accounts is None and contacts is None:
        raise HTTPException(status_code=422, detail="Upload an accounts file, a contacts file, or both")
    try:
        acc_rows = parse_rows(await accounts.read()) if accounts else []
        con_rows = parse_rows(await contacts.read()) if contacts else []
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not read the file: {exc}") from exc
    names = ", ".join(f.filename or "" for f in (accounts, contacts) if f)
    report = run_import(db, accounts=acc_rows, contacts=con_rows, actor=admin, dry_run=dry_run, filename=names)
    return BiginImportResult(**report.as_dict())
