"""Portal v1 for residents and case managers: profile, tenancies, documents, maintenance, grants."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_portal
from app.config import Settings, settings_dep
from app.crm_common import get_or_404
from app.db import get_db
from app.files import download_link
from app.models import Document, MaintenanceComment, MaintenanceRequest, PortalAccessGrant, Tenancy, User
from app.portal_access import (active_grants_for, can_see_document, can_see_tenancy, contact_for_user, log_grant_read,
                               visible_tenancies)
from app.routers.housing import maintenance_out, tenancy_out
from app.rule11 import apply_result, screen
from app.schemas_housing import (CommentIn, DocumentOut, GrantIn, GrantOut, MaintenanceIn, MaintenanceOut, PortalProfile,
                                 ProfileUpdate)

router = APIRouter(prefix="/api/portal", tags=["portal"])


def _transport(request: Request):
    return getattr(request.app.state, "rule11_transport", None)


@router.get("/me", response_model=PortalProfile)
def me(db: Session = Depends(get_db), user: User = Depends(require_portal)):
    c = contact_for_user(db, user)
    tenancies = visible_tenancies(db, user)
    grants = active_grants_for(db, user) if user.role == "case_manager" else \
        db.scalars(select(PortalAccessGrant).where(PortalAccessGrant.tenancy_id.in_([t.id for t in tenancies] or [0]),
                                                   PortalAccessGrant.revoked_at.is_(None))).all()
    db.commit()
    return PortalProfile(role=user.role, email=user.email, display_name=c.display_name if c else None,
                         first_name=c.first_name if c else "", phone=c.phone if c else "", contact_id=c.id if c else None,
                         tenancies=[tenancy_out(t) for t in tenancies], grants=list(grants))


@router.put("/me", response_model=PortalProfile)
def update_me(item: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(require_portal)):
    c = contact_for_user(db, user)
    if c is None:
        raise HTTPException(status_code=404, detail="No resident record is linked to this login yet. Ask Paul.")
    changes = {}
    for k in ("first_name", "phone"):
        v = getattr(item, k)
        if v and getattr(c, k) != v:
            changes[k] = [getattr(c, k), v]
            setattr(c, k, v)
    if changes:
        write_audit(db, actor=user, action="portal.profile_update", entity="contact", entity_id=c.id, details={"changes": changes})
    db.commit()
    return me(db, user)


def _own_tenancy(db: Session, user: User, tenancy_id: int | None, scope: str = "maintenance") -> Tenancy:
    tenancies = visible_tenancies(db, user)
    if tenancy_id is None:
        if len(tenancies) == 1:
            return tenancies[0]
        raise HTTPException(status_code=422, detail="tenancy_id is required")
    t = get_or_404(db, Tenancy, tenancy_id, "Tenancy")
    if not can_see_tenancy(db, user, t, scope):
        raise HTTPException(status_code=404, detail="Tenancy not found")
    return t


# ---- documents ----
@router.get("/documents", response_model=list[DocumentOut])
def documents(tenancy_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require_portal)):
    tenancies = visible_tenancies(db, user) if tenancy_id is None else [_own_tenancy(db, user, tenancy_id, "documents")]
    out = []
    for t in tenancies:
        if user.role == "case_manager" and not can_see_tenancy(db, user, t, "documents"):
            continue
        for d in db.scalars(select(Document).where(Document.tenancy_id == t.id, Document.status == "stored").order_by(Document.id.desc())).all():
            if can_see_document(db, user, d):
                out.append(d)
                log_grant_read(db, user, "document", d.id, t.id)
    db.commit()
    return out


@router.get("/documents/{doc_id}/link")
def document_link(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_portal),
                  settings: Settings = Depends(settings_dep)):
    d = get_or_404(db, Document, doc_id, "Document")
    if not can_see_document(db, user, d):
        raise HTTPException(status_code=404, detail="Document not found")
    if not settings.files_service_url or not settings.files_service_secret:
        raise HTTPException(status_code=503, detail="File service is not configured")
    write_audit(db, actor=user, action="document.download_link", entity="document", entity_id=d.id, details={"tenancy_id": d.tenancy_id})
    db.commit()
    return download_link(settings, d.id, d.storage_key, user.id)


# ---- maintenance ----
@router.get("/maintenance", response_model=list[MaintenanceOut])
def my_requests(db: Session = Depends(get_db), user: User = Depends(require_portal)):
    ids = [t.id for t in visible_tenancies(db, user) if user.role == "resident" or can_see_tenancy(db, user, t, "maintenance")]
    rows = db.scalars(select(MaintenanceRequest).where(MaintenanceRequest.tenancy_id.in_(ids or [0]))
                      .order_by(MaintenanceRequest.id.desc())).all()
    out = []
    for r in rows:
        include = user.role == "resident" and r.submitted_by == user.id and r.status != "withheld"
        out.append(maintenance_out(db, r, user, include_text=include))
        log_grant_read(db, user, "maintenance_request", r.id, r.tenancy_id)
    db.commit()
    return out


@router.post("/maintenance", response_model=MaintenanceOut, status_code=201)
def submit_request(item: MaintenanceIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_portal),
                   settings: Settings = Depends(settings_dep)):
    if user.role != "resident":
        raise HTTPException(status_code=403, detail="Only residents submit maintenance requests")
    t = _own_tenancy(db, user, item.tenancy_id)
    row = MaintenanceRequest(tenancy_id=t.id, submitted_by=user.id, category=item.category, title=item.title[:120],
                             description=item.description)
    db.add(row)
    db.flush()
    res = screen(settings, channel="portal.maintenance", category=item.category, text=f"{item.title}\n{item.description}",
                 ref=f"maintenance_requests:{row.id}", transport=_transport(request))
    if res.status == "flagged":
        row.title = ""  # the title is free text too
    apply_result(db, row, res, channel="portal.maintenance", settings=settings)
    write_audit(db, actor=user, action="maintenance.submit", entity="maintenance_request", entity_id=row.id,
                details={"tenancy_id": t.id, "category": item.category, "screening": row.screening_status})
    db.commit()
    db.refresh(row)
    return maintenance_out(db, row, user, include_text=row.status != "withheld")


@router.get("/maintenance/{req_id}", response_model=MaintenanceOut)
def my_request(req_id: int, db: Session = Depends(get_db), user: User = Depends(require_portal)):
    r = get_or_404(db, MaintenanceRequest, req_id, "Request")
    t = db.get(Tenancy, r.tenancy_id)
    if not can_see_tenancy(db, user, t, "maintenance"):
        raise HTTPException(status_code=404, detail="Request not found")
    log_grant_read(db, user, "maintenance_request", r.id, r.tenancy_id)
    db.commit()
    return maintenance_out(db, r, user, include_text=user.role == "resident" and r.submitted_by == user.id)


@router.post("/maintenance/{req_id}/comments", response_model=MaintenanceOut, status_code=201)
def comment(req_id: int, item: CommentIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_portal),
            settings: Settings = Depends(settings_dep)):
    r = get_or_404(db, MaintenanceRequest, req_id, "Request")
    t = db.get(Tenancy, r.tenancy_id)
    if not can_see_tenancy(db, user, t, "maintenance"):
        raise HTTPException(status_code=404, detail="Request not found")
    if r.status in ("pending_screening", "withheld"):
        raise HTTPException(status_code=409, detail="This request is still being reviewed")
    c = MaintenanceComment(request_id=r.id, author_id=user.id, author_role=user.role, body=item.body, screening_status="pending")
    db.add(c)
    db.flush()
    res = screen(settings, channel="portal.comment", category="comment", text=item.body, ref=f"maintenance_comments:{c.id}",
                 transport=_transport(request))
    apply_result(db, c, res, channel="portal.comment", settings=settings)
    r.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(r)
    return maintenance_out(db, r, user, include_text=user.role == "resident" and r.submitted_by == user.id)


# ---- grants (resident gives, revokes; case manager sees what they received) ----
@router.get("/grants", response_model=list[GrantOut])
def grants(db: Session = Depends(get_db), user: User = Depends(require_portal)):
    if user.role == "case_manager":
        out = active_grants_for(db, user)
        db.commit()
        return out
    ids = [t.id for t in visible_tenancies(db, user)] or [0]
    return db.scalars(select(PortalAccessGrant).where(PortalAccessGrant.tenancy_id.in_(ids)).order_by(PortalAccessGrant.id.desc())).all()


@router.post("/grants", response_model=GrantOut, status_code=201)
def give_grant(item: GrantIn, db: Session = Depends(get_db), user: User = Depends(require_portal)):
    if user.role != "resident":
        raise HTTPException(status_code=403, detail="Only the resident can grant access to their records")
    t = _own_tenancy(db, user, item.tenancy_id, "documents")
    if item.case_manager_email == (user.email or "").lower():
        raise HTTPException(status_code=422, detail="Enter the case manager's email, not your own")
    row = PortalAccessGrant(tenancy_id=t.id, case_manager_email=item.case_manager_email, scopes=list(item.scopes),
                            granted_by=user.id, granted_by_role="resident", expires_at=item.expires_at)
    db.add(row)
    db.flush()
    write_audit(db, actor=user, action="grant.create", entity="portal_access_grant", entity_id=row.id,
                details={"tenancy_id": t.id, "scopes": row.scopes, "by_role": "resident"})
    db.commit()
    return row


@router.post("/grants/{grant_id}/revoke", response_model=GrantOut)
def revoke_grant(grant_id: int, db: Session = Depends(get_db), user: User = Depends(require_portal)):
    row = get_or_404(db, PortalAccessGrant, grant_id, "Grant")
    t = db.get(Tenancy, row.tenancy_id)
    if user.role != "resident" or not can_see_tenancy(db, user, t):
        raise HTTPException(status_code=404, detail="Grant not found")
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by = datetime.now(timezone.utc), user.id
        write_audit(db, actor=user, action="grant.revoke", entity="portal_access_grant", entity_id=row.id, details={})
        db.commit()
    return row
