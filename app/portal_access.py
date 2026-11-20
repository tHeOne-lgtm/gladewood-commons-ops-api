"""Who may see what in the portal (role matrix, decision 2026-11-20).

resident       own tenancies, documents shared with the resident, own maintenance requests
case_manager   tenancies with an active grant naming their email or user id, within the grant's scopes
ops_staff, management, owner, audit   every tenancy (audit reads are logged by the auth layer)
"""
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import STAFF_ROLES
from app.models import Contact, Document, PortalAccessGrant, Tenancy, User

GRANT_SCOPES = ("documents", "maintenance", "balance", "payments")


def contact_for_user(db: Session, user: User) -> Contact | None:
    """The contact record behind a portal login: by stored user id, else by email (then stored)."""
    c = db.scalar(select(Contact).where(Contact.portal_user_id == user.id))
    if c is None and user.email:
        c = db.scalar(select(Contact).where(func.lower(Contact.email) == user.email.lower(), Contact.portal_user_id.is_(None)))
        if c is not None:
            c.portal_user_id = user.id
            db.flush()
    return c


def active_grants_for(db: Session, user: User) -> list[PortalAccessGrant]:
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(PortalAccessGrant).where(
        PortalAccessGrant.revoked_at.is_(None),
        or_(PortalAccessGrant.case_manager_user_id == user.id,
            func.lower(PortalAccessGrant.case_manager_email) == (user.email or "").lower()))).all()
    out = []
    for g in rows:
        exp = g.expires_at if g.expires_at is None or g.expires_at.tzinfo else g.expires_at.replace(tzinfo=timezone.utc)
        if exp is not None and exp < now:
            continue
        if g.case_manager_user_id is None:
            g.case_manager_user_id = user.id  # first sign-in binds the grant to the account
        out.append(g)
    return out


def visible_tenancies(db: Session, user: User) -> list[Tenancy]:
    if user.role in STAFF_ROLES:
        return db.scalars(select(Tenancy).order_by(Tenancy.id)).all()
    if user.role == "resident":
        c = contact_for_user(db, user)
        return db.scalars(select(Tenancy).where(Tenancy.contact_id == c.id).order_by(Tenancy.id)).all() if c else []
    if user.role == "case_manager":
        ids = {g.tenancy_id for g in active_grants_for(db, user)}
        return db.scalars(select(Tenancy).where(Tenancy.id.in_(ids)).order_by(Tenancy.id)).all() if ids else []
    return []


def grant_for(db: Session, user: User, tenancy_id: int, scope: str) -> PortalAccessGrant | None:
    for g in active_grants_for(db, user):
        if g.tenancy_id == tenancy_id and scope in (g.scopes or []):
            return g
    return None


def can_see_tenancy(db: Session, user: User, tenancy: Tenancy, scope: str = "documents") -> bool:
    if user.role in STAFF_ROLES:
        return True
    if user.role == "resident":
        c = contact_for_user(db, user)
        return c is not None and tenancy.contact_id == c.id
    if user.role == "case_manager":
        return grant_for(db, user, tenancy.id, scope) is not None
    return False


def can_see_document(db: Session, user: User, doc: Document) -> bool:
    if user.role in STAFF_ROLES:
        return True
    if doc.tenancy_id is None:
        return False
    t = db.get(Tenancy, doc.tenancy_id)
    if t is None or doc.status != "stored":
        return False
    if user.role == "resident":
        return doc.shared_with_resident and can_see_tenancy(db, user, t)
    if user.role == "case_manager":
        return doc.shared_with_case_manager and can_see_tenancy(db, user, t, "documents")
    return False


def log_grant_read(db: Session, user: User, entity: str, entity_id: int, tenancy_id: int) -> None:
    """Every read of a grant-scoped record writes to the audit log (plan Section 6)."""
    if user.role == "case_manager":
        write_audit(db, actor=user, action="portal.grant_read", entity=entity, entity_id=entity_id,
                    details={"tenancy_id": tenancy_id})
