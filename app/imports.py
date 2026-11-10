"""Import batches and duplicate review (comparison item 4, adopted 2026-11-09).

Every import run (CSV upload or the legacy migration) is an ImportBatch. Rows it creates
carry the batch id, so an admin can undo the run as a unit. Duplicate checks run before
insert against existing contacts and against earlier rows of the same file; matches are
reported for review instead of being merged or inserted.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Contact, Deal, ImportBatch, RecordTag, User, utcnow
from app.schemas_crm import ImportDuplicate


def norm_email(v: str | None) -> str:
    return (v or "").strip().lower()


def norm_phone(v: str | None) -> str:
    digits = re.sub(r"\D", "", v or "")
    return digits[-10:] if len(digits) >= 7 else ""


def norm_name(v: str | None) -> str:
    return re.sub(r"\s+", " ", (v or "").strip().lower())


@dataclass
class DuplicateIndex:
    """Keys seen so far: existing contacts first, then each accepted row of the file."""
    email: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    phone: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    name: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)

    @classmethod
    def from_db(cls, db: Session) -> "DuplicateIndex":
        idx = cls()
        for c in db.scalars(select(Contact).where(Contact.status == "active")).all():
            idx.add(c.email, c.phone, c.display_name, contact_id=c.id, row=None)
        return idx

    def add(self, email: str | None, phone: str | None, name: str | None, *,
            contact_id: int | None, row: int | None) -> None:
        for key, store in ((norm_email(email), self.email), (norm_phone(phone), self.phone),
                           (norm_name(name), self.name)):
            if key and key not in store:
                store[key] = (contact_id, row)

    def matches(self, row: int, email: str | None, phone: str | None, name: str | None) -> list[ImportDuplicate]:
        out = []
        for reason, key, store in (("email", norm_email(email), self.email),
                                   ("phone", norm_phone(phone), self.phone),
                                   ("name", norm_name(name), self.name)):
            if key and key in store:
                contact_id, seen_row = store[key]
                out.append(ImportDuplicate(row=row, reason=reason, value=key, existing_contact_id=contact_id,
                                           matches_row=seen_row))
        return out


def start_batch(db: Session, *, source: str, entity: str, filename: str, actor: User | None) -> ImportBatch:
    batch = ImportBatch(source=source, entity=entity, filename=filename or "",
                        created_by=actor.id if actor else None)
    db.add(batch)
    db.flush()
    return batch


def undo_batch(db: Session, batch: ImportBatch, *, actor: User) -> dict[str, int]:
    """Delete every row the batch created. Deals go first so stage history cascades;
    contact and company links on later records fall back to NULL through the foreign keys."""
    deleted = {"contacts": 0, "companies": 0, "deals": 0}
    for d in db.scalars(select(Deal).where(Deal.import_batch_id == batch.id)).all():
        db.delete(d)
        deleted["deals"] += 1
    for c in db.scalars(select(Contact).where(Contact.import_batch_id == batch.id)).all():
        for link in db.scalars(select(RecordTag).where(RecordTag.entity == "contact",
                                                       RecordTag.entity_id == c.id)).all():
            db.delete(link)
        db.delete(c)
        deleted["contacts"] += 1
    for co in db.scalars(select(Company).where(Company.import_batch_id == batch.id)).all():
        for link in db.scalars(select(RecordTag).where(RecordTag.entity == "company",
                                                       RecordTag.entity_id == co.id)).all():
            db.delete(link)
        db.delete(co)
        deleted["companies"] += 1
    batch.undone_at = utcnow()
    batch.undone_by = actor.id
    db.flush()
    return deleted
