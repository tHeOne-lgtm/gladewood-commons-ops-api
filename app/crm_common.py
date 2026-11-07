"""Helpers shared by the CRM routers."""
import csv
import io
from decimal import Decimal
from typing import Iterable, Sequence, Type

from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Base, RecordTag, Tag


def get_or_404(db: Session, model: Type[Base], row_id: int, what: str = "Record") -> Base:
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row


def ensure_exists(db: Session, model: Type[Base], row_id: int | None, what: str) -> None:
    if row_id is not None and db.get(model, row_id) is None:
        raise HTTPException(status_code=422, detail=f"{what} {row_id} does not exist")


def snapshot(row: Base, fields: Iterable[str]) -> dict:
    out = {}
    for f in fields:
        v = getattr(row, f)
        out[f] = str(v) if isinstance(v, Decimal) else (v.isoformat() if hasattr(v, "isoformat") else v)
    return out


def diff(before: dict, after: dict) -> dict:
    return {k: [before[k], after[k]] for k in after if before.get(k) != after[k]}


def tags_for(db: Session, entity: str, entity_ids: Sequence[int]) -> dict[int, list[str]]:
    if not entity_ids:
        return {}
    rows = db.scalars(select(RecordTag).where(RecordTag.entity == entity,
                                              RecordTag.entity_id.in_(list(entity_ids)))).all()
    out: dict[int, list[str]] = {i: [] for i in entity_ids}
    for r in rows:
        out[r.entity_id].append(r.tag.name)
    for v in out.values():
        v.sort()
    return out


def set_tags(db: Session, entity: str, entity_id: int, names: list[str]) -> list[str]:
    existing = db.scalars(select(RecordTag).where(RecordTag.entity == entity,
                                                  RecordTag.entity_id == entity_id)).all()
    current = {r.tag.name: r for r in existing}
    wanted = set(names)
    for name, link in current.items():
        if name not in wanted:
            db.delete(link)
    for name in wanted - set(current):
        tag = db.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        db.add(RecordTag(entity=entity, entity_id=entity_id, tag_id=tag.id))
    db.flush()
    return sorted(wanted)


def csv_response(filename: str, fields: list[str], rows: Iterable[dict]) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


async def read_csv_upload(file: UploadFile, max_bytes: int = 5_000_000) -> list[dict]:
    raw = await file.read()
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="CSV larger than 5 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
