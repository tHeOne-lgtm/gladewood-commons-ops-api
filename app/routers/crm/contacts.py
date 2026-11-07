import re
from collections import defaultdict

from fastapi import APIRouter, Depends, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import (csv_response, diff, ensure_exists, get_or_404, read_csv_upload, set_tags,
                            snapshot, tags_for)
from app.db import get_db
from app.models import Company, Contact, RecordTag, Tag, User
from app.schemas import DeleteResult
from app.schemas_crm import ContactIn, ContactOut, DuplicateGroup, ImportError_, ImportResult, TagsSet

router = APIRouter(prefix="/api/contacts", tags=["crm: contacts"])
FIELDS = list(ContactIn.model_fields)
CSV_FIELDS = ["id"] + [f for f in FIELDS if f != "extra"] + ["tags"]


def _out(db: Session, rows: list[Contact]) -> list[ContactOut]:
    tags = tags_for(db, "contact", [r.id for r in rows])
    out = []
    for r in rows:
        o = ContactOut.model_validate(r)
        o.tags = tags.get(r.id, [])
        o.company_name = r.company.name if r.company else None
        out.append(o)
    return out


def _query(q, kind, status, company_id, tag):
    stmt = select(Contact)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Contact.display_name.ilike(like), Contact.email.ilike(like),
                              Contact.phone.ilike(like), Contact.first_name.ilike(like),
                              Contact.last_name.ilike(like)))
    if kind:
        stmt = stmt.where(Contact.kind == kind)
    if status:
        stmt = stmt.where(Contact.status == status)
    if company_id is not None:
        stmt = stmt.where(Contact.company_id == company_id)
    if tag:
        stmt = stmt.where(Contact.id.in_(
            select(RecordTag.entity_id).join(Tag).where(RecordTag.entity == "contact", Tag.name == tag)))
    return stmt.order_by(Contact.display_name)


@router.get("", response_model=list[ContactOut])
def list_contacts(q: str | None = None, kind: str | None = None, status: str | None = "active",
                  company_id: int | None = None, tag: str | None = None,
                  limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), _: User = Depends(require_staff)):
    status = None if status == "all" else status
    return _out(db, db.scalars(_query(q, kind, status, company_id, tag).limit(limit).offset(offset)).all())


@router.get("/export")
def export_contacts(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows = _out(db, db.scalars(_query(None, None, None, None, None)).all())
    return csv_response("contacts.csv", CSV_FIELDS,
                        ({**r.model_dump(exclude={"extra"}), "tags": "|".join(r.tags)} for r in rows))


@router.post("/import", response_model=ImportResult)
async def import_contacts(file: UploadFile, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    rows = await read_csv_upload(file)
    created, errors = 0, []
    for i, raw in enumerate(rows, start=2):
        try:
            data = {k: v for k, v in raw.items() if k in FIELDS and k != "extra"}
            if data.get("company_id") == "":
                data["company_id"] = None
            item = ContactIn(**data)
            if item.company_id is not None and db.get(Company, item.company_id) is None:
                raise ValueError(f"company_id {item.company_id} does not exist")
        except (ValidationError, ValueError) as exc:
            msg = "; ".join(e["msg"] for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
            errors.append(ImportError_(row=i, error=msg))
            continue
        row = Contact(**item.model_dump())
        db.add(row)
        db.flush()
        tags = [t for t in (raw.get("tags") or "").split("|") if t.strip()]
        if tags:
            set_tags(db, "contact", row.id, tags)
        created += 1
    write_audit(db, actor=user, action="contact.import", entity="contact",
                details={"created": created, "errors": len(errors)})
    db.commit()
    return ImportResult(created=created, errors=errors)


@router.get("/duplicates", response_model=list[DuplicateGroup])
def duplicates(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    rows = db.scalars(select(Contact).where(Contact.status == "active")).all()
    by: dict[tuple[str, str], list[int]] = defaultdict(list)
    for r in rows:
        if r.email:
            by[("email", r.email.lower())].append(r.id)
        digits = re.sub(r"\D", "", r.phone or "")
        if len(digits) >= 7:
            by[("phone", digits[-10:])].append(r.id)
        by[("name", r.display_name.strip().lower())].append(r.id)
    return [DuplicateGroup(reason=k[0], value=k[1], contact_ids=sorted(v))
            for k, v in sorted(by.items()) if len(v) > 1]


@router.get("/{row_id}", response_model=ContactOut)
def get_contact(row_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return _out(db, [get_or_404(db, Contact, row_id, "Contact")])[0]


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(item: ContactIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    ensure_exists(db, Company, item.company_id, "Company")
    row = Contact(**item.model_dump())
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="contact.create", entity="contact", entity_id=row.id,
                details=snapshot(row, FIELDS))
    db.commit()
    db.refresh(row)
    return _out(db, [row])[0]


@router.put("/{row_id}", response_model=ContactOut)
def update_contact(row_id: int, item: ContactIn, db: Session = Depends(get_db),
                   user: User = Depends(require_staff)):
    row = get_or_404(db, Contact, row_id, "Contact")
    ensure_exists(db, Company, item.company_id, "Company")
    before = snapshot(row, FIELDS)
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    write_audit(db, actor=user, action="contact.update", entity="contact", entity_id=row_id,
                details={"changes": diff(before, snapshot(row, FIELDS))})
    db.commit()
    db.refresh(row)
    return _out(db, [row])[0]


@router.put("/{row_id}/tags", response_model=ContactOut)
def set_contact_tags(row_id: int, payload: TagsSet, db: Session = Depends(get_db),
                     user: User = Depends(require_staff)):
    row = get_or_404(db, Contact, row_id, "Contact")
    before = tags_for(db, "contact", [row_id])[row_id]
    after = set_tags(db, "contact", row_id, payload.tags)
    if before != after:
        write_audit(db, actor=user, action="contact.tags", entity="contact", entity_id=row_id,
                    details={"changes": {"tags": [before, after]}})
    db.commit()
    return _out(db, [row])[0]


@router.delete("/{row_id}", response_model=DeleteResult)
def delete_contact(row_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Contact, row_id, "Contact")
    write_audit(db, actor=user, action="contact.delete", entity="contact", entity_id=row_id,
                details=snapshot(row, FIELDS))
    for link in db.scalars(select(RecordTag).where(RecordTag.entity == "contact",
                                                   RecordTag.entity_id == row_id)).all():
        db.delete(link)
    db.delete(row)
    db.commit()
    return DeleteResult(deleted=row_id)
