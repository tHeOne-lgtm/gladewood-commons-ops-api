from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import get_or_404
from app.db import get_db
from app.models import Activity, Company, Contact, Deal, Note, Property, User
from app.schemas import DeleteResult
from app.schemas_crm import NoteIn, NoteOut

router = APIRouter(prefix="/api/notes", tags=["crm: notes"])
ENTITY_MODELS = {"contact": Contact, "company": Company, "deal": Deal, "property": Property, "activity": Activity}


@router.get("", response_model=list[NoteOut])
def list_notes(entity: str, entity_id: int, limit: int = Query(200, ge=1, le=1000),
               db: Session = Depends(get_db), _: User = Depends(require_staff)):
    stmt = select(Note).where(Note.entity == entity, Note.entity_id == entity_id).order_by(Note.created_at.desc())
    return db.scalars(stmt.limit(limit)).all()


@router.post("", response_model=NoteOut, status_code=201)
def create_note(item: NoteIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    if db.get(ENTITY_MODELS[item.entity], item.entity_id) is None:
        raise HTTPException(status_code=422, detail=f"{item.entity} {item.entity_id} does not exist")
    row = Note(**item.model_dump(), author_id=user.id, author_email=user.email)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="note.create", entity=item.entity, entity_id=item.entity_id,
                details={"note_id": row.id})
    db.commit()
    db.refresh(row)
    return row


@router.put("/{row_id}", response_model=NoteOut)
def update_note(row_id: int, body: dict, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Note, row_id, "Note")
    text = (body.get("body") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="body is required")
    if row.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the author or an admin can edit a note")
    row.body = text
    write_audit(db, actor=user, action="note.update", entity=row.entity, entity_id=row.entity_id,
                details={"note_id": row.id})
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{row_id}", response_model=DeleteResult)
def delete_note(row_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Note, row_id, "Note")
    if row.author_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the author or an admin can delete a note")
    write_audit(db, actor=user, action="note.delete", entity=row.entity, entity_id=row.entity_id,
                details={"note_id": row.id, "body": row.body})
    db.delete(row)
    db.commit()
    return DeleteResult(deleted=row_id)
