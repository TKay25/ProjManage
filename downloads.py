"""Signed download links, so a file can be fetched from a WhatsApp message.

The web app serves attachments behind a login. A client talking to the bot may
not have an account at all, so notifications carry a token instead: an
attachment id, an expiry and an HMAC over both. Nothing is stored server side,
tokens cannot be guessed, and they stop working on their own.
"""

import hashlib
import hmac
import time

from flask import current_app, has_request_context, request, url_for

DEFAULT_TTL_DAYS = 7


def _signature(attachment_id: str, expires: int) -> str:
    secret = str(current_app.config["SECRET_KEY"]).encode("utf-8")
    message = f"{attachment_id}.{expires}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()[:32]


def token_for(attachment_id: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    expires = int(time.time()) + max(1, ttl_days) * 86400
    return f"{attachment_id}.{expires}.{_signature(attachment_id, expires)}"


def verify(token: str):
    """Return the attachment id for a valid, unexpired token, else None."""
    parts = (token or "").split(".")
    if len(parts) != 3:
        return None
    attachment_id, expires_raw, digest = parts
    try:
        expires = int(expires_raw)
    except ValueError:
        return None
    if expires < int(time.time()):
        return None
    if not hmac.compare_digest(digest, _signature(attachment_id, expires)):
        return None
    return attachment_id


def absolute_url(attachment_id: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    """Full https link for a message body. Empty when no base URL is known."""
    token = token_for(attachment_id, ttl_days)
    path = f"/d/{token}"
    if has_request_context():
        return url_for("documents.download", token=token, _external=True)
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    return f"{base}{path}" if base else ""


def relative_url(attachment_id: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    return url_for("documents.download", token=token_for(attachment_id, ttl_days))
