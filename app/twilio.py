"""Twilio helpers: phone normalization, request signature validation, and sending.

No SDK; the two HTTP calls are small and this keeps the dependency list short.
"""
import base64
import hashlib
import hmac
import re

import httpx

from app.config import Settings

STOP_WORDS = {"stop", "unsubscribe", "cancel", "end", "quit", "stopall"}


def normalize_phone(raw: str) -> str:
    """Return E.164 for US numbers and anything already international; '' if unusable."""
    s = (raw or "").strip()
    s = s.removeprefix("whatsapp:")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if s.startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits


def compute_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's scheme: URL, then each POST key+value in sorted key order, HMAC-SHA1, base64."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def signature_valid(auth_token: str, url: str, params: dict[str, str], header: str | None) -> bool:
    if not header or not auth_token:
        return False
    return hmac.compare_digest(compute_signature(auth_token, url, params), header)


def send_whatsapp(settings: Settings, to_e164: str, body: str, status_callback: str | None,
                  transport: httpx.BaseTransport | None = None) -> dict:
    """POST to Twilio's Messages resource. Returns the parsed JSON (sid, status, ...)."""
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_whatsapp_from):
        raise RuntimeError("Twilio is not configured: set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    data = {"From": f"whatsapp:{settings.twilio_whatsapp_from}", "To": f"whatsapp:{to_e164}", "Body": body}
    if status_callback:
        data["StatusCallback"] = status_callback
    with httpx.Client(transport=transport, timeout=15.0) as client:
        r = client.post(url, data=data, auth=(settings.twilio_account_sid, settings.twilio_auth_token))
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", r.text)
        except ValueError:
            msg = r.text
        raise RuntimeError(f"Twilio refused the message: {msg}")
    return r.json()
