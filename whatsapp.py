"""WhatsApp Cloud API integration and the YaVaKa conversation assistant."""

import json
import re
import urllib.error
import urllib.request

from flask import current_app

import whatsapp_i18n as i18n
from db import execute, new_id, now_iso, query
from money import format_money, parse_money_to_cents
from stages import project_progress, stage_by_key

DEFAULT_LANGUAGE = i18n.DEFAULT_LANGUAGE


def tr(key: str, language: str = DEFAULT_LANGUAGE, **values) -> str:
    """Every reply goes through here, so a language switch covers the whole chat."""
    return i18n.t(key, language, **values)


def normalise_language(value: str) -> str:
    return i18n.normalise_language(value)


def menu_for(role: str):
    return i18n.menu_for(role)


def menu_titles(items, language: str):
    return i18n.menu_titles(items, language)

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


QUICK_REPLIES = {
    "balance": ("STATUS", "PROJECTS", "PAY 500"),
    "status": ("BALANCE", "PROJECTS", "PAY 500"),
    "projects": ("BALANCE", "STATUS"),
    "deposit": ("BALANCE", "STATUS"),
    "receipt": ("BALANCE", "STATUS"),
    "help": ("BALANCE", "STATUS", "PROJECTS", "PAY 500"),
    "unknown": ("BALANCE", "STATUS", "PROJECTS", "PAY 500"),
}


def quick_replies(intent: str):
    """Follow-up commands offered under an assistant reply."""
    return QUICK_REPLIES.get(intent or "", ())


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


def send_whatsapp_buttons(to: str, body: str, buttons) -> dict:
    """Reply with up to three tappable buttons. `buttons` is [(id, title)]."""
    if not whatsapp_configured():
        return {"status": "queued", "simulated": True}

    payload = [
        {"type": "reply", "reply": {"id": str(button_id)[:256], "title": str(title)[:20]}}
        for button_id, title in list(buttons)[:3]
    ]
    return _send_whatsapp_payload(
        to,
        {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body[:1024]},
                "action": {"buttons": payload},
            },
        },
    )


def send_whatsapp_list(to: str, body: str, button_label: str, rows) -> dict:
    """Reply with a tappable list. `rows` is [(id, title)]; Meta allows ten."""
    if not whatsapp_configured():
        return {"status": "queued", "simulated": True}

    section_rows = [
        {"id": str(row_id)[:200], "title": str(title)[:24]}
        for row_id, title in list(rows)[:10]
    ]
    return _send_whatsapp_payload(
        to,
        {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body[:1024]},
                "action": {
                    "button": str(button_label)[:20],
                    "sections": [{"rows": section_rows}],
                },
            },
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

    # Menu ids arrive from tapped buttons and list rows, and are unambiguous.
    if text.startswith("m_"):
        return text[2:], None
    if text in i18n.CLIENT_MENU or text in i18n.MANAGER_MENU:
        return text, None
    if text in i18n.LANGUAGE_WORDS:
        return "language", i18n.LANGUAGE_WORDS[text]

    if re.match(r"^(hi|hello|hey|start|menu|help|0|mhoro|mauya|sawubona)\b", text):
        return "help", None
    if re.search(r"\b(balance|how much|funds|money left|account|mari|imali)\b", text):
        return "balance", None
    if re.search(r"\b(status|progress|stage|where|nhanho|isigaba)\b", text):
        return "status", None
    if re.search(r"\b(project|projects|house|build|chirongwa|zvirongwa|umsebenzi)\b", text):
        return "projects", None
    if re.search(r"\b(receipt|invoice|proof|upload|risiti|irisidi)\b", text):
        return "receipt", None
    if re.search(r"\b(clients|customers|vatengi|amaklayenti)\b", text):
        return "clients", None
    if re.search(r"\b(approvals|attention|blocked|zvinoda)\b", text):
        return "approvals", None
    if re.search(r"\b(escalate|complain|human|bata)\b", text):
        return "escalate", None
    if re.match(r"^update\b", text):
        return "update", None

    deposit = re.search(
        r"\b(?:pay|paid|paying|sent|send|deposit(?:ed)?|transfer(?:red)?)\b[^\d]{0,20}([\d,]+(?:\.\d{1,2})?)",
        text,
    )
    if deposit:
        return "deposit", parse_money_to_cents(deposit.group(1))

    if text.isdigit():
        menu = i18n.CLIENT_MENU
        index = int(text)
        if 1 <= index <= len(menu):
            return menu[index - 1], None
        return "unknown", None

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
        """INSERT INTO whatsapp_contacts (id, phone, name, user_id, project_id, language, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            contact_id,
            normalised,
            profile_name.strip() or (user["name"] if user else display_phone(normalised)),
            user["id"] if user else None,
            project["id"] if project else None,
            i18n.DEFAULT_LANGUAGE,
            now_iso(),
        ),
    )
    return query("SELECT * FROM whatsapp_contacts WHERE id = ?", (contact_id,), one=True)


def contact_role(contact) -> str:
    """manager, admin, client, or stranger when the number is unknown."""
    if not contact["user_id"]:
        return "client" if contact["project_id"] else "stranger"
    user = query("SELECT role FROM users WHERE id = ?", (contact["user_id"],), one=True)
    role = (user["role"] if user else "") or "client"
    return role


def managed_projects(user_id: str):
    """Projects this manager is assigned to, newest first."""
    return query(
        "SELECT * FROM projects WHERE manager_id = ? ORDER BY created_at DESC",
        (user_id,),
    )


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


def _reply(contact, body, intent, language, *, kind="text", rows=None, buttons=None):
    """Record and send one assistant reply, then hand the result back."""
    execute(
        """INSERT INTO whatsapp_messages (id, contact_id, direction, body, intent, status, created_at)
           VALUES (?, ?, 'OUT', ?, ?, 'sent', ?)""",
        (new_id(), contact["id"], body, intent, now_iso()),
    )

    if kind == "buttons":
        delivery = send_whatsapp_buttons(contact["phone"], body, buttons)
    elif kind == "list":
        delivery = send_whatsapp_list(
            contact["phone"], body, tr("menu_more", language), rows
        )
    else:
        delivery = send_whatsapp_text(contact["phone"], body)

    return {
        "reply": body,
        "intent": intent,
        "contact_id": contact["id"],
        "delivery": delivery["status"],
        "language": language,
        # Command words for the in-app simulator's chips; the WhatsApp buttons
        # themselves carry ids. Excludes the action just performed.
        "quick_replies": [
            key.upper() for key in menu_for(contact_role(contact)) if key != intent
        ][:4],
        "options": [title for _, title in (rows or buttons or [])],
    }


def _menu(contact, role, language, opening, intent="help"):
    """Send the role's menu as buttons when it fits, otherwise as a list."""
    titles = menu_titles(menu_for(role), language)
    numbered = "\n".join(
        f"{index}. {title}" for index, (_, title) in enumerate(titles, start=1)
    )
    body = f"{opening}\n\n{numbered}"
    if len(titles) <= 3:
        return _reply(contact, body, intent, language, kind="buttons", buttons=titles)
    return _reply(contact, body, intent, language, kind="list", rows=titles)


def handle_inbound(phone: str, body: str, profile_name: str = "") -> dict:
    contact = resolve_contact(phone, profile_name)
    intent, argument = detect_intent(body)
    language = normalise_language(contact["language"] or DEFAULT_LANGUAGE)
    role = contact_role(contact)
    project = load_project(contact)

    execute(
        """INSERT INTO whatsapp_messages (id, contact_id, direction, body, intent, status, created_at)
           VALUES (?, ?, 'IN', ?, ?, 'received', ?)""",
        (new_id(), contact["id"], str(body)[:2000], intent, now_iso()),
    )

    if contact["handoff_at"]:
        # A person is handling this conversation. The message is on record,
        # but the assistant must not talk over them - and whoever took the
        # conversation over needs to know a reply has landed.
        if project:
            import updates

            updates.notify(
                contact["handoff_by"] or project["manager_id"],
                project["id"],
                "whatsapp.reply",
                f"{contact['name']}: {str(body).strip()[:160]}",
                href=f"/app/whatsapp?contact={contact['id']}",
            )
        return {
            "reply": "",
            "intent": intent,
            "contact_id": contact["id"],
            "delivery": "handoff",
            "quick_replies": [],
            "handoff": True,
        }

    # ---- language switching, available at any point in the conversation ----
    if intent == "language":
        if argument:
            language = normalise_language(argument)
            execute(
                "UPDATE whatsapp_contacts SET language = ? WHERE id = ?",
                (language, contact["id"]),
            )
            return _menu(contact, role, language, tr("language_set", language))
        names = [(f"lang_{code}", label) for code, label in i18n.LANGUAGES.items()]
        return _reply(
            contact,
            tr("language_prompt", language),
            "language",
            language,
            kind="buttons",
            buttons=names,
        )

    # ---- number that belongs to nobody ----
    if role == "stranger":
        return _reply(contact, tr("greeting_unknown", language), intent, language)

    if intent in {"help", "unknown"}:
        opening = tr(
            "greeting_manager" if role == "manager" else "greeting_client",
            language,
            name=(contact["name"] or "").split(" ")[0] or contact["name"],
            project=project["name"] if project else "",
            projects=len(managed_projects(contact["user_id"])) if role == "manager" else 0,
            pending=len(_attention_items(contact)), 
        )
        if intent == "unknown":
            opening = f"{tr('unknown', language)}\n\n{opening}"
        return _menu(contact, role, language, opening, intent)

    # ---- client intents ----
    if intent == "balance" and project:
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
        body_text = "\n".join(
            [
                f"*{project['name']}*",
                "",
                tr("balance_received", language, amount=format_money(funded)),
                tr("balance_used", language, amount=format_money(spent)),
                f"*{tr('balance_available', language, amount=format_money(funded - spent))}*",
            ]
        )
        return _reply(contact, body_text, intent, language)

    if intent == "status" and project:
        stages = query(
            "SELECT * FROM stages WHERE project_id = ? ORDER BY position", (project["id"],)
        )
        completed = [stage for stage in stages if stage["status"] == "complete"]
        current = next(
            (stage for stage in stages if stage["status"] == "in_progress"), None
        ) or next((stage for stage in stages if stage["status"] != "complete"), None)
        lines = [
            f"*{project['name']}*",
            tr(
                "status_progress",
                language,
                percent=project_progress(stages),
                done=len(completed),
                total=len(stages),
            ),
            tr("status_now", language, stage=current["name"])
            if current
            else tr("status_done", language),
        ]
        if current and current["status"] == "blocked":
            lines.append(tr("status_blocked", language))
        return _reply(contact, "\n".join(lines), intent, language)

    if intent == "projects":
        projects = (
            query(
                "SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at DESC LIMIT 5",
                (contact["user_id"],),
            )
            if contact["user_id"]
            else [project]
        )
        body_text = "\n".join(
            [f"*{tr('projects_heading', language)}*", ""]
            + [
                f"- {item['name']} ({item['code']}) - {item['status'].replace('_', ' ')}"
                for item in projects
            ]
        )
        return _reply(contact, body_text, intent, language)

    if intent == "receipt":
        return _reply(contact, tr("receipt_help", language), intent, language)

    if intent == "contact":
        manager = (
            query("SELECT * FROM users WHERE id = ?", (project["manager_id"],), one=True)
            if project and project["manager_id"]
            else None
        )
        if manager:
            body_text = tr(
                "contact_details",
                language,
                name=manager["name"],
                phone=display_phone(manager["phone"] or ""),
            )
        else:
            body_text = tr("clients_empty", language)
        return _reply(contact, body_text, intent, language)

    if intent == "deposit":
        if not project:
            return _menu(contact, role, language, tr("greeting_unknown", language))
        if not argument:
            return _reply(contact, tr("deposit_bad", language), intent, language)
        execute(
            """INSERT INTO transactions
                 (id, project_id, type, amount_cents, currency, category, stage_key, description, method, reference, occurred_at, created_by, created_at)
               VALUES (?, ?, 'FUNDING', ?, 'USD', 'client_deposit', NULL, ?, 'OTHER', ?, ?, ?, ?)""",
            (
                new_id(),
                project["id"],
                argument,
                "Deposit notified via WhatsApp - pending verification",
                f"WA-{int(__import__('time').time())}",
                now_iso(),
                contact["user_id"] or project["owner_id"],
                now_iso(),
            ),
        )
        body_text = "\n\n".join(
            [
                tr("deposit_logged", language, amount=format_money(argument), project=project["name"]),
                tr("deposit_pending", language),
            ]
        )
        return _reply(contact, body_text, intent, language)

    # ---- build manager intents ----
    if intent == "portfolio":
        projects = managed_projects(contact["user_id"]) if contact["user_id"] else []
        if not projects:
            return _reply(contact, tr("portfolio_empty", language), intent, language)
        lines = [f"*{tr('menu_portfolio', language)}*", ""]
        for item in projects[:8]:
            stages = query(
                "SELECT * FROM stages WHERE project_id = ? ORDER BY position", (item["id"],)
            )
            lines.append(
                tr(
                    "portfolio_line",
                    language,
                    name=item["name"],
                    code=item["code"],
                    percent=project_progress(stages),
                    status=item["status"].replace("_", " "),
                )
            )
        return _reply(contact, "\n".join(lines), intent, language)

    if intent == "approvals":
        items = _attention_items(contact)
        if not items:
            return _reply(contact, tr("approvals_none", language), intent, language)
        lines = [f"*{tr('menu_approvals', language)}*", ""]
        lines.extend(
            tr("approvals_line", language, name=name, detail=detail)
            for name, detail in items[:8]
        )
        return _reply(contact, "\n".join(lines), intent, language)

    if intent == "clients":
        projects = managed_projects(contact["user_id"]) if contact["user_id"] else []
        seen = []
        for item in projects:
            owner = query("SELECT * FROM users WHERE id = ?", (item["owner_id"],), one=True)
            phone = item["client_whatsapp"] or (owner["phone"] if owner else "") or ""
            name = owner["name"] if owner else item["name"]
            key = (name, phone)
            if key not in seen:
                seen.append(key)
        if not seen:
            return _reply(contact, tr("clients_empty", language), intent, language)
        lines = [f"*{tr('menu_clients', language)}*", ""]
        lines.extend(
            tr("clients_line", language, name=name, phone=display_phone(phone) if phone else "-")
            for name, phone in seen[:10]
        )
        return _reply(contact, "\n".join(lines), intent, language)

    if intent == "update":
        text = str(body or "").strip()
        match = re.match(r"(?i)^update\s+([A-Za-z0-9-]+)\s*[:\-]?\s*(.+)$", text, re.S)
        if not match:
            return _reply(contact, tr("update_usage", language), intent, language)
        code, message = match.group(1), match.group(2).strip()
        target = next(
            (
                item
                for item in (managed_projects(contact["user_id"]) if contact["user_id"] else [])
                if item["code"].lower() == code.lower()
            ),
            None,
        )
        if not target:
            return _reply(contact, tr("update_unknown_project", language), intent, language)
        import updates

        updates.notify(
            target["owner_id"],
            target["id"],
            "whatsapp.update",
            f"{contact['name']}: {message[:160]}",
            href=f"/app/projects/{target['id']}",
        )
        return _reply(
            contact,
            tr("update_saved", language, project=target["name"]),
            intent,
            language,
        )

    if intent == "escalate":
        import updates

        for admin in query("SELECT id FROM users WHERE role = 'admin'"):
            updates.notify(
                admin["id"],
                project["id"] if project else None,
                "whatsapp.escalation",
                f"{contact['name']} asked for help on WhatsApp: {str(body).strip()[:160]}",
                href=f"/app/whatsapp?contact={contact['id']}",
            )
        return _reply(contact, tr("escalate_sent", language), intent, language)

    # ---- nothing matched ----
    return _menu(contact, role, language, tr("unknown", language))


def _attention_items(contact):
    """Blocked stages across the projects this manager is responsible for."""
    if not contact["user_id"]:
        return []
    projects = managed_projects(contact["user_id"])
    items = []
    for item in projects:
        blocked = query(
            "SELECT name FROM stages WHERE project_id = ? AND status = 'blocked' ORDER BY position",
            (item["id"],),
        )
        for stage in blocked:
            items.append((item["name"], stage["name"]))
    return items
