"""Public web form endpoints. No bearer auth: a honeypot, field limits, and a per-IP rate limit
protect the direct endpoints; the Netlify endpoint verifies Netlify's JWS signature instead.
"""
import hashlib
import time
from collections import defaultdict, deque

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings, settings_dep
from app.db import get_db
from app.forms import intake_inquiry, intake_referral, map_fields
from app.schemas_crm import FormResult, InquiryFormIn, ReferralFormIn

router = APIRouter(prefix="/api/forms", tags=["public: forms"])
_buckets: dict[str, deque] = defaultdict(deque)
FORM_NAMES = {"inquiry": ("tour-request", "tour", "inquiry", "room-inquiry", "contact"),
              "referral": ("referral-inquiry", "referral", "partner", "partner-inquiry")}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def _rate_limit(request: Request, settings: Settings) -> None:
    ip = _client_ip(request)
    now = time.time()
    q = _buckets[ip]
    while q and q[0] < now - 3600:
        q.popleft()
    if len(q) >= settings.forms_rate_limit_per_hour:
        raise HTTPException(status_code=429, detail="Too many submissions from this address. Try again later.")
    q.append(now)


async def _payload(request: Request) -> dict:
    if "application/json" in request.headers.get("content-type", ""):
        data = await request.json()
        return data if isinstance(data, dict) else {}
    form = await request.form()
    return {k: str(v) for k, v in form.items()}


def _parse(model, mapped: dict):
    try:
        return model(**{k: v for k, v in mapped.items() if k in model.model_fields})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _result(contact, deal, created) -> FormResult:
    return FormResult(contact_id=contact.id, deal_id=deal.id if deal else None, created_contact=created)


@router.post("/inquiry", response_model=FormResult, status_code=201)
async def inquiry(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    _rate_limit(request, settings)
    mapped = map_fields(await _payload(request))
    if mapped.get("website"):
        # Bots fill hidden fields. Answer as if accepted so they stop retrying; store nothing.
        return Response(status_code=204)
    contact, deal, created = intake_inquiry(db, _parse(InquiryFormIn, mapped))
    db.commit()
    return _result(contact, deal, created)


@router.post("/referral", response_model=FormResult, status_code=201)
async def referral(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    _rate_limit(request, settings)
    mapped = map_fields(await _payload(request))
    if mapped.get("website"):
        return Response(status_code=204)
    contact, deal, created = intake_referral(db, _parse(ReferralFormIn, mapped))
    db.commit()
    return _result(contact, deal, created)


@router.post("/netlify", response_model=FormResult, status_code=201, include_in_schema=False)
async def netlify(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    """Netlify Forms outgoing webhook. Netlify signs each delivery as a JWS in X-Webhook-Signature
    with claims iss=netlify and sha256=<hex digest of the raw body>."""
    if not settings.forms_webhook_secret:
        raise HTTPException(status_code=503, detail="FORMS_WEBHOOK_SECRET is not set")
    body = await request.body()
    token = request.headers.get("x-webhook-signature", "")
    try:
        claims = jwt.decode(token, settings.forms_webhook_secret, algorithms=["HS256"], issuer="netlify")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=403, detail="Invalid webhook signature") from exc
    if claims.get("sha256") != hashlib.sha256(body).hexdigest():
        raise HTTPException(status_code=403, detail="Webhook body does not match signature")
    payload = await request.json()
    form_name = str(payload.get("form_name") or "").strip().lower()
    data = payload.get("data") or {}
    mapped = map_fields(data if isinstance(data, dict) else {})
    for key in ("name", "email"):  # Netlify also lifts these to the top level of the submission
        if not mapped.get(key) and payload.get(key):
            mapped[key] = str(payload[key]).strip()
    mapped.setdefault("page", str(payload.get("site_url") or ""))
    if mapped.get("website"):
        return Response(status_code=204)
    if form_name in FORM_NAMES["referral"] or (form_name not in FORM_NAMES["inquiry"] and mapped.get("organization")):
        contact, deal, created = intake_referral(db, _parse(ReferralFormIn, mapped))
    else:
        contact, deal, created = intake_inquiry(db, _parse(InquiryFormIn, mapped))
    db.commit()
    return _result(contact, deal, created)
