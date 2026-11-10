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

ROLES = ("admin", "staff", "tenant", "case_manager", "pending")
STAFF_ROLES = ("admin", "staff")

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
        role = "admin" if email and email in settings.bootstrap_admin_set else "pending"
        user = User(id=sub, email=email, role=role)
        db.add(user)
        write_audit(db, actor=user, action="user.first_login", entity="user", entity_id=sub,
                    details={"role": role})
    else:
        user.last_seen_at = utcnow()
        if email and user.email != email:
            user.email = email
    db.commit()
    return user


def mfa_required(request: Request, user: User, settings: Settings) -> bool:
    """True when this staff or admin token still needs a second factor (decision 2026-11-09)."""
    if not settings.require_staff_mfa or user.role not in STAFF_ROLES:
        return False
    return getattr(request.state, "token_aal", "aal1") != "aal2"


def require_roles(*roles: str):
    def dependency(request: Request, user: User = Depends(get_current_user),
                   settings: Settings = Depends(settings_dep)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="This account does not have access to this resource")
        if mfa_required(request, user, settings):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Multi-factor authentication is required for staff accounts. "
                                       "Complete the authenticator step and sign in again.")
        return user
    return dependency


require_staff = require_roles(*STAFF_ROLES)
require_admin = require_roles("admin")
