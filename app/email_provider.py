"""Outbound email through one of three drivers, chosen by EMAIL_PROVIDER.

resend  Resend REST API (campaign metrics come back through its webhook). Source fact (Resend docs
        via search, 2026-11-20): POST https://api.resend.com/emails with a bearer key; batch endpoint
        takes up to 100. Assumption: `reply_to` and `headers` are accepted fields (not verified
        this session because resend.com is blocked from the build environment).
smtp    Any SMTP relay with STARTTLS, for example Google Workspace. No delivery metrics.
log     Nothing leaves the server; the row is still written. Default, so a fresh deploy cannot
        send by accident.
"""
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import make_msgid

import httpx

from app.config import Settings

RESEND_URL = "https://api.resend.com/emails"


class EmailSendError(RuntimeError):
    pass


def send_email(settings: Settings, *, to: str, subject: str, text: str, html: str,
               headers: dict[str, str] | None = None, transport: httpx.BaseTransport | None = None) -> str:
    """Send one message and return the provider's message id."""
    provider = settings.email_provider
    if provider == "log":
        return f"log-{uuid.uuid4()}"
    if provider == "resend":
        if not settings.resend_api_key:
            raise EmailSendError("RESEND_API_KEY is not set")
        payload: dict = {"from": settings.email_from, "to": [to], "subject": subject, "text": text, "html": html}
        if settings.email_reply_to:
            payload["reply_to"] = settings.email_reply_to
        if headers:
            payload["headers"] = headers
        with httpx.Client(timeout=20, transport=transport) as client:
            r = client.post(RESEND_URL, json=payload, headers={"Authorization": f"Bearer {settings.resend_api_key}"})
        if r.status_code >= 300:
            raise EmailSendError(f"Resend {r.status_code}: {r.text[:300]}")
        data = r.json()
        if not data.get("id"):
            raise EmailSendError("Resend returned no message id")
        return str(data["id"])
    if provider == "smtp":
        if not settings.smtp_host:
            raise EmailSendError("SMTP_HOST is not set")
        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = to
        msg["Subject"] = subject
        if settings.email_reply_to:
            msg["Reply-To"] = settings.email_reply_to
        msg_id = make_msgid()
        msg["Message-ID"] = msg_id
        for k, v in (headers or {}).items():
            msg[k] = v
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                s.starttls()
                if settings.smtp_user:
                    s.login(settings.smtp_user, settings.smtp_password)
                s.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailSendError(f"SMTP: {exc}") from exc
        return msg_id.strip("<>")
    raise EmailSendError(f"Unknown EMAIL_PROVIDER {provider!r}")
