"""Staff side of housing and portal v1: rooms, tenancies, documents, the maintenance queue, grants."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_admin, require_staff
from app.config import Settings, settings_dep
from app.crm_common import ensure_exists, get_or_404
from app.db import get_db
from app.files import upload_link
from app.models import (Contact, Document, MaintenanceComment, MaintenanceRequest, PortalAccessGrant, Property, Room,
                        Tenancy, User)
from app.schemas import DeleteResult
from app.schemas_housing import (CommentIn, CommentOut, DocumentCreated, DocumentIn, DocumentOut, GrantIn, GrantOut,
                                 MaintenanceOut, MaintenanceUpdate, RoomIn, RoomOut, TenancyIn, TenancyOut)

router = APIRouter(prefix="/api/housing", tags=["housing (staff)"])


def tenancy_out(t: Tenancy) -> TenancyOut:
    o = TenancyOut.model_validate(t)
    o.contact_name = t.contact.display_name if t.contact else None
    o.property_address = t.property.address if t.property else None
    o.room_name = t.room.name if t.room else None
    return o


def maintenance_out(db: Session, r: MaintenanceRequest, viewer: User | None = None, include_text: bool = True) -> MaintenanceOut:
    o = MaintenanceOut.model_validate(r)
    if not include_text or r.status == "pending_screening":
        o.description = ""  # held text is unread until the router clears it
    t = r.tenancy
    o.property_address = t.property.address if t and t.property else None
    o.room_name = t.room.name if t and t.room else None
    o.resident_name = t.contact.display_name if t and t.contact else None
    comments = db.scalars(select(MaintenanceComment).where(MaintenanceComment.request_id == r.id).order_by(MaintenanceComment.id)).all()
    o.comments = []
    for c in comments:
        co = CommentOut.model_validate(c)
        if c.screening_status in ("unreachable", "pending", "flagged"):
            co.body = ""
        co.mine = viewer is not None and c.author_id == viewer.id
        o.comments.append(co)
    return o


# ---- rooms ----
@router.get("/rooms", response_model=list[RoomOut])
def list_rooms(property_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(Room)
    if property_id is not None:
        q = q.where(Room.property_id == property_id)
    return db.scalars(q.order_by(Room.property_id, Room.name)).all()


@router.post("/rooms", response_model=RoomOut, status_code=201)
def create_room(item: RoomIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    ensure_exists(db, Property, item.property_id, "Property")
    row = Room(**item.model_dump())
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="room.create", entity="room", entity_id=row.id, details={"name": row.name})
    db.commit()
    return row


@router.put("/rooms/{room_id}", response_model=RoomOut)
def update_room(room_id: int, item: RoomIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Room, room_id, "Room")
    ensure_exists(db, Property, item.property_id, "Property")
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    write_audit(db, actor=user, action="room.update", entity="room", entity_id=row.id, details={"name": row.name})
    db.commit()
    return row


# ---- tenancies ----
@router.get("/tenancies", response_model=list[TenancyOut])
def list_tenancies(status: str | None = "active", contact_id: int | None = None, property_id: int | None = None,
                   db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(Tenancy)
    if status and status != "all":
        q = q.where(Tenancy.status == status)
    if contact_id is not None:
        q = q.where(Tenancy.contact_id == contact_id)
    if property_id is not None:
        q = q.where(Tenancy.property_id == property_id)
    return [tenancy_out(t) for t in db.scalars(q.order_by(Tenancy.id.desc())).all()]


@router.post("/tenancies", response_model=TenancyOut, status_code=201)
def create_tenancy(item: TenancyIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    ensure_exists(db, Contact, item.contact_id, "Contact")
    ensure_exists(db, Property, item.property_id, "Property")
    ensure_exists(db, Room, item.room_id, "Room")
    row = Tenancy(**item.model_dump())
    db.add(row)
    db.flush()
    contact = db.get(Contact, item.contact_id)
    if contact and contact.kind != "resident":
        contact.kind = "resident"
    if item.room_id and item.status == "active":
        db.get(Room, item.room_id).status = "occupied"
    write_audit(db, actor=user, action="tenancy.create", entity="tenancy", entity_id=row.id,
                details={"contact_id": row.contact_id, "property_id": row.property_id, "status": row.status})
    db.commit()
    db.refresh(row)
    return tenancy_out(row)


@router.get("/tenancies/{tenancy_id}", response_model=TenancyOut)
def get_tenancy(tenancy_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return tenancy_out(get_or_404(db, Tenancy, tenancy_id, "Tenancy"))


@router.put("/tenancies/{tenancy_id}", response_model=TenancyOut)
def update_tenancy(tenancy_id: int, item: TenancyIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Tenancy, tenancy_id, "Tenancy")
    ensure_exists(db, Contact, item.contact_id, "Contact")
    ensure_exists(db, Property, item.property_id, "Property")
    ensure_exists(db, Room, item.room_id, "Room")
    before = row.status
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    if before != row.status and row.room_id:
        db.get(Room, row.room_id).status = "occupied" if row.status == "active" else "available"
    write_audit(db, actor=user, action="tenancy.update", entity="tenancy", entity_id=row.id, details={"status": [before, row.status]})
    db.commit()
    db.refresh(row)
    return tenancy_out(row)


# ---- documents (metadata; bytes live on the Mac mini) ----
@router.get("/documents", response_model=list[DocumentOut])
def list_documents(tenancy_id: int | None = None, contact_id: int | None = None, property_id: int | None = None,
                   db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(Document).where(Document.status != "removed")
    for col, val in ((Document.tenancy_id, tenancy_id), (Document.contact_id, contact_id), (Document.property_id, property_id)):
        if val is not None:
            q = q.where(col == val)
    return db.scalars(q.order_by(Document.id.desc())).all()


@router.post("/documents", response_model=DocumentCreated, status_code=201)
def create_document(item: DocumentIn, db: Session = Depends(get_db), user: User = Depends(require_staff),
                    settings: Settings = Depends(settings_dep)):
    if not settings.files_service_url or not settings.files_service_secret:
        raise HTTPException(status_code=503, detail="FILES_SERVICE_URL and FILES_SERVICE_SECRET are not set")
    ensure_exists(db, Tenancy, item.tenancy_id, "Tenancy")
    ensure_exists(db, Contact, item.contact_id, "Contact")
    ensure_exists(db, Property, item.property_id, "Property")
    row = Document(**item.model_dump(), uploaded_by=user.id, uploaded_role=user.role)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="document.create", entity="document", entity_id=row.id,
                details={"title": row.title, "category": row.category, "tenancy_id": row.tenancy_id})
    db.commit()
    return DocumentCreated(document=DocumentOut.model_validate(row), upload=upload_link(settings, row.id, user.id))


@router.put("/documents/{doc_id}", response_model=DocumentOut)
def update_document(doc_id: int, item: DocumentIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, Document, doc_id, "Document")
    for k, v in item.model_dump().items():
        setattr(row, k, v)
    write_audit(db, actor=user, action="document.update", entity="document", entity_id=row.id,
                details={"shared_with_resident": row.shared_with_resident, "shared_with_case_manager": row.shared_with_case_manager})
    db.commit()
    return row


@router.delete("/documents/{doc_id}", response_model=DeleteResult)
def remove_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = get_or_404(db, Document, doc_id, "Document")
    row.status = "removed"
    write_audit(db, actor=user, action="document.remove", entity="document", entity_id=row.id, details={"title": row.title})
    db.commit()
    return DeleteResult(deleted=1)


# ---- maintenance queue ----
@router.get("/maintenance", response_model=list[MaintenanceOut])
def maintenance_queue(status: str | None = None, tenancy_id: int | None = None, limit: int = Query(200, ge=1, le=1000),
                      db: Session = Depends(get_db), user: User = Depends(require_staff)):
    q = select(MaintenanceRequest)
    if status:
        q = q.where(MaintenanceRequest.status == status)
    elif True:
        q = q.where(MaintenanceRequest.status.in_(["pending_screening", "withheld", "open", "in_progress"]))
    if tenancy_id is not None:
        q = q.where(MaintenanceRequest.tenancy_id == tenancy_id)
    return [maintenance_out(db, r, user) for r in db.scalars(q.order_by(MaintenanceRequest.id.desc()).limit(limit)).all()]


@router.get("/maintenance/{req_id}", response_model=MaintenanceOut)
def maintenance_get(req_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    return maintenance_out(db, get_or_404(db, MaintenanceRequest, req_id, "Request"), user)


@router.put("/maintenance/{req_id}", response_model=MaintenanceOut)
def maintenance_update(req_id: int, item: MaintenanceUpdate, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, MaintenanceRequest, req_id, "Request")
    if row.status in ("pending_screening", "withheld") and item.status in ("open", "in_progress", "done"):
        raise HTTPException(status_code=409, detail="This request has not cleared screening")
    changes = {}
    for k, v in item.model_dump(exclude_none=True).items():
        if getattr(row, k) != v:
            changes[k] = [getattr(row, k), v]
            setattr(row, k, v)
    if item.status in ("done", "closed") and row.resolved_at is None:
        row.resolved_at = datetime.now(timezone.utc)
    write_audit(db, actor=user, action="maintenance.update", entity="maintenance_request", entity_id=row.id, details={"changes": changes})
    db.commit()
    db.refresh(row)
    return maintenance_out(db, row, user)


@router.post("/maintenance/{req_id}/comments", response_model=MaintenanceOut, status_code=201)
def maintenance_comment(req_id: int, item: CommentIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, MaintenanceRequest, req_id, "Request")
    from app.fair_housing import protected_term_hits
    hits = protected_term_hits(item.body)
    if hits:
        raise HTTPException(status_code=422, detail=f"Comment is not allowed to carry: {', '.join(hits)}")
    db.add(MaintenanceComment(request_id=row.id, author_id=user.id, author_role=user.role, body=item.body, screening_status="clear"))
    row.updated_at = datetime.now(timezone.utc)
    write_audit(db, actor=user, action="maintenance.comment", entity="maintenance_request", entity_id=row.id, details={})
    db.commit()
    db.refresh(row)
    return maintenance_out(db, row, user)


@router.post("/maintenance/{req_id}/redact", response_model=MaintenanceOut)
def maintenance_redact(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    """Staff can drop the stored text of a request (plan Section 6: staff can redact)."""
    row = get_or_404(db, MaintenanceRequest, req_id, "Request")
    row.description = ""
    write_audit(db, actor=user, action="maintenance.redact", entity="maintenance_request", entity_id=row.id, details={})
    db.commit()
    return maintenance_out(db, row, user)


# ---- grants (staff view; management may override) ----
@router.get("/grants", response_model=list[GrantOut])
def list_grants(tenancy_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    q = select(PortalAccessGrant)
    if tenancy_id is not None:
        q = q.where(PortalAccessGrant.tenancy_id == tenancy_id)
    return db.scalars(q.order_by(PortalAccessGrant.id.desc())).all()


@router.post("/grants", response_model=GrantOut, status_code=201)
def staff_grant(item: GrantIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Management override: a grant recorded from a signed tenant authorization on file."""
    if item.tenancy_id is None:
        raise HTTPException(status_code=422, detail="tenancy_id is required")
    get_or_404(db, Tenancy, item.tenancy_id, "Tenancy")
    row = PortalAccessGrant(tenancy_id=item.tenancy_id, case_manager_email=item.case_manager_email, scopes=list(item.scopes),
                            granted_by=user.id, granted_by_role=user.role, expires_at=item.expires_at)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="grant.create", entity="portal_access_grant", entity_id=row.id,
                details={"tenancy_id": row.tenancy_id, "scopes": row.scopes, "by_role": user.role})
    db.commit()
    return row


@router.post("/grants/{grant_id}/revoke", response_model=GrantOut)
def staff_revoke(grant_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    row = get_or_404(db, PortalAccessGrant, grant_id, "Grant")
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by = datetime.now(timezone.utc), user.id
        write_audit(db, actor=user, action="grant.revoke", entity="portal_access_grant", entity_id=row.id, details={})
        db.commit()
    return row
