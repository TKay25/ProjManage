"""WhatsApp inbox, simulator and Meta Cloud API webhook."""

import hashlib
import hmac

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

import web
from auth import accessible_projects, login_required
from db import execute, new_id, now_iso, query
from whatsapp import (
    display_phone,
    handle_inbound,
    normalize_phone,
    quick_replies,
    send_whatsapp_text,
)

bp = Blueprint("whatsapp", __name__)


def contact_for_user(contact_id):
    """Loads a conversation the current user is allowed to read or answer."""
    contact = query(
        "SELECT * FROM whatsapp_contacts WHERE id = ?", (contact_id or "",), one=True
    )
    if not contact:
        abort(404)

    project_ids = [project["id"] for project in accessible_projects(g.user)]
    if contact["project_id"] not in project_ids and contact["user_id"] != g.user["id"]:
        abort(403)
    return contact


@bp.get("/app/whatsapp")
@login_required
def index():
    projects = accessible_projects(g.user)
    project_ids = [project["id"] for project in projects]

    contacts = []
    if project_ids:
        placeholders = ",".join("?" for _ in project_ids)
        contacts = query(
            f"""SELECT c.*, p.name AS project_name, u.name AS user_name,
                   h.name AS handoff_name,
                   (SELECT COUNT(*) FROM whatsapp_messages m WHERE m.contact_id = c.id) AS message_count
                FROM whatsapp_contacts c
                LEFT JOIN projects p ON p.id = c.project_id
                LEFT JOIN users u ON u.id = c.user_id
                LEFT JOIN users h ON h.id = c.handoff_by
                WHERE c.project_id IN ({placeholders}) OR c.user_id = ?
                ORDER BY c.created_at DESC""",
            [*project_ids, g.user["id"]],
        )

    selected = None
    requested = request.args.get("contact")
    if requested:
        selected = next((item for item in contacts if item["id"] == requested), None)
    selected = selected or (contacts[0] if contacts else None)

    messages = []
    if selected:
        # The newest 200, then flipped back into reading order.
        messages = query(
            """SELECT * FROM (
                   SELECT * FROM whatsapp_messages
                   WHERE contact_id = ?
                   ORDER BY created_at DESC, id DESC
                   LIMIT 200
               ) recent
               ORDER BY created_at ASC, id ASC""",
            (selected["id"],),
        )

    return render_template(
        "app/whatsapp.html",
        title="WhatsApp",
        active="whatsapp",
        projects=projects,
        contacts=contacts,
        selected=selected,
        messages=messages,
        quick_replies=quick_replies,
        display_phone=display_phone,
    )


@bp.post("/app/whatsapp/simulate")
@login_required
def simulate():
    payload = request.get_json(silent=True) or request.form
    projects = accessible_projects(g.user)
    project_id = payload.get("project_id") or ""
    project = next((item for item in projects if item["id"] == project_id), None)
    phone = payload.get("phone") or (g.user["phone"] or "263771234567")
    body = (payload.get("body") or "").strip()

    if not body:
        return jsonify({"error": "Type a message first."}), 400

    contact = query(
        "SELECT * FROM whatsapp_contacts WHERE phone = ?", (normalize_phone(phone),), one=True
    )
    if not contact:
        contact_id = new_id()
        execute(
            """INSERT INTO whatsapp_contacts (id, phone, name, user_id, project_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                contact_id,
                normalize_phone(phone),
                g.user["name"],
                g.user["id"],
                project["id"] if project else (projects[0]["id"] if projects else None),
                now_iso(),
            ),
        )

    result = handle_inbound(phone=phone, body=body, profile_name=g.user["name"])
    return jsonify(result)


@bp.post("/app/whatsapp/handoff")
@login_required
def handoff():
    contact = contact_for_user(request.form.get("contact_id"))
    execute(
        "UPDATE whatsapp_contacts SET handoff_at = ?, handoff_by = ? WHERE id = ?",
        (now_iso(), g.user["id"], contact["id"]),
    )
    flash(
        f"You're replying to {contact['name']}. The assistant will stay quiet until you hand it back.",
        "success",
    )
    return redirect(url_for("whatsapp.index", contact=contact["id"]))


@bp.post("/app/whatsapp/resume")
@login_required
def resume():
    contact = contact_for_user(request.form.get("contact_id"))
    execute(
        "UPDATE whatsapp_contacts SET handoff_at = NULL, handoff_by = NULL WHERE id = ?",
        (contact["id"],),
    )
    flash(f"The assistant is answering {contact['name']} again.", "success")
    return redirect(url_for("whatsapp.index", contact=contact["id"]))


@bp.post("/app/whatsapp/send")
@login_required
def send():
    payload = request.get_json(silent=True) or request.form
    contact = contact_for_user(payload.get("contact_id"))
    body = (payload.get("body") or "").strip()

    if not body:
        return jsonify({"error": "Type a message first."}), 400

    execute(
        """INSERT INTO whatsapp_messages (id, contact_id, direction, body, intent, status, created_at)
           VALUES (?, ?, 'OUT', ?, 'manual', 'sent', ?)""",
        (new_id(), contact["id"], body[:2000], now_iso()),
    )
    delivery = send_whatsapp_text(contact["phone"], body)

    if not web.wants_json():
        flash(f"Message sent to {contact['name']}.", "success")
        return redirect(url_for("whatsapp.index", contact=contact["id"]))

    return jsonify({"status": delivery["status"], "simulated": delivery.get("simulated", False)})


@bp.get("/api/whatsapp/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.token") or request.args.get("hub.verify_token") or ""
    challenge = request.args.get("hub.challenge", "")
    expected = current_app.config.get("WHATSAPP_VERIFY_TOKEN") or ""

    if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
        return challenge, 200, {"Content-Type": "text/plain"}

    return "Forbidden", 403


@bp.post("/api/whatsapp/webhook")
def webhook():
    app_secret = current_app.config.get("WHATSAPP_APP_SECRET")

    if app_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            app_secret.encode("utf-8"), request.get_data(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return "Invalid signature", 403

    payload = request.get_json(silent=True) or {}
    handled = 0

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = value.get("contacts", [])
            profile_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

            for message in value.get("messages", []):
                kind = message.get("type")
                body = ""
                if kind == "text":
                    body = message.get("text", {}).get("body", "")
                elif kind == "interactive":
                    # A tapped reply button or list row carries an id, which the
                    # assistant treats exactly like a typed command.
                    interactive = message.get("interactive", {}) or {}
                    body = (
                        (interactive.get("button_reply") or {}).get("id", "")
                        or (interactive.get("list_reply") or {}).get("id", "")
                    )
                if not body:
                    continue
                handle_inbound(phone=message.get("from", ""), body=body, profile_name=profile_name)
                handled += 1

    return jsonify({"handled": handled})
