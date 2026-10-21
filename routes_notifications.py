"""Token-protected endpoint for recovering pending notification outbox work."""

import hmac
import os

from flask import Blueprint, current_app, jsonify, request

from db import query
from notifications import schedule_dispatch

bp = Blueprint("notifications", __name__)


@bp.post("/api/notifications/dispatch")
def dispatch():
    expected = current_app.config.get("NOTIFICATIONS_TOKEN") or os.environ.get(
        "NOTIFICATIONS_TOKEN", ""
    )
    supplied = request.headers.get("X-Notifications-Token") or ""
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify({"ok": False, "message": "Not authorised."}), 403

    pending = query(
        "SELECT COUNT(*) AS count FROM notification_outbox WHERE status = 'pending'",
        one=True,
    )["count"]
    schedule_dispatch(current_app._get_current_object())
    return jsonify({"ok": True, "scheduled": pending})
