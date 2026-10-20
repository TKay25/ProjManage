"""WhatsApp inbox, simulator and Meta Cloud API webhook."""

import hashlib
import hmac

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    render_template,
    request,
)

from auth import accessible_projects, login_required
from db import execute, new_id, now_iso, query
from whatsapp import (
    display_phone,
    handle_inbound,
    normalize_phone,
    send_whatsapp_text,
    whatsapp_configured,
)

bp = Blueprint("whatsapp", __name__)


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
                   (SELECT COUNT(*) FROM whatsapp_messages m WHERE m.contact_id = c.id) AS message_count
                FROM whatsapp_contacts c
                LEFT JOIN projects p ON p.id = c.project_id
                LEFT JOIN users u ON u.id = c.user_id
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
        messages = query(
            "SELECT * FROM whatsapp_messages WHERE contact_id = ? ORDER BY created_at ASC LIMIT 200",
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
        configured=whatsapp_configured(),
        webhook_url=request.url_root.rstrip("/") + "/api/whatsapp/webhook",
        verify_token=current_app.config["WHATSAPP_VERIFY_TOKEN"],
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


@bp.post("/app/whatsapp/send")
@login_required
def send():
    contact = query(
        "SELECT * FROM whatsapp_contacts WHERE id = ?",
        (request.form.get("contact_id") or "",),
        one=True,
    )
    body = (request.form.get("body") or "").strip()

    if not contact:
        return jsonify({"error": "Contact not found."}), 404
    if not body:
        return jsonify({"error": "Type a message first."}), 400

    projects = accessible_projects(g.user)
    if contact["project_id"] not in [project["id"] for project in projects]:
        return jsonify({"error": "You do not have access to that conversation."}), 403

    execute(
        """INSERT INTO whatsapp_messages (id, contact_id, direction, body, intent, status, created_at)
           VALUES (?, ?, 'OUT', ?, 'manual', 'sent', ?)""",
        (new_id(), contact["id"], body[:2000], now_iso()),
    )
    delivery = send_whatsapp_text(contact["phone"], body)

    return jsonify({"status": delivery["status"], "simulated": delivery.get("simulated", False)})


@bp.get("/api/whatsapp/webhook")
def webhook_verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge", "")

    if mode == "subscribe" and token == current_app.config["WHATSAPP_VERIFY_TOKEN"]:
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
                if message.get("type") != "text":
                    continue
                body = message.get("text", {}).get("body", "")
                if not body:
                    continue
                handle_inbound(phone=message.get("from", ""), body=body, profile_name=profile_name)
                handled += 1

    return jsonify({"handled": handled})
