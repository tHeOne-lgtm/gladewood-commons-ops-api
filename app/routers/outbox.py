"""The outbound queue (Atlas gap 2). Staff draft and edit; an admin approves, pauses and dispatches."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin, require_staff
from app.config import Settings, settings_dep
from app.crm_common import get_or_404
from app.db import get_db
from app.models import Contact, Deal, OutboxItem, User
from app.outbox import (FLAG_PAUSED, FLAG_SHADOW, OPEN_STATUSES, OutboxError, approve_item, cancel_item, create_item, delivery_status,
                        dispatch, flag, is_paused, is_shadow, set_flag, text_hours_open, update_item)
from app.schemas_outbox import DispatchReport, FlagsIn, FlagsOut, OutboxEditIn, OutboxIn, OutboxOut

router = APIRouter(prefix="/api/outbox", tags=["outbox"])


def _out(db: Session, row: OutboxItem) -> OutboxOut:
    o = OutboxOut.model_validate(row)
    o.delivery_status = delivery_status(db, row)
    return o


def _raise(exc: OutboxError):
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _flags(db: Session, settings: Settings) -> FlagsOut:
    return FlagsOut(paused=is_paused(db, settings), shadow=is_shadow(db, settings), env_paused=settings.outbox_paused,
                    env_shadow=settings.outbox_shadow, flag_paused=flag(db, FLAG_PAUSED) == "true",
                    flag_shadow=flag(db, FLAG_SHADOW) == "true", text_hours_open=text_hours_open(settings),
                    text_hours=settings.outbox_text_hours, timezone=settings.outbox_timezone,
                    allowed_prices_set=bool(settings.outbox_allowed_prices.strip()))


@router.get("", response_model=list[OutboxOut])
def list_items(status: str | None = None, contact_id: int | None = None, thread_key: str | None = None,
               open_only: bool = False, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
               _: User = Depends(require_staff)):
    q = select(OutboxItem)
    if status:
        q = q.where(OutboxItem.status == status)
    if open_only:
        q = q.where(OutboxItem.status.in_(OPEN_STATUSES))
    if contact_id is not None:
        q = q.where(OutboxItem.contact_id == contact_id)
    if thread_key:
        q = q.where(OutboxItem.thread_key == thread_key)
    return [_out(db, r) for r in db.scalars(q.order_by(OutboxItem.id.desc()).limit(limit)).all()]


@router.post("", response_model=OutboxOut, status_code=201)
def create(item: OutboxIn, db: Session = Depends(get_db), user: User = Depends(require_staff),
           settings: Settings = Depends(settings_dep)):
    contact = get_or_404(db, Contact, item.contact_id, "Contact")
    deal = get_or_404(db, Deal, item.deal_id, "Deal") if item.deal_id else None
    try:
        row = create_item(db, settings, channel=item.channel, contact=contact, deal=deal, subject=item.subject, body=item.body,
                          marketing=item.marketing, send_after=item.send_after, allow_outside_window=item.allow_outside_window,
                          in_reply_to_email_id=item.in_reply_to_email_id, created_by=user.id, actor=user)
    except OutboxError as exc:
        _raise(exc)
    db.commit()
    return _out(db, row)


@router.get("/flags", response_model=FlagsOut)
def flags(db: Session = Depends(get_db), _: User = Depends(require_staff), settings: Settings = Depends(settings_dep)):
    return _flags(db, settings)


@router.put("/flags", response_model=FlagsOut)
def put_flags(item: FlagsIn, db: Session = Depends(get_db), user: User = Depends(require_admin),
              settings: Settings = Depends(settings_dep)):
    """The kill switch and shadow mode, flipped from the staff app. The environment values are a floor:
    OUTBOX_PAUSED=true or OUTBOX_SHADOW=true cannot be turned off here."""
    if item.paused is not None:
        set_flag(db, FLAG_PAUSED, "true" if item.paused else "false", user)
    if item.shadow is not None:
        set_flag(db, FLAG_SHADOW, "true" if item.shadow else "false", user)
    db.commit()
    return _flags(db, settings)


@router.post("/dispatch", response_model=DispatchReport)
def dispatch_now(request: Request, db: Session = Depends(get_db), _: User = Depends(require_admin),
                 settings: Settings = Depends(settings_dep)):
    """Run the gates once, now, instead of waiting for the cron."""
    return DispatchReport(**dispatch(db, settings, email_transport=getattr(request.app.state, "email_transport", None),
                                     twilio_transport=getattr(request.app.state, "twilio_transport", None)))


@router.get("/{item_id}", response_model=OutboxOut)
def get_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return _out(db, get_or_404(db, OutboxItem, item_id, "Outbox row"))


@router.put("/{item_id}", response_model=OutboxOut)
def edit_item(item_id: int, item: OutboxEditIn, db: Session = Depends(get_db), user: User = Depends(require_staff),
              settings: Settings = Depends(settings_dep)):
    row = get_or_404(db, OutboxItem, item_id, "Outbox row")
    changes = item.model_dump(exclude_unset=True)
    if row.channel != "email" and changes.get("body") and len(changes["body"]) > 1600:
        raise HTTPException(status_code=422, detail="a text body is at most 1600 characters")
    try:
        update_item(db, settings, row, user, **changes)
    except OutboxError as exc:
        _raise(exc)
    db.commit()
    return _out(db, row)


@router.post("/{item_id}/approve", response_model=OutboxOut)
def approve(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin),
            settings: Settings = Depends(settings_dep)):
    row = get_or_404(db, OutboxItem, item_id, "Outbox row")
    try:
        approve_item(db, settings, row, user)
    except OutboxError as exc:
        _raise(exc)
    db.commit()
    return _out(db, row)


@router.post("/{item_id}/cancel", response_model=OutboxOut)
def cancel(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    row = get_or_404(db, OutboxItem, item_id, "Outbox row")
    try:
        cancel_item(db, row, user)
    except OutboxError as exc:
        _raise(exc)
    db.commit()
    return _out(db, row)
