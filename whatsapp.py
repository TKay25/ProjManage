"""WhatsApp Cloud API integration and the YaVaKa conversation assistant."""

import json
import re
import urllib.error
import urllib.request

from flask import current_app

from db import execute, new_id, now_iso, query
from money import format_money, parse_money_to_cents
from stages import project_progress, stage_by_key

HELP = "\n".join(
    [
        "*YaVaKa assistant* — reply with a number or keyword:",
        "",
        "1. *BALANCE* — money received vs spent",
        "2. *STATUS* — current build stage",
        "3. *PROJECTS* — your projects",
        "4. *PAY 500* — log a deposit you have sent",
        "5. *RECEIPT* — how to upload a receipt",
        "",
        "A human from your build team reads these messages during working hours.",
    ]
)


def whatsapp_configured() -> bool:
    return bool(
        current_app.config.get("WHATSAPP_TOKEN")
        and current_app.config.get("WHATSAPP_PHONE_NUMBER_ID")
    )


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return ""
    if digits.startswith("263"):
        return digits
    if digits.startswith("0") and len(digits) >= 9:
        return f"263{digits[1:]}"
    return digits


def display_phone(phone: str) -> str:
    normalised = normalize_phone(phone)
    if normalised.startswith("263") and len(normalised) == 12:
        return f"+263 {normalised[3:6]} {normalised[6:9]} {normalised[9:]}"
    return f"+{normalised}"


def send_whatsapp_text(to: str, body: str) -> dict:
    """Send via Meta Cloud API, or queue locally when credentials are absent."""
    if not whatsapp_configured():
        return {"status": "queued", "simulated": True}

    return _send_whatsapp_payload(
        to,
        {
            "type": "text",
            "text": {"preview_url": False, "body": body},
        },
    )


def send_whatsapp_project_update(to: str, body: str) -> dict:
    """Send an approved template so updates can be delivered outside the 24h window."""
    template_name = current_app.config.get("WHATSAPP_UPDATE_TEMPLATE")
    if not whatsapp_configured():
        return {"status": "failed", "error": "WhatsApp Cloud API is not configured."}
    if not template_name:
        return {
            "status": "failed",
            "error": "An approved WhatsApp update template is not configured.",
        }

    return _send_whatsapp_payload(
        to,
        {
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": current_app.config.get("WHATSAPP_UPDATE_LANGUAGE", "en")},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": body[:1024]}],
                    }
                ],
            },
        },
    )


def _send_whatsapp_payload(to: str, content: dict) -> dict:
    url = (
        f"https://graph.facebook.com/v21.0/"
        f"{current_app.config['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    )
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": normalize_phone(to),
            **content,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {current_app.config['WHATSAPP_TOKEN']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
            return {"status": "sent", "id": (data.get("messages") or [{}])[0].get("id")}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        try:
            message = json.loads(detail).get("error", {}).get("message", detail)
        except json.JSONDecodeError:
            message = detail
        return {"status": "failed", "error": message}
    except Exception as error:  # noqa: BLE001 - surface any transport failure
        return {"status": "failed", "error": str(error)}


def detect_intent(body: str):
    text = str(body or "").strip().lower()

    if re.match(r"^(hi|hello|hey|start|menu|help|0)\b", text):
        return "help", None
    if re.search(r"\b(balance|how much|funds|money left|account)\b", text):
        return "balance", None
    if re.search(r"\b(status|progress|stage|where)\b", text):
        return "status", None
    if re.search(r"\b(project|projects|house|build)\b", text):
        return "projects", None
    if re.search(r"\b(receipt|invoice|proof|upload)\b", text):
        return "receipt", None

    deposit = re.search(
        r"\b(?:pay|paid|paying|sent|send|deposit(?:ed)?|transfer(?:red)?)\b[^\d]{0,20}([\d,]+(?:\.\d{1,2})?)",
        text,
    )
    if deposit:
        return "deposit", parse_money_to_cents(deposit.group(1))

    if text.isdigit():
        return {"1": "balance", "2": "status", "3": "projects", "4": "deposit", "5": "receipt"}.get(
            text, "unknown"
        ), None

    return "unknown", None


def resolve_contact(phone: str, profile_name: str = ""):
    normalised = normalize_phone(phone)
    existing = query("SELECT * FROM whatsapp_contacts WHERE phone = ?", (normalised,), one=True)
    if existing:
        return existing

    user = query("SELECT * FROM users WHERE phone = ?", (normalised,), one=True)
    project = None
    if user:
        project = query(
            "SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at LIMIT 1",
            (user["id"],),
            one=True,
        )
    if not project:
        # A build manager can record a client's WhatsApp on the project even
        # when that client has no YaVaKa login of their own.
        project = query(
            "SELECT * FROM projects WHERE client_whatsapp = ? ORDER BY created_at DESC LIMIT 1",
            (normalised,),
            one=True,
        )

    contact_id = new_id()
    execute(
        """INSERT INTO whatsapp_contacts (id, phone, name, user_id, project_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            contact_id,
            normalised,
            profile_name.strip() or (user["name"] if user else display_phone(normalised)),
            user["id"] if user else None,
            project["id"] if project else None,
            now_iso(),
        ),
    )
    return query("SELECT * FROM whatsapp_contacts WHERE id = ?", (contact_id,), one=True)


def load_project(contact):
    if contact["project_id"]:
        return query("SELECT * FROM projects WHERE id = ?", (contact["project_id"],), one=True)
    if contact["user_id"]:
        return query(
            "SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at LIMIT 1",
            (contact["user_id"],),
            one=True,
        )
    return None


def handle_inbound(phone: str, body: str, profile_name: str = "") -> dict:
    contact = resolve_contact(phone, profile_name)
    intent, amount_cents = detect_intent(body)
    project = load_project(contact)

    execute(
        """INSERT INTO whatsapp_messages (id, contact_id, direction, body, intent, status, created_at)
           VALUES (?, ?, 'IN', ?, ?, 'received', ?)""",
        (new_id(), contact["id"], str(body)[:2000], intent, now_iso()),
    )

    if not project:
        reply = (
            "Karibu! I can't find a project linked to this number yet.\n\n"
            "Ask your build manager to link your number in YaVaKa, or reply *HELP* to see what I can do."
        )
    elif intent in {"help", "unknown"}:
        reply = f"{HELP}\n\n_Project: {project['name']}_"
    elif intent == "balance":
        totals = query(
            """SELECT
                 COALESCE(SUM(CASE WHEN type = 'FUNDING' THEN amount_cents END), 0) AS funded,
                 COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount_cents END), 0) AS spent
               FROM transactions WHERE project_id = ?""",
            (project["id"],),
            one=True,
        )
        funded = int(totals["funded"] or 0)
        spent = int(totals["spent"] or 0)
        reply = "\n".join(
            [
                f"*{project['name']}*",
                "",
                f"Received: {format_money(funded)}",
                f"Used: {format_money(spent)}",
                f"*Available: {format_money(funded - spent)}*",
                "",
                "Reply *STATUS* for the current stage.",
            ]
        )
    elif intent == "status":
        stages = query("SELECT * FROM stages WHERE project_id = ? ORDER BY position", (project["id"],))
        completed = [stage for stage in stages if stage["status"] == "complete"]
        current = next((stage for stage in stages if stage["status"] == "in_progress"), None) or next(
            (stage for stage in stages if stage["status"] != "complete"), None
        )
        definition = stage_by_key(current["key"]) if current else None
        lines = [
            f"*{project['name']}*",
            f"Progress: {project_progress(stages)}% ({len(completed)}/{len(stages)} stages)",
            (
                f"Now: *{current['name']}*" + (f" — {definition['authority']}" if definition and definition.get("authority") else "")
                if current
                else "All stages complete 🎉"
            ),
        ]
        if current and current["status"] == "blocked":
            lines.append("⚠️ This stage is on hold — your manager will call you.")
        lines += ["", "Reply *BALANCE* for the money position."]
        reply = "\n".join(lines)
    elif intent == "projects":
        projects = (
            query(
                "SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at DESC LIMIT 5",
                (contact["user_id"],),
            )
            if contact["user_id"]
            else [project]
        )
        reply = "\n".join(
            ["*Your projects*", ""]
            + [f"• {item['name']} ({item['code']}) — {item['status'].replace('_', ' ')}" for item in projects]
        )
    elif intent == "receipt":
        reply = "\n".join(
            [
                "📎 *Sending a receipt*",
                "",
                "1. Open YaVaKa → Documents → Upload receipt",
                "2. Or send the photo here and your manager will attach it to the expense.",
                "",
                "Always include the amount, supplier and project name.",
            ]
        )
    elif intent == "deposit":
        if not amount_cents:
            reply = "I couldn't read that amount. Try: *PAY 500* or *PAY 1,250.50*.\n\nNothing is recorded until you confirm."
        else:
            execute(
                """INSERT INTO transactions
                     (id, project_id, type, amount_cents, currency, category, stage_key, description, method, reference, occurred_at, created_by, created_at)
                   VALUES (?, ?, 'FUNDING', ?, 'USD', 'client_deposit', NULL, ?, 'OTHER', ?, ?, ?, ?)""",
                (
                    new_id(),
                    project["id"],
                    amount_cents,
                    "Deposit notified via WhatsApp — pending verification",
                    f"WA-{int(__import__('time').time())}",
                    now_iso(),
                    contact["user_id"] or project["owner_id"],
                    now_iso(),
                ),
            )
            reply = "\n".join(
                [
                    f"Logged a *{format_money(amount_cents)}* deposit notification for *{project['name']}*.",
                    "",
                    "Status: *pending verification* — your manager will match it to the bank or EcoCash entry and attach the proof.",
                    "",
                    "Reply *BALANCE* to see the updated position.",
                ]
            )
    else:
        reply = HELP

    execute(
        """INSERT INTO whatsapp_messages (id, contact_id, direction, body, intent, status, created_at)
           VALUES (?, ?, 'OUT', ?, ?, 'sent', ?)""",
        (new_id(), contact["id"], reply, intent, now_iso()),
    )

    delivery = send_whatsapp_text(contact["phone"], reply)
    return {"reply": reply, "intent": intent, "contact_id": contact["id"], "delivery": delivery["status"]}
