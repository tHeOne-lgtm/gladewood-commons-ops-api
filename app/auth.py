"""Supabase Auth JWT verification and role checks.

Two verification modes:
- SUPABASE_JWT_SECRET set: legacy HS256 shared secret.
- SUPABASE_URL set: asymmetric keys fetched from the project's JWKS endpoint.
"""
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.config import Settings, settings_dep
from app.db import get_db
from app.models import User, utcnow

# Six portal roles (decision 2026-11-20) plus "pending" for a fresh sign-in.
ROLES = ("owner", "management", "ops_staff", "audit", "case_manager", "resident", "pending")
STAFF_ROLES = ("owner", "management", "ops_staff", "audit")   # CRM access; audit is read-only
ADMIN_ROLES = ("owner", "management")                          # settings, roles, grant overrides, sends
PORTAL_ROLES = ("resident", "case_manager")
ROLE_ALIASES = {"admin": "owner", "staff": "ops_staff", "tenant": "resident"}  # pre-2026-11-20 names


def normalize_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def _jwk_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_keys=True)


def decode_token(token: str, settings: Settings) -> dict:
    if settings.supabase_jwt_secret:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
        )
    if settings.supabase_url:
        jwks_url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        signing_key = _jwk_client(jwks_url).get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=["ES256", "RS256", "EdDSA"],
            audience=settings.jwt_audience,
        )
    raise RuntimeError("Authentication is not configured: set SUPABASE_JWT_SECRET or SUPABASE_URL")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> User:
    if creds is None or not creds.credentials:
        raise _unauthorized("Missing bearer token")
    try:
        claims = decode_token(creds.credentials, settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired token") from exc
    sub = claims.get("sub")
    if not sub:
        raise _unauthorized("Token has no subject")
    email = (claims.get("email") or "").lower()
    request.state.token_aal = claims.get("aal") or "aal1"

    user = db.get(User, sub)
    if user is None:
        role = "owner" if email and email in settings.bootstrap_admin_set else "pending"
        user = User(id=sub, email=email, role=role)
        db.add(user)
        write_audit(db, actor=user, action="user.first_login", entity="user", entity_id=sub,
                    details={"role": role})
    else:
        user.last_seen_at = utcnow()
        if email and user.email != email:
            user.email = email
        if user.role in ROLE_ALIASES:
            user.role = normalize_role(user.role)
    db.commit()
    return user


def mfa_required(request: Request, user: User, settings: Settings) -> bool:
    """True when this staff or admin token still needs a second factor (decision 2026-11-09)."""
    if not settings.require_staff_mfa or user.role not in STAFF_ROLES:
        return False
    return getattr(request.state, "token_aal", "aal1") != "aal2"


def require_roles(*roles: str):
    def dependency(request: Request, user: User = Depends(get_current_user),
                   settings: Settings = Depends(settings_dep), db: Session = Depends(get_db)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="This account does not have access to this resource")
        if mfa_required(request, user, settings):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Multi-factor authentication is required for staff accounts. "
                                       "Complete the authenticator step and sign in again.")
        if user.role == "audit":
            # Audit / Governance: read everything, change nothing, and every read is logged.
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                    detail="The audit role is read-only")
            write_audit(db, actor=user, action="audit.read", entity="request", entity_id=None,
                        details={"path": request.url.path, "query": str(request.url.query)[:300]})
            db.commit()
        return user
    return dependency


require_staff = require_roles(*STAFF_ROLES)
require_admin = require_roles(*ADMIN_ROLES)
require_owner = require_roles("owner")
require_portal = require_roles(*PORTAL_ROLES)
require_any_signed_in = require_roles(*ROLES)
