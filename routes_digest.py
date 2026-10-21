"""Weekly progress and balance digest over WhatsApp.

Triggered by an external scheduler hitting POST /api/whatsapp/digest with the
shared token, so no long-running worker is needed. Each client gets one short
message per active project.
"""

import hmac
import os
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, render_template, request

from db import log_event, query
from money import format_money
from queries import money_totals, next_stage, stage_rows
from stages import project_progress, stage_name
from whatsapp import normalize_phone, send_whatsapp_text

bp = Blueprint("digest", __name__)


def _authorised() -> bool:
    """Fails closed: no configured token means the endpoint does nothing."""
    expected = current_app.config.get("DIGEST_TOKEN") or os.environ.get("DIGEST_TOKEN", "")
    if not expected:
        return False
    supplied = request.headers.get("X-Digest-Token") or request.args.get("token") or ""
    return hmac.compare_digest(supplied, expected)


def build_digest(project) -> str:
    """One message: progress, money, and the next thing to happen."""
    stages = stage_rows(project["id"])
    totals = money_totals(project["id"])
    progress = project_progress(stages)
    upcoming = next_stage(stages)
    completed = len([stage for stage in stages if stage["status"] == "complete"])

    lines = [
        f"*{project['name']}* · weekly update",
        "",
        f"Progress: {progress}% ({completed} of {len(stages)} stages done)",
        f"Sent: {format_money(totals['funded'])}",
        f"Used: {format_money(totals['spent'])}",
        f"Balance: {format_money(totals['balance'])}",
    ]

    if upcoming:
        lines += ["", f"Next: {stage_name(upcoming['key'])}"]
    else:
        lines += ["", "All stages are complete."]

    lines += ["", "Reply BALANCE or STATUS any time for an on-demand update."]
    return "\n".join(lines)


@bp.post("/api/whatsapp/digest")
def digest():
    if not _authorised():
        return jsonify({"ok": False, "message": "Not authorised."}), 403

    # Only projects that are actually live, and only where we have a number.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    projects = query(
        """SELECT p.*, u.name AS owner_name, u.phone AS owner_phone
           FROM projects p JOIN users u ON u.id = p.owner_id
           WHERE p.archived_at IS NULL
             AND p.status IN ('planning', 'in_progress')
             AND u.phone IS NOT NULL AND u.phone != ''
           ORDER BY p.created_at"""
    )

    sent, skipped, failed = [], [], []
    for project in projects:
        phone = normalize_phone(project["owner_phone"] or "")
        if not phone:
            skipped.append({"project": project["name"], "reason": "no phone"})
            continue

        body = build_digest(project)
        result = send_whatsapp_text(phone, body)

        if result.get("status") in {"sent", "queued"}:
            sent.append(project["name"])
            log_event(None, project["id"], "digest.sent", f"Weekly digest to {phone}")
        else:
            failed.append({"project": project["name"], "error": result.get("error")})

    return jsonify(
        {
            "ok": True,
            "considered": len(projects),
            "sent": len(sent),
            "skipped": skipped,
            "failed": failed,
            "simulated": not current_app.config.get("WHATSAPP_TOKEN"),
        }
    )
