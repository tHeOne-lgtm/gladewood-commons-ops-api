"""Signed links for the Mac mini file service (decision 2026-11-20: files on the Mac mini, Google
Drive copy, API keeps metadata). The n8n file service verifies the same HMAC with FILES_SERVICE_SECRET.

Token = urlsafe_base64(json payload) + "." + hex HMAC-SHA256(secret, that base64 string).
Payload for an upload: {"doc": id, "op": "upload", "exp": unix seconds, "by": user id}.
Payload for a download: {"doc": id, "op": "download", "exp": unix seconds, "by": user id, "key": storage_key}.
"""
import base64
import hashlib
import hmac
import json
import time

from app.config import Settings


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def sign(settings: Settings, payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(settings.files_service_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def verify(settings: Settings, token: str) -> dict | None:
    try:
        body, mac = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(settings.files_service_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    pad = "=" * (-len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode(body + pad))
    return payload if payload.get("exp", 0) >= time.time() else None


def upload_link(settings: Settings, doc_id: int, user_id: str, ttl: int = 900) -> dict:
    token = sign(settings, {"doc": doc_id, "op": "upload", "exp": int(time.time()) + ttl, "by": user_id})
    return {"url": settings.files_service_url.rstrip("/") + "/upload", "token": token, "expires_in": ttl}


def download_link(settings: Settings, doc_id: int, storage_key: str, user_id: str, ttl: int = 300) -> dict:
    token = sign(settings, {"doc": doc_id, "op": "download", "exp": int(time.time()) + ttl, "by": user_id, "key": storage_key})
    return {"url": settings.files_service_url.rstrip("/") + "/download?token=" + token, "expires_in": ttl}
