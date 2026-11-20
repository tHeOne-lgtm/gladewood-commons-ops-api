"""Tags across contacts, companies, and deals: list with counts, bulk add and remove."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_staff
from app.crm_common import set_tags, tags_for
from app.db import get_db
from app.models import Company, Contact, Deal, RecordTag, Tag, User
from app.schemas_crm import BulkTagIn, TagCount, TagEntity

router = APIRouter(prefix="/api/tags", tags=["crm: tags"])
MODELS = {"contact": Contact, "company": Company, "deal": Deal}


@router.get("", response_model=list[TagCount])
def list_tags(entity: TagEntity | None = None, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(Tag.name, func.count(RecordTag.id)).outerjoin(RecordTag, RecordTag.tag_id == Tag.id)
    if entity:
        q = q.where(RecordTag.entity == entity)
    rows = db.execute(q.group_by(Tag.name).order_by(Tag.name)).all()
    return [TagCount(name=n, count=c) for n, c in rows if c or entity is None]


@router.post("/bulk", response_model=dict[str, int])
def bulk(item: BulkTagIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    model = MODELS[item.entity]
    ids = [r for r in db.scalars(select(model.id).where(model.id.in_(item.ids))).all()]
    current = tags_for(db, item.entity, ids)
    changed = 0
    for rid in ids:
        after = sorted((set(current.get(rid, [])) | set(item.add)) - set(item.remove))
        if after != current.get(rid, []):
            set_tags(db, item.entity, rid, after)
            changed += 1
    write_audit(db, actor=user, action=f"{item.entity}.tags.bulk", entity=item.entity, entity_id=None,
                details={"ids": ids, "add": item.add, "remove": item.remove, "changed": changed})
    db.commit()
    return {"matched": len(ids), "changed": changed}
