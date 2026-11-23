"""The in-app conversation: reads, guided flows and the state between them.

One thread per person per door, stored in the database rather than the session,
so a reload — or a different device — continues exactly where the flow stopped.
An unfinished flow lives in ``chat_threads.draft``: the flow key, the step it is
on, the values gathered so far and any instruction still queued behind it.

The sentence itself is read by chat_nlu, which pulls out the intent, the figure,
the date and the name of the build or house. Whatever it finds is dropped into
the flow's slots before the flow starts, so "spent 340 on cement" goes straight
to a confirmation card instead of three questions.

Every write is delegated to services.py, the same functions the pages call, so
a chat command and the matching form can never disagree — and every write can be
taken back with "undo".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from flask import g

from auth import accessible_projects
from db import execute, log_event, new_id, now_iso, query
from money import format_money, parse_money_to_cents
from stages import PAYMENT_METHODS, stage_name
import assistant
import chat_nlu
import portals
import queries
import rentals
import services

# Chat verbs travel as ordinary message text so the transcript is readable and
# a no-JavaScript fallback needs nothing special. A double colon can never be
# confused with a question someone would type.
VERB_PREFIX = "::"
MAX_BODY = 2000
# A write can be taken back for this long before it becomes a ledger matter.
UNDO_MINUTES = 24 * 60


# ----------------------------------------------------------------------
# Threads and events
# ----------------------------------------------------------------------


def thread_for(user, portal: str = portals.PROJECT, *, create: bool = True):
    portal = portal if portal in portals.ALL else portals.PROJECT
    row = query(
        "SELECT * FROM chat_threads WHERE user_id = ? AND portal = ?",
        (user["id"], portal),
        one=True,
    )
    if row or not create:
        return row

    thread_id = new_id()
    stamp = now_iso()
    execute(
        """INSERT INTO chat_threads (id, user_id, portal, project_id, draft, created_at, updated_at)
           VALUES (?, ?, ?, NULL, NULL, ?, ?)""",
        (thread_id, user["id"], portal, stamp, stamp),
    )
    return query("SELECT * FROM chat_threads WHERE id = ?", (thread_id,), one=True)


def _touch(thread_id: str, draft=None, project_id=None):
    if draft is None and project_id is None:
        execute(
            "UPDATE chat_threads SET updated_at = ? WHERE id = ?", (now_iso(), thread_id)
        )
        return
    if project_id is not None:
        execute(
            "UPDATE chat_threads SET project_id = ?, updated_at = ? WHERE id = ?",
            (project_id, now_iso(), thread_id),
        )
        return
    execute(
        "UPDATE chat_threads SET draft = ?, updated_at = ? WHERE id = ?",
        (json.dumps(draft) if draft else None, now_iso(), thread_id),
    )


def post(
    thread_id: str,
    role: str,
    body: str,
    *,
    actions=None,
    links=None,
    card=None,
    kind=None,
    undo=None,
    undo_of=None,
) -> dict:
    payload = {}
    if actions:
        payload["actions"] = actions
    if links:
        payload["links"] = links
    if card:
        payload["card"] = card
    if undo:
        payload["undo"] = undo
    if undo_of:
        payload["undo_of"] = undo_of
    event_id = new_id()
    execute(
        """INSERT INTO chat_events (id, thread_id, role, kind, body, payload, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            thread_id,
            role,
            kind or ("actions" if actions else "text"),
            (body or "")[:MAX_BODY],
            json.dumps(payload) if payload else None,
            now_iso(),
        ),
    )
    _touch(thread_id)
    return {"id": event_id, "role": role, "body": body or "", **payload}


def history(thread_id: str, limit: int = 80) -> list[dict]:
    rows = query(
        "SELECT * FROM chat_events WHERE thread_id = ? ORDER BY created_at, id LIMIT ?",
        (thread_id, limit),
        one=False,
    )
    events = []
    for row in rows or []:
        payload = {}
        if row["payload"]:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                payload = {}
        events.append(
            {
                "id": row["id"],
                "role": row["role"],
                "kind": row["kind"],
                "body": row["body"],
                "created_at": row["created_at"],
                **payload,
            }
        )
    return events


def clear(thread_id: str):
    execute("DELETE FROM chat_events WHERE thread_id = ?", (thread_id,))
    _touch(thread_id, draft={})


# ----------------------------------------------------------------------
# Context
# ----------------------------------------------------------------------


def projects_for(user):
    return queries.projects_with_summary(accessible_projects(user))


def current_project(user, thread):
    projects = projects_for(user)
    chosen = thread["project_id"] if thread else None
    return next((item for item in projects if item["id"] == chosen), None) or (
        projects[0] if projects else None
    )


def _fresh_project(user, project_id):
    """The project as it is now, not as it was when the flow began.

    A card rendered after a write must show the new balance, and the request's
    project list was read before the row existed — so this reads the row again
    rather than trusting the memoised copy.
    """
    row = query("SELECT * FROM projects WHERE id = ?", (project_id,), one=True)
    if not row:
        return None
    summary = queries.projects_with_summary([row])
    return summary[0] if summary else None


def _project_card(project) -> dict:
    totals = project["totals"]
    current = queries.next_stage(project["stages"])
    return {
        "title": project["name"],
        "subtitle": f"{project['code']} · {project.get('suburb') or ''}".strip(" ·"),
        "stats": [
            ("Available", format_money(totals["balance"])),
            ("Received", format_money(totals["funded"])),
            ("Spent", format_money(totals["spent"])),
            ("Progress", f"{project['progress']}%"),
        ],
        "note": (
            f"Now: {current['name']}"
            if current and current["status"] in {"in_progress", "blocked"}
            else ("Nothing is in progress." if current else "Every stage is complete.")
        ),
    }


def _portfolio_card(owner_id) -> dict:
    totals = rentals.dashboard_totals(owner_id)
    return {
        "title": "Your portfolio",
        "subtitle": totals["month_label"],
        "stats": [
            ("Occupancy", f"{totals['occupied']}/{totals['properties']}"),
            ("Rent roll", format_money(totals["rent_roll"])),
            ("Collected", format_money(totals["collected"])),
            ("Outstanding", format_money(totals["outstanding"])),
        ],
        "note": (
            f"{plural(totals['work_orders'], 'open work order')}, "
            f"{plural(totals['checks_due'], 'check')} due."
            if totals["properties"]
            else "Add a property to start the record."
        ),
    }


def _project_actions(project):
    actions = [
        {"label": "Record money", "value": f"{VERB_PREFIX}flow:money"},
        {"label": "Post an update", "value": f"{VERB_PREFIX}flow:update"},
        {"label": "Stage status", "value": f"{VERB_PREFIX}flow:stage"},
    ]
    if project:
        actions.append({"label": "Attention", "value": "What needs attention?"})
    actions.append({"label": "All commands", "value": f"{VERB_PREFIX}help"})
    return actions


def _property_actions():
    return [
        {"label": "Receipt rent", "value": f"{VERB_PREFIX}flow:rent"},
        {"label": "Record a cost", "value": f"{VERB_PREFIX}flow:cost"},
        {"label": "Open a work order", "value": f"{VERB_PREFIX}flow:work_order"},
        {"label": "Add a tenant", "value": f"{VERB_PREFIX}flow:tenant"},
        {"label": "All commands", "value": f"{VERB_PREFIX}help"},
    ]


def _build_context(user, portal: str) -> chat_nlu.Context:
    if portal == portals.PROPERTY:
        return chat_nlu.Context(properties=rentals.portfolio(user["id"]))
    return chat_nlu.Context(projects=projects_for(user))


def _stages_for(user, thread):
    if thread["portal"] != portals.PROJECT:
        return []
    project = current_project(user, thread)
    return project["stages"] if project else []


def plural(count: int, noun: str, plural_form: str | None = None) -> str:
    return f"{count} {noun if count == 1 else (plural_form or noun + 's')}"


def _and_list(items) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def greeting(user, portal: str) -> dict:
    """The first thing a conversation shows: the numbers, then the actions."""
    first_name = (user["name"] or "").split(" ")[0]
    if portal == portals.PROPERTY:
        totals = rentals.dashboard_totals(user["id"])
        card = _portfolio_card(user["id"])
        if not totals["properties"]:
            body = (
                f"Hello {first_name}. Add your first property and I will keep the "
                "tenants, the rent and the receipts in one place."
            )
        else:
            pending = totals["outstanding"]
            body = (
                f"Hello {first_name}. "
                f"{plural(totals['properties'], 'property', 'properties')} on the record, "
                f"{format_money(totals['collected'])} collected in {totals['month_label']}"
                + (
                    f", {format_money(pending)} still outstanding."
                    if pending
                    else ", nothing outstanding."
                )
            )
        return {"body": body, "card": card, "actions": _property_actions()}

    projects = projects_for(user)
    project = current_project(user, thread_for(user, portal, create=False))
    if not project:
        return {
            "body": (
                f"Hello {first_name}. You have no build yet. Start one and I will track the "
                "stages, the money and the proof with you."
            ),
            "actions": [
                {"label": "Start a build", "href": "/app/projects/new"},
                {"label": "All commands", "value": f"{VERB_PREFIX}help"},
            ],
        }

    counts = queries.attention_counts([item["id"] for item in projects])
    card = _project_card(project)
    if counts["total"]:
        waiting = []
        if counts["blocked"]:
            waiting.append(plural(counts["blocked"], "blocked stage"))
        if counts["approvals"]:
            waiting.append(plural(counts["approvals"], "approval") + " waiting")
        if counts["receipts"]:
            waiting.append(
                plural(counts["receipts"], "entry", "entries") + " without a receipt"
            )
        if counts["agreements"]:
            waiting.append(plural(counts["agreements"], "agreement") + " to sign")
        body = (
            f"Hello {first_name}. {project['name']}: "
            f"{format_money(project['totals']['balance'])} available. "
            f"{plural(counts['total'], 'thing')} need you — {_and_list(waiting)}."
        )
    else:
        body = (
            f"Hello {first_name}. {project['name']}: "
            f"{format_money(project['totals']['balance'])} available, "
            f"{project['progress']}% through the plan. Ask me anything, or tell me what happened."
        )
    return {"body": body, "card": card, "actions": _project_actions(project)}


def ensure_greeting(user, thread) -> None:
    if history(thread["id"], limit=1):
        return
    opening = greeting(user, thread["portal"])
    post(
        thread["id"],
        "assistant",
        opening["body"],
        card=opening.get("card"),
        actions=opening.get("actions"),
    )


# ----------------------------------------------------------------------
# Guided flows
# ----------------------------------------------------------------------


@dataclass
class Step:
    key: str
    prompt: str
    kind: str = "text"
    choices: object = None  # callable(user, thread, slots) -> [(value, label)]
    parse: object = None  # callable(text, choices) -> value, raises ValueError
    hint: str = ""
    when: object = None  # callable(slots) -> bool


@dataclass
class Flow:
    key: str
    label: str
    portal: str
    steps: list = field(default_factory=list)
    commit: object = None
    summary: object = None  # callable(user, thread, slots) -> [(label, value)]


def _amount(text, _choices=None):
    cents = parse_money_to_cents(text)
    if cents is None or cents <= 0:
        cents = chat_nlu.parse_amount(text) or 0
    if cents <= 0:
        raise ValueError("Give me an amount, like 500 or 1,250.50.")
    return cents


def _plain(minimum=3, message="Give me a few more words."):
    def parse(text, _choices=None):
        text = (text or "").strip()
        if len(text) < minimum:
            raise ValueError(message)
        return text

    return parse


def _choice_parse(text, choices):
    text = (text or "").strip()
    lowered = text.lower()
    for value, label in choices or []:
        if lowered == str(value).lower() or lowered == str(label).lower():
            return value
    if text.isdigit() and choices:
        index = int(text) - 1
        if 0 <= index < len(choices):
            return choices[index][0]
    best, runner = chat_nlu.resolve_option(text, [
        {"value": value, "label": label} for value, label in (choices or [])
    ], keys=("label", "value"))
    if best and not runner:
        return best["value"]
    raise ValueError("Pick one of the options.")


def _project_choices(user, thread, _slots):
    return [(item["id"], item["name"]) for item in projects_for(user)]


def _project_choice_step():
    return Step(
        "project",
        "Which build?",
        kind="choice",
        choices=_project_choices,
        parse=_choice_parse,
        # Asked only when the account runs several builds and none is selected.
        # One build is already answered, and so is a conversation with a build.
        when=lambda slots: slots.get("_needs_project") and not slots.get("project"),
    )


def _property_choices(user, _thread, _slots):
    return [(row["id"], row["name"]) for row in rentals.portfolio(user["id"])]


def _property_choice_step(step_key="property"):
    return Step(
        step_key,
        "Which property?",
        kind="choice",
        choices=_property_choices,
        parse=_choice_parse,
        # A one-property portfolio is already answered; asking would be noise.
        when=lambda slots: not slots.get("property"),
    )


def _load_project(user, thread, slots=None):
    """The build this turn is about: the one named, else the one selected."""
    chosen = (slots or {}).get("project")
    if chosen:
        project = next((item for item in projects_for(user) if item["id"] == chosen), None)
        if project:
            if thread and thread.get("project_id") != project["id"]:
                thread["project_id"] = project["id"]
                _touch(thread["id"], project_id=project["id"])
            return project
    project = current_project(user, thread)
    if not project:
        raise ValueError("You have no build yet. Start one first.")
    return project


def _property_row(user, slots):
    rows = rentals.portfolio(user["id"])
    chosen = slots.get("property")
    if chosen:
        for row in rows:
            if row["id"] == chosen:
                return row
    if len(rows) == 1:
        return rows[0]
    raise services.ServiceError("Tell me which property this is for.")


def _stage_choices(user, thread, slots):
    project = _load_project(user, thread, slots)
    open_stages = [
        (row["key"], f"{row['position']}. {row['name']} ({row['status'].replace('_', ' ')})")
        for row in project["stages"]
        if row["status"] != "complete"
    ]
    return open_stages[:8] or [
        (row["key"], row["name"]) for row in project["stages"][:5]
    ]


def _commit_money(user, thread, slots):
    kind = slots.get("kind") or slots.get("type") or "EXPENSE"
    project = _load_project(user, thread, slots)
    result = services.record_project_transaction(
        user,
        project,
        tx_type=kind,
        amount_cents=slots["amount"],
        description=slots["description"],
        category=slots.get("category") or "other",
        stage_key=slots.get("stage"),
        method=slots.get("method") or "BANK_TRANSFER",
        occurred=slots.get("occurred"),
    )
    verb = "Deposit" if kind == "FUNDING" else "Expense"
    project = _fresh_project(user, project["id"]) or project
    return {
        "body": (
            f"{verb} of {format_money(result['amount_cents'])} recorded on "
            f"{project['name']} — {slots['description']}."
        ),
        "card": _project_card(project),
        "actions": _project_actions(project),
        "undo": {
            "kind": "transaction",
            "id": result["id"],
            "project": project["id"],
            "label": f"{verb.lower()} of {format_money(result['amount_cents'])}",
        },
    }


def _summary_money(user, thread, slots):
    kind = slots.get("kind") or slots.get("type") or "EXPENSE"
    project = _load_project(user, thread, slots)
    rows = [
        ("Project", project["name"]),
        ("Type", "Money in" if kind == "FUNDING" else "Money out"),
        ("Amount", format_money(slots["amount"])),
        ("For", slots["description"]),
    ]
    if kind != "FUNDING" and slots.get("category"):
        rows.append(("Bucket", slots["category"].replace("_", " ").title()))
    if slots.get("occurred"):
        rows.append(("Date", slots["occurred"]))
    if slots.get("method"):
        rows.append(("Method", slots["method"].replace("_", " ").title()))
    return rows


def _commit_update(user, thread, slots):
    project = _load_project(user, thread, slots)
    result = services.post_project_update(user, project, slots["message"])
    note = (
        "The client will see it in their Updates inbox."
        if result["delivered"]
        else "Saved to the record."
    )
    project = _fresh_project(user, project["id"]) or project
    return {
        "body": f"Update posted on {project['name']}. {note}",
        "card": _project_card(project),
        "actions": _project_actions(project),
    }


def _commit_stage(user, thread, slots):
    project = _load_project(user, thread, slots)
    stage = next(
        (row for row in project["stages"] if row["key"] == slots["stage"]), None
    )
    if not stage:
        raise services.ServiceError("That stage is no longer on the plan.")
    services.change_stage_status(
        user, project, stage, slots["change"], slots.get("note", "")
    )
    project = _fresh_project(user, project["id"]) or project
    return {
        "body": f"{stage['name']} is now {slots['change'].replace('_', ' ')}.",
        "card": _project_card(project),
        "actions": _project_actions(project),
        "undo": {
            "kind": "stage",
            "id": stage["id"],
            "project": project["id"],
            "previous": stage["status"],
            "label": f"{stage['name']} → {slots['change'].replace('_', ' ')}",
        },
    }


def _commit_rent(user, thread, slots):
    property_row = _property_row(user, slots)
    invoice = None
    chosen = slots.get("invoice")
    if chosen and chosen != "account":
        if chosen.startswith("number:"):
            number = chosen.split(":", 1)[1]
            invoice = query(
                """SELECT * FROM property_invoices
                    WHERE number = ? AND property_id = ?
                    ORDER BY period_start DESC LIMIT 1""",
                (number, property_row["id"]),
                one=True,
            )
        else:
            invoice = query(
                "SELECT * FROM property_invoices WHERE id = ? AND property_id = ?",
                (chosen, property_row["id"]),
                one=True,
            )
    result = services.record_rent_payment(
        user,
        property_row,
        amount_cents=slots["amount"],
        method=slots.get("method") or "ECOCASH",
        invoice=invoice,
        received_at=slots.get("received_at"),
    )
    return {
        "body": (
            f"Receipt {result['receipt']} recorded: {format_money(result['amount_cents'])} "
            f"for {property_row['name']}."
        ),
        "links": [
            {
                "label": f"Open receipt {result['receipt']}",
                "href": f"/property/payments/{result['id']}/receipt",
            }
        ],
        "card": _portfolio_card(user["id"]),
        "actions": _property_actions(),
        "undo": {
            "kind": "rent",
            "id": result["id"],
            "property": property_row["id"],
            "label": f"receipt {result['receipt']}",
        },
    }


def _commit_cost(user, thread, slots):
    property_row = _property_row(user, slots)
    result = services.record_property_expense(
        user,
        property_row,
        category=slots["category"],
        amount_cents=slots["amount"],
        description=slots["description"],
        method=slots.get("method") or "BANK_TRANSFER",
        incurred=slots.get("incurred"),
    )
    return {
        "body": (
            f"Cost of {format_money(slots['amount'])} recorded on {property_row['name']}"
            f" — {slots['description']}."
        ),
        "card": _portfolio_card(user["id"]),
        "actions": _property_actions(),
        "undo": {
            "kind": "cost",
            "id": result["id"],
            "property": property_row["id"],
            "label": f"cost of {format_money(slots['amount'])}",
        },
    }


def _commit_tenant(user, thread, slots):
    property_row = _property_row(user, slots)
    name = slots["name"]
    phone = slots.get("phone")
    if phone in {"-", "—", "skip"}:
        phone = None
    tenant_id = new_id()
    execute(
        """INSERT INTO property_tenants
             (id, property_id, owner_id, name, email, phone, national_id, status,
              moved_in, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, NULL, ?, NULL, 'active', ?, NULL, ?, ?)""",
        (
            tenant_id,
            property_row["id"],
            property_row["owner_id"],
            name[:120],
            phone or None,
            date.today().isoformat(),
            now_iso(),
            now_iso(),
        ),
    )
    rentals.sync_property_status(property_row["id"])
    log_event(
        user["id"], None, "tenant.added", f"{name[:80]} at {property_row['name'][:60]}"
    )
    rentals.log_activity(
        property_row["owner_id"],
        property_row["id"],
        user["id"],
        "tenant.added",
        "Tenant added",
        name,
        href=f"/property/properties/{property_row['id']}",
    )
    return {
        "body": f"{name} is now a tenant at {property_row['name']}. Draft the lease next.",
        "links": [
            {
                "label": "Draft the lease",
                "href": f"/property/leases/new?property={property_row['id']}&tenant={tenant_id}",
            }
        ],
        "actions": _property_actions(),
    }


def _commit_work_order(user, thread, slots):
    property_row = _property_row(user, slots)
    tenant = rentals.tenant_in_place(property_row["id"])
    execute(
        """INSERT INTO property_work_orders
             (id, owner_id, property_id, tenant_id, title, description, priority, status,
              reported_at, scheduled_for, contractor_name, contractor_phone, cost_cents,
              created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, NULL, ?, 'open', ?, NULL, NULL, NULL, 0, ?, ?, ?)""",
        (
            new_id(),
            property_row["owner_id"],
            property_row["id"],
            tenant["id"] if tenant else None,
            slots["title"][:160],
            slots.get("priority", "normal"),
            date.today().isoformat(),
            user["id"],
            now_iso(),
            now_iso(),
        ),
    )
    log_event(user["id"], None, "property.work_order", slots["title"][:120])
    rentals.log_activity(
        property_row["owner_id"],
        property_row["id"],
        user["id"],
        "property.work_order",
        "Work order opened",
        slots["title"],
        href="/property/work-orders",
    )
    return {
        "body": f"Work order opened on {property_row['name']}: {slots['title']}.",
        "links": [{"label": "Open work orders", "href": "/property/work-orders"}],
        "actions": _property_actions(),
    }


def _summary_rent(user, thread, slots):
    rows = [("Amount", format_money(slots["amount"]))]
    chosen = slots.get("invoice")
    if chosen and chosen != "account":
        if chosen.startswith("number:"):
            rows.append(("Against", f"invoice {chosen.split(':', 1)[1]}"))
        else:
            invoice = query(
                "SELECT number FROM property_invoices WHERE id = ?", (chosen,), one=True
            )
            rows.append(("Against", invoice["number"] if invoice else "invoice"))
    else:
        rows.append(("Against", "money on account"))
    rows.append(("Method", (slots.get("method") or "ECOCASH").replace("_", " ").title()))
    if slots.get("received_at"):
        rows.append(("Received", slots["received_at"]))
    return rows


def _invoice_choices(user, _thread, slots):
    property_id = slots.get("property")
    rows = [
        row
        for row in rentals.open_invoices(user["id"], limit=12)
        if not property_id or row["property_id"] == property_id
    ][:5]
    choices = [
        (row["id"], f"{row['number']} · {format_money(row['balance_cents'])} due")
        for row in rows
    ]
    choices.append(("account", "No invoice — money on account"))
    return choices


FLOWS = {
    "money": Flow(
        key="money",
        label="Record money",
        portal=portals.PROJECT,
        steps=[
            _project_choice_step(),
            Step(
                "kind",
                "Is this money you sent in, or money spent?",
                kind="choice",
                choices=lambda *_args: [("FUNDING", "Money in"), ("EXPENSE", "Money out")],
                parse=_choice_parse,
            ),
            Step(
                "amount",
                "How much?",
                parse=_amount,
                hint="A figure in US dollars, for example 500 or 1,250.50.",
            ),
            Step(
                "description",
                "What was it for?",
                parse=_plain(3, "Add a short description so the entry makes sense later."),
            ),
            Step(
                "category",
                "Which bucket does it belong to?",
                kind="choice",
                choices=lambda *_args: list(services.EXPENSE_CATEGORIES),
                parse=_choice_parse,
                when=lambda slots: (slots.get("kind") or slots.get("type")) != "FUNDING",
            ),
        ],
        commit=_commit_money,
        summary=_summary_money,
    ),
    "update": Flow(
        key="update",
        label="Post an update",
        portal=portals.PROJECT,
        steps=[
            _project_choice_step(),
            Step("message", "What should the client know?", parse=_plain(3, "Write the update.")),
        ],
        commit=_commit_update,
        summary=lambda user, thread, slots: [
            ("Project", _load_project(user, thread, slots)["name"]),
            ("Update", slots["message"]),
        ],
    ),
    "stage": Flow(
        key="stage",
        label="Change a stage",
        portal=portals.PROJECT,
        steps=[
            _project_choice_step(),
            Step(
                "stage",
                "Which stage?",
                kind="choice",
                choices=_stage_choices,
                parse=_choice_parse,
            ),
            Step(
                "change",
                "What is happening to it?",
                kind="choice",
                choices=lambda *_args: [
                    ("in_progress", "Start it"),
                    ("complete", "Mark it complete"),
                    ("blocked", "Block it"),
                ],
                parse=_choice_parse,
            ),
            Step(
                "note",
                "Why is it blocked?",
                parse=_plain(3, "Give the reason, so the client can act on it."),
                when=lambda slots: slots.get("change") == "blocked",
            ),
        ],
        commit=_commit_stage,
        summary=lambda user, thread, slots: [
            ("Stage", stage_name(slots["stage"]) or slots["stage"]),
            ("Change", str(slots["change"]).replace("_", " ").title()),
        ]
        + ([("Reason", slots["note"])] if slots.get("note") else []),
    ),
    "rent": Flow(
        key="rent",
        label="Receipt rent",
        portal=portals.PROPERTY,
        steps=[
            _property_choice_step(),
            Step(
                "invoice",
                "Which invoice are you receipting?",
                kind="choice",
                choices=_invoice_choices,
                parse=_choice_parse,
                when=lambda slots: not slots.get("invoice"),
            ),
            Step(
                "amount",
                "How much did you receive?",
                parse=_amount,
                hint="The full balance is fine — just send the figure.",
            ),
            Step(
                "method",
                "How was it paid?",
                kind="choice",
                choices=lambda *_args: list(PAYMENT_METHODS),
                parse=_choice_parse,
            ),
        ],
        commit=_commit_rent,
        summary=_summary_rent,
    ),
    "cost": Flow(
        key="cost",
        label="Record a cost",
        portal=portals.PROPERTY,
        steps=[
            _property_choice_step(),
            Step(
                "category",
                "What kind of cost?",
                kind="choice",
                choices=lambda *_args: list(rentals.EXPENSE_CATEGORIES),
                parse=_choice_parse,
            ),
            Step("amount", "How much was it?", parse=_amount),
            Step("description", "What was it for?", parse=_plain(3, "Add a short description.")),
        ],
        commit=_commit_cost,
        summary=lambda user, thread, slots: [
            ("Amount", format_money(slots["amount"])),
            ("Category", slots["category"].replace("_", " ").title()),
            ("For", slots["description"]),
        ]
        + ([("Date", slots["incurred"])] if slots.get("incurred") else []),
    ),
    "tenant": Flow(
        key="tenant",
        label="Add a tenant",
        portal=portals.PROPERTY,
        steps=[
            _property_choice_step(),
            Step("name", "What is the tenant's full name?", parse=_plain(2, "Enter the full name.")),
            Step(
                "phone",
                "What is their phone number?",
                parse=lambda text, _choices=None: (text or "").strip()[:40] or None,
                hint="Used for rent reminders on WhatsApp. Send a dash to skip.",
            ),
        ],
        commit=_commit_tenant,
        summary=lambda user, thread, slots: [
            ("Tenant", slots["name"]),
            ("Phone", slots.get("phone") or "—"),
        ],
    ),
    "work_order": Flow(
        key="work_order",
        label="Open a work order",
        portal=portals.PROPERTY,
        steps=[
            _property_choice_step(),
            Step("title", "What needs fixing?", parse=_plain(4, "Say what needs fixing.")),
            Step(
                "priority",
                "How urgent is it?",
                kind="choice",
                choices=lambda *_args: list(rentals.WORK_ORDER_PRIORITIES),
                parse=_choice_parse,
            ),
        ],
        commit=_commit_work_order,
        summary=lambda user, thread, slots: [
            ("Issue", slots["title"]),
            ("Priority", slots.get("priority", "normal").title()),
        ],
    ),
}

# Commands people type rather than tap. Each maps to a flow or a screen.
FLOW_WORDS = {
    "money": "money",
    "record money": "money",
    "deposit": "money",
    "pay": "money",
    "expense": "money",
    "update": "update",
    "post update": "update",
    "stage": "stage",
    "rent": "rent",
    "receipt": "rent",
    "cost": "cost",
    "tenant": "tenant",
    "add tenant": "tenant",
    "work order": "work_order",
}

OPEN_ACTIONS = {
    portals.PROJECT: [
        ("New project", "/app/projects/new"),
        ("Ledger", "/app/money"),
        ("Documents", "/app/documents"),
        ("Agreements", "/app/agreements"),
        ("Reports", "/app/reports"),
        ("Attention", "/app/attention"),
        ("Suppliers", "/app/suppliers"),
        ("WhatsApp", "/app/whatsapp"),
        ("Dashboard", "/app/dashboard"),
        ("Settings", "/app/settings"),
    ],
    portals.PROPERTY: [
        ("Properties", "/property/properties"),
        ("Add a property", "/property/properties"),
        ("Tenants", "/property/tenants"),
        ("Leases", "/property/leases"),
        ("Rent invoices", "/property/invoices"),
        ("Receipts", "/property/payments"),
        ("Costs", "/property/expenses"),
        ("Work orders", "/property/work-orders"),
        ("Reports", "/property/reports"),
        ("Dashboard", "/property/dashboard"),
    ],
}


def flow_menu(portal: str) -> list[dict]:
    actions = []
    for flow in FLOWS.values():
        if flow.portal != portal:
            continue
        actions.append({"label": flow.label, "value": f"{VERB_PREFIX}flow:{flow.key}"})
    actions.append({"label": "Start over", "value": f"{VERB_PREFIX}reset"})
    return actions


def commands_message(portal: str) -> dict:
    opens = [
        {"label": f"Open {label.lower()}", "href": href}
        for label, href in OPEN_ACTIONS.get(portal, OPEN_ACTIONS[portals.PROJECT])
    ]
    return {
        "body": (
            "Two ways to use me. Say or pick an action and I run a short guided flow — "
            "for example “spent 340 on cement”. Or just ask a question in your own "
            "words. The links open the full screen for anything that needs more fields."
        ),
        "actions": flow_menu(portal),
        "links": opens,
    }


# ----------------------------------------------------------------------
# Flow state machine
# ----------------------------------------------------------------------


def _active_steps(flow, slots):
    return [step for step in flow.steps if not step.when or step.when(slots)]


def _draft_of(thread):
    if not thread or not thread["draft"]:
        return None
    try:
        draft = json.loads(thread["draft"])
    except (TypeError, ValueError):
        return None
    return draft if draft.get("flow") in FLOWS else None


def _ask_step(user, thread, draft):
    flow = FLOWS[draft["flow"]]
    slots = draft["slots"]
    steps = _active_steps(flow, slots)

    # Skip whatever the sentence already answered, so a full instruction lands
    # on the confirmation instead of walking the person through what they said.
    # A choice with one option is not a question either — answering it for them
    # keeps "there is only one invoice" from becoming a tap.
    step = None
    choices = None
    while draft["index"] < len(steps):
        candidate = steps[draft["index"]]
        if candidate.key in slots:
            draft["index"] += 1
            continue
        if candidate.kind == "choice":
            options = candidate.choices(user, thread, slots) if candidate.choices else []
            if len(options) == 1:
                slots[candidate.key] = options[0][0]
                draft["index"] += 1
                continue
            choices = options
        step = candidate
        break

    if step is None or draft["index"] >= len(steps):
        return _ask_confirm(user, thread, draft)

    draft["choices"] = [{"value": value, "label": label} for value, label in (choices or [])]
    draft["step"] = step.key
    _touch(thread["id"], draft)

    prompt = step.prompt
    if step.hint:
        prompt = f"{prompt}\n{step.hint}"
    actions = (
        [{"label": label, "value": str(value)} for value, label in choices]
        if step.kind == "choice"
        else []
    )
    actions.append({"label": "Cancel", "value": f"{VERB_PREFIX}cancel"})
    return {"body": prompt, "actions": actions}


def _ask_confirm(user, thread, draft):
    flow = FLOWS[draft["flow"]]
    rows = flow.summary(user, thread, draft["slots"])
    draft["step"] = "confirm"
    _touch(thread["id"], draft)
    return {
        "body": "Ready. Shall I record it? Say “change the amount to 600” if something is off.",
        "card": {
            "title": flow.label,
            "stats": [[label, value] for label, value in rows],
        },
        "actions": [
            {"label": "Yes, record it", "value": f"{VERB_PREFIX}confirm", "tone": "primary"},
            {"label": "Cancel", "value": f"{VERB_PREFIX}cancel"},
        ],
    }


def _begin(user, thread, flow_key, slots=None, pending=None):
    flow = FLOWS.get(flow_key)
    if not flow or flow.portal != thread["portal"]:
        return None
    slots = {key: value for key, value in (slots or {}).items() if value not in (None, "")}
    if flow.portal == portals.PROJECT:
        projects = projects_for(user)
        if not projects:
            return {
                "body": (
                    "Start a build first — then I can record the money, move the "
                    "stages and keep the proof with it."
                ),
                "links": [{"label": "Start a build", "href": "/app/projects/new"}],
            }
        selected = slots.get("project") or (thread or {}).get("project_id")
        if len(projects) == 1:
            slots.setdefault("project", projects[0]["id"])
        elif selected and any(item["id"] == selected for item in projects):
            slots["project"] = selected
        else:
            # Several builds and no selection: asking beats writing to the wrong one.
            slots["_needs_project"] = True
    if flow.portal == portals.PROPERTY:
        rows = rentals.portfolio(user["id"])
        if not rows:
            return {
                "body": (
                    "Add a property first — then I can receipt rent, record costs "
                    "and open work orders."
                ),
                "links": [{"label": "Add a property", "href": "/property/properties"}],
            }
        if len(rows) == 1:
            slots.setdefault("property", rows[0]["id"])
    draft = {"flow": flow_key, "index": 0, "slots": slots, "step": None}
    if pending:
        draft["pending"] = pending
    return _ask_step(user, thread, draft)


def _queue_next(user, thread, draft, replies):
    pending = list(draft.get("pending") or [])
    if not pending:
        _touch(thread["id"], {})
        return replies
    following = pending.pop(0)
    started = _begin(user, thread, following["flow"], following.get("slots"), pending)
    if started:
        replies.append(started)
    else:
        _touch(thread["id"], {})
    return replies


def _decide(user, thread, draft, text):
    flow = FLOWS[draft["flow"]]
    lowered = text.lower().strip(" .!")
    if (
        lowered in chat_nlu.CONFIRM_WORDS
        or lowered == f"{VERB_PREFIX}confirm"
        or lowered.startswith(f"{VERB_PREFIX}confirm:")
    ):
        try:
            result = flow.commit(user, thread, draft["slots"])
        except services.ServiceError as error:
            pending = draft.get("pending") or []
            _touch(thread["id"], {"pending": pending} if pending else {})
            return [
                {
                    "body": f"{error} Nothing was recorded. Let's start that one again.",
                    "actions": flow_menu(thread["portal"]),
                }
            ]
        replies = [result] if isinstance(result, dict) else list(result)
        return _queue_next(user, thread, draft, replies)

    if lowered in chat_nlu.CANCEL_WORDS or lowered.startswith(f"{VERB_PREFIX}cancel"):
        replies = [
            {
                "body": "Cancelled. Nothing was recorded.",
                "actions": flow_menu(thread["portal"]),
            }
        ]
        return _queue_next(user, thread, draft, replies)

    # A fresh instruction typed over the confirmation wins: cancel this one and
    # read the sentence as the new instruction it clearly is.
    _touch(thread["id"], {})
    fresh = _from_intents(user, thread, text)
    if fresh:
        return [
            {"body": "Cancelled the previous one — nothing was recorded there."}
        ] + fresh
    return [
        {
            "body": "I did not catch a yes or a no. Nothing was recorded.",
            "actions": flow_menu(thread["portal"]),
        }
    ]


def _advance(user, thread, text):
    """Feed the turn into the running flow. None when nothing is running."""
    draft = _draft_of(thread)
    if not draft:
        return None
    flow = FLOWS[draft["flow"]]

    if draft.get("step") == "confirm":
        return _decide(user, thread, draft, text)

    steps = _active_steps(flow, draft["slots"])
    if draft["index"] >= len(steps):
        return [_ask_confirm(user, thread, draft)]

    step = steps[draft["index"]]
    choices = step.choices(user, thread, draft["slots"]) if step.choices else None

    position = chat_nlu.ordinal_index(text, len(choices or []))
    try:
        if step.kind == "choice" and choices and position is not None:
            value = choices[position][0]
        else:
            value = step.parse(text, choices) if step.parse else text
    except ValueError as error:
        prompt = _ask_step(user, thread, draft)
        if chat_nlu.looks_like_question(text):
            # Answer the question and keep the flow where it was.
            return [_read(user, thread["portal"], text), prompt]
        # "Actually, receipt 450 rent" while halfway through another flow: the
        # new instruction is what they mean, so stop asking the old question.
        if step.kind == "choice":
            changed = _switched_instruction(user, thread, draft, text)
            if changed:
                return changed
        return [
            {"body": f"{error}\n\n{prompt['body']}", "actions": prompt.get("actions")}
        ]

    draft["slots"][step.key] = value
    draft["index"] += 1
    draft.pop("choices", None)
    return [_ask_step(user, thread, draft)]


def _switched_instruction(user, thread, draft, text):
    """A confident, self-contained instruction replaces the one running."""
    intents = chat_nlu.detect(
        text,
        _build_context(user, thread["portal"]),
        portal=thread["portal"],
        stages=_stages_for(user, thread),
    )
    if not intents or intents[0].score < 0.85:
        return None
    mapped = _flow_for_intent(thread["portal"], intents[0])
    # A half-said instruction ("spent 200") is a better answer to the question
    # than a new errand, so only a sentence that already carries its own detail
    # is allowed to take over — and only for a different flow, or repeating the
    # same instruction would restart it.
    if not mapped or len(mapped["slots"]) < 3:
        return None
    if mapped["flow"] == draft["flow"]:
        return None
    _touch(thread["id"], {})
    started = _from_intents(user, thread, text)
    if not started:
        return None
    return [
        {"body": "Switched to what you just said — the earlier one was not recorded."}
    ] + started


def _apply_correction(user, thread, draft, fixed):
    draft["slots"][fixed["field"]] = fixed["value"]
    _touch(thread["id"], draft)
    return [_ask_step(user, thread, draft)]


# ----------------------------------------------------------------------
# Undo
# ----------------------------------------------------------------------


def _recent(created_at: str) -> bool:
    try:
        stamp = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    age = datetime.now(stamp.tzinfo) - stamp
    return age.total_seconds() <= UNDO_MINUTES * 60


def undo_last(user, thread) -> dict:
    """Take back the last write made in this conversation."""
    events = history(thread["id"], limit=120)
    undone = {event.get("undo_of") for event in events if event.get("undo_of")}
    for event in reversed(events):
        payload = event.get("undo")
        if not payload or event["id"] in undone:
            continue
        if not _recent(event.get("created_at")):
            return {
                "body": (
                    "That was recorded more than a day ago, so I will not quietly "
                    "take it back. Open the record and delete it there."
                ),
                "links": [{"label": "Open the ledger", "href": "/app/money"}],
            }
        try:
            body = _reverse(user, payload)
        except services.ServiceError as error:
            return {"body": str(error), "actions": flow_menu(thread["portal"])}
        return {
            "body": body,
            "undo_of": event["id"],
            "actions": flow_menu(thread["portal"]),
        }
    return {
        "body": "There is nothing recent for me to undo in this conversation.",
        "actions": flow_menu(thread["portal"]),
    }


def _reverse(user, payload) -> str:
    kind = payload.get("kind")
    if kind == "transaction":
        project = next(
            (item for item in projects_for(user) if item["id"] == payload.get("project")),
            None,
        )
        if not project:
            raise services.ServiceError("That build is no longer in your workspace.")
        removed = services.delete_project_transaction(user, project, payload["id"])
        return f"Removed the {format_money(removed['amount_cents'])} entry — {removed['description']}."

    if kind == "rent":
        property_row = next(
            (row for row in rentals.portfolio(user["id"]) if row["id"] == payload.get("property")),
            None,
        )
        if not property_row:
            raise services.ServiceError("That property is no longer in your portfolio.")
        removed = services.reverse_rent_payment(user, property_row, payload["id"])
        return (
            f"Reversed receipt {removed['receipt']} "
            f"({format_money(removed['amount_cents'])}). The invoice is open again."
        )

    if kind == "cost":
        property_row = next(
            (row for row in rentals.portfolio(user["id"]) if row["id"] == payload.get("property")),
            None,
        )
        if not property_row:
            raise services.ServiceError("That property is no longer in your portfolio.")
        removed = services.delete_property_expense(user, property_row, payload["id"])
        return f"Removed the {format_money(removed['amount_cents'])} cost — {removed['description']}."

    if kind == "stage":
        stage = query("SELECT * FROM stages WHERE id = ?", (payload["id"],), one=True)
        project = next(
            (item for item in projects_for(user) if item["id"] == payload.get("project")),
            None,
        )
        if not stage or not project:
            raise services.ServiceError("That stage has changed since. Open the build to adjust it.")
        services.change_stage_status(user, project, stage, payload["previous"] or "pending", "")
        return f"{stage['name']} moved back to {(payload['previous'] or 'pending').replace('_', ' ')}."

    raise services.ServiceError("I do not know how to undo that one.")


# ----------------------------------------------------------------------
# Answers that need more than a lookup
# ----------------------------------------------------------------------


def _brief(user, thread) -> dict:
    portal = thread["portal"]
    if portal == portals.PROPERTY:
        totals = rentals.dashboard_totals(user["id"])
        if not totals["properties"]:
            return {
                "body": "Nothing to report yet — there is no property on the record.",
                "links": [{"label": "Add a property", "href": "/property/properties"}],
            }
        body = (
            f"{totals['month_label']}: {format_money(totals['collected'])} collected of "
            f"{format_money(totals['rent_roll'])} rent roll, {format_money(totals['expenses'])} "
            f"in costs, {format_money(totals['outstanding'])} outstanding."
        )
        extras = []
        if totals["work_orders"]:
            extras.append(plural(totals["work_orders"], "work order") + " open")
        if totals["checks_due"]:
            extras.append(plural(totals["checks_due"], "property check") + " due")
        if totals["expiring_leases"]:
            extras.append(
                plural(totals["expiring_leases"], "lease") + " expiring within 60 days"
            )
        if extras:
            body += " Also: " + ", ".join(extras) + "."
        return {"body": body, "card": _portfolio_card(user["id"]), "actions": _property_actions()}

    projects = projects_for(user)
    project = current_project(user, thread)
    if not project:
        return {
            "body": "No build on the record yet, so there is nothing to report.",
            "links": [{"label": "Start a build", "href": "/app/projects/new"}],
        }
    counts = queries.attention_counts([item["id"] for item in projects])
    totals = project["totals"]
    body = (
        f"{project['name']}: {format_money(totals['funded'])} received, "
        f"{format_money(totals['spent'])} spent, {format_money(totals['balance'])} available, "
        f"{project['progress']}% through the plan."
    )
    next_stage = queries.next_stage(project["stages"])
    if next_stage:
        body += (
            f" Next up is {next_stage['name']} ({next_stage['status'].replace('_', ' ')})."
            if next_stage["status"] in {"in_progress", "blocked"}
            else f" Next up is {next_stage['name']}."
        )
    if counts["total"]:
        body += (
            f" {plural(counts['total'], 'thing')} need attention: "
            f"{counts['blocked']} blocked, {counts['approvals']} awaiting approval, "
            f"{counts['receipts']} without a receipt, "
            f"{counts['agreements']} to sign."
        )
    return {
        "body": body,
        "card": _project_card(project),
        "actions": _project_actions(project),
    }


def _spend_answer(user, thread, text) -> dict | None:
    """Answer "how much did I spend on cement?" from the ledger itself."""
    if thread["portal"] != portals.PROJECT:
        return None
    lowered = text.lower()
    trigger = next(
        (
            word
            for word in (
                "spent on",
                "spend on",
                "spending on",
                "cost of",
                "how much on",
                "how much did i spend",
                "how much have i spent",
                "how much have we spent",
                "total for",
                "how much for",
            )
            if word in lowered
        ),
        None,
    )
    if not trigger:
        return None
    project = current_project(user, thread)
    if not project:
        return None

    keyword = lowered.split(trigger, 1)[1].strip(" ?.!,:;")
    keyword = keyword.replace("%", "").replace("_", " ").strip()
    params = [project["id"]]
    clause = "project_id = ? AND type = 'EXPENSE'"
    if keyword:
        clause += " AND (LOWER(description) LIKE ? OR LOWER(category) LIKE ?)"
        params += [f"%{keyword}%", f"%{keyword}%"]
    rows = query(
        f"""SELECT description, amount_cents, occurred_at, category
            FROM transactions WHERE {clause}
            ORDER BY occurred_at DESC""",
        params,
    )
    if not rows:
        return {
            "body": (
                f"Nothing on {project['name']} matches “{keyword or 'spending'}” yet."
                if keyword
                else f"No spending recorded on {project['name']} yet."
            ),
            "links": [{"label": "Open the ledger", "href": "/app/money"}],
        }

    total = sum(int(row["amount_cents"]) for row in rows)
    body = (
        f"Spent {format_money(total)} on “{keyword}” across {len(rows)} "
        f"entr{'y' if len(rows) == 1 else 'ies'} on {project['name']}."
        if keyword
        else f"Spent {format_money(total)} across {len(rows)} entries on {project['name']}."
    )
    latest = rows[0]
    body += (
        f" The most recent was {format_money(latest['amount_cents'])} — "
        f"{latest['description']} ({str(latest['occurred_at'])[:10]})."
    )
    if len(rows) > 1:
        biggest = max(rows, key=lambda row: int(row["amount_cents"]))
        body += (
            f" The biggest single entry was {format_money(biggest['amount_cents'])} — "
            f"{biggest['description']}."
        )
    return {
        "body": body,
        "card": {
            "title": f"“{keyword}”" if keyword else "Spending",
            "stats": [
                ["Total", format_money(total)],
                ["Entries", str(len(rows))],
                ["Project", project["name"]],
            ],
        },
        "links": [{"label": "Open the ledger", "href": "/app/money"}],
        "actions": _project_actions(project),
    }


def _portfolio_answer(user, thread, text) -> dict | None:
    if thread["portal"] != portals.PROPERTY:
        return None
    lowered = text.lower()
    if not any(
        word in lowered
        for word in ("collect", "collected", "income", "how much rent", "net", "made this month")
    ):
        return None
    totals = rentals.dashboard_totals(user["id"])
    return {
        "body": (
            f"{totals['month_label']}: {format_money(totals['collected'])} collected, "
            f"{format_money(totals['outstanding'])} still outstanding, "
            f"{format_money(totals['expenses'])} in costs — net "
            f"{format_money(totals['net'])}."
        ),
        "card": _portfolio_card(user["id"]),
        "links": [{"label": "Open reports", "href": "/property/reports"}],
        "actions": _property_actions(),
    }


def _insight(user, thread, text) -> dict | None:
    return _spend_answer(user, thread, text) or _portfolio_answer(user, thread, text)


# ----------------------------------------------------------------------
# Small talk
# ----------------------------------------------------------------------

_SMALLTALK = (
    ("thank", "Anytime. Anything else on the build?"),
    ("thanx", "Anytime. Anything else on the build?"),
    ("ta", "Anytime. Anything else on the build?"),
    ("good morning", "Morning. What are we doing today?"),
    ("good afternoon", "Afternoon. What are we doing today?"),
    ("good evening", "Evening. What are we doing today?"),
    ("hello", "Hello. What would you like to do?"),
    ("hi", "Hello. What would you like to do?"),
    ("hey", "Hello. What would you like to do?"),
    ("bye", "Bye. Everything you recorded is saved."),
    ("goodbye", "Bye. Everything you recorded is saved."),
    ("who are you", "I am the YaVaKa assistant. I can record money, post updates, move stages and answer questions about your records."),
    ("how are you", "Working, and ready. What do you need?"),
)


def _smalltalk(text: str) -> dict | None:
    lowered = text.lower().strip(" .!?")
    for trigger, reply in _SMALLTALK:
        if lowered == trigger or lowered.startswith(trigger + " "):
            return {"body": reply}
    return None


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def _read(user, portal: str, text: str) -> dict:
    g.assistant_portal = portal
    try:
        result = assistant.answer(user, text)
    except Exception:  # noqa: BLE001 - a broken read must not break the chat
        return {
            "body": (
                "I could not work that one out. Try asking about the balance, a stage, "
                "the documents or what needs attention — or open the full screen."
            ),
            "links": [
                {"label": "Open the dashboard", "href": portals.home_path(portal) + "/dashboard"}
            ],
        }
    links = [{"label": label, "href": href} for label, href in result.get("links", [])]
    actions = [
        {"label": label, "value": label} for label in result.get("suggestions", [])[:4]
    ]
    return {"body": result["reply"], "links": links, "actions": actions}


def _flow_for_intent(portal: str, intent) -> dict | None:
    slots = dict(intent.slots or {})
    kind = intent.kind

    if kind == "record_money":
        money_type = slots.pop("type", None) or "EXPENSE"
        if portal == portals.PROPERTY:
            if money_type == "FUNDING":
                return {"flow": "rent", "slots": _clean({
                    "amount": slots.get("amount"),
                    "property": slots.get("property"),
                    "method": slots.get("method"),
                    "received_at": slots.get("occurred"),
                })}
            return {"flow": "cost", "slots": _clean({
                "amount": slots.get("amount"),
                "description": slots.get("description"),
                "category": slots.get("category") or "other",
                "property": slots.get("property"),
                "method": slots.get("method"),
                "incurred": slots.get("occurred"),
            })}
        description = slots.get("description") or ""
        if money_type == "FUNDING" and description.lower().strip() in {"", "client", "the client"}:
            description = "Client deposit"
        return {"flow": "money", "slots": _clean({
            "kind": money_type,
            "amount": slots.get("amount"),
            "description": description,
            "category": slots.get("category"),
            "method": slots.get("method"),
            "occurred": slots.get("occurred"),
            "project": slots.get("project"),
        })}

    if kind == "record_update":
        return {"flow": "update", "slots": _clean({
            "message": slots.get("message"), "project": slots.get("project")
        })}

    if kind == "change_stage":
        return {"flow": "stage", "slots": _clean({
            "stage": slots.get("stage"),
            "change": slots.get("change"),
            "note": slots.get("note"),
            "project": slots.get("project"),
        })}

    if kind == "receipt_rent":
        invoice = slots.get("invoice_number")
        return {"flow": "rent", "slots": _clean({
            "property": slots.get("property"),
            "amount": slots.get("amount"),
            "method": slots.get("method"),
            "received_at": slots.get("received_at"),
            "invoice": f"number:{invoice}" if invoice else None,
        })}

    if kind == "record_cost":
        return {"flow": "cost", "slots": _clean({
            "property": slots.get("property"),
            "category": slots.get("category") or "other",
            "amount": slots.get("amount"),
            "description": slots.get("description"),
            "method": slots.get("method"),
            "incurred": slots.get("incurred"),
        })}

    if kind == "add_tenant":
        return {"flow": "tenant", "slots": _clean({
            "property": slots.get("property"),
            "name": slots.get("name"),
            "phone": slots.get("phone"),
        })}

    if kind == "open_work_order":
        return {"flow": "work_order", "slots": _clean({
            "property": slots.get("property"),
            "title": slots.get("title"),
            "priority": slots.get("priority"),
        })}

    return None


def _clean(slots: dict) -> dict:
    return {key: value for key, value in slots.items() if value not in (None, "")}


def _from_intents(user, thread, text):
    portal = thread["portal"]
    intents = chat_nlu.detect(
        text,
        _build_context(user, portal),
        portal=portal,
        stages=_stages_for(user, thread),
    )
    if not intents:
        return []

    head = intents[0]
    if head.kind == "undo":
        return [undo_last(user, thread)]
    if head.kind == "brief":
        return [_brief(user, thread)]
    if head.kind == "help":
        return [commands_message(portal)]
    if head.kind == "confirm":
        return [
            {
                "body": "There is nothing waiting on a yes at the moment.",
                "actions": flow_menu(portal),
            }
        ]
    if head.kind == "cancel":
        return [{"body": "Nothing is running, so nothing was cancelled.", "actions": flow_menu(portal)}]

    queue = [mapped for mapped in (_flow_for_intent(portal, item) for item in intents) if mapped]
    if not queue:
        return []

    first = queue[0]
    target = first["slots"].pop("project", None)
    if target and target != thread["project_id"]:
        project = next((item for item in projects_for(user) if item["id"] == target), None)
        if project:
            thread["project_id"] = project["id"]
            _touch(thread["id"], project_id=project["id"])
    for item in queue[1:]:
        item["slots"].pop("project", None)

    started = _begin(user, thread, first["flow"], first["slots"], queue[1:])
    return [started] if started else []


def _verb(user, thread, text):
    portal = thread["portal"]
    verb, _, value = text[len(VERB_PREFIX):].partition(":")
    verb, value = verb.lower().strip(), value.strip()

    if verb == "help":
        return [commands_message(portal)]
    if verb == "reset":
        clear(thread["id"])
        listing = commands_message(portal)
        listing["body"] = "Fresh start — the record itself is untouched. " + listing["body"]
        return [listing]
    if verb in {"flow", "start"}:
        prompt = _begin(user, thread, value)
        if prompt:
            return [prompt]
        return [{"body": "I do not have that one.", "actions": flow_menu(portal)}]
    if verb == "project":
        project = next((item for item in projects_for(user) if item["id"] == value), None)
        if project:
            thread["project_id"] = project["id"]
            _touch(thread["id"], project_id=project["id"])
            return [
                {
                    "body": f"Switched to {project['name']}.",
                    "card": _project_card(project),
                    "actions": _project_actions(project),
                }
            ]
        return [{"body": "I could not find that build.", "actions": flow_menu(portal)}]
    if verb == "confirm":
        advanced = _advance(user, thread, "yes")
        return advanced or [{"body": "Nothing is waiting to be recorded.", "actions": flow_menu(portal)}]
    if verb == "cancel":
        _touch(thread["id"], {})
        return [{"body": "Cancelled. Nothing was recorded.", "actions": flow_menu(portal)}]
    if verb == "undo":
        return [undo_last(user, thread)]
    return [commands_message(portal)]


def handle(user, thread, text: str) -> list[dict]:
    """One turn. ``text`` is either something typed or an action's value."""
    text = (text or "").strip()[:MAX_BODY]
    if not text:
        return []
    portal = thread["portal"]
    lowered = text.lower().strip(" .!")

    if lowered.startswith(VERB_PREFIX):
        return _verb(user, thread, text)

    draft = _draft_of(thread)
    if lowered in chat_nlu.CANCEL_WORDS:
        if draft:
            _touch(thread["id"], {})
            return [
                {
                    "body": "Cancelled. Nothing was recorded.",
                    "actions": flow_menu(portal),
                }
            ]
        return [
            {"body": "Nothing is running, so nothing was cancelled.", "actions": flow_menu(portal)}
        ]

    if draft:
        fixed = chat_nlu.correction(text)
        if fixed and fixed.get("value") not in (None, ""):
            return _apply_correction(user, thread, draft, fixed)
        advanced = _advance(user, thread, text)
        if advanced:
            return advanced

    replies = _from_intents(user, thread, text)
    if replies:
        return replies

    navigation = chat_nlu.detect_navigation(text, OPEN_ACTIONS.get(portal, []))
    if navigation:
        if navigation.get("label") == "ambig":
            options = navigation["options"]
            return [
                {
                    "body": "Which one did you mean?",
                    "links": [
                        {"label": option["label"], "href": option["href"]} for option in options
                    ],
                }
            ]
        return [
            {
                "body": f"Opening {navigation['label']}.",
                "links": [{"label": navigation["label"], "href": navigation["href"]}],
            }
        ]

    friendly = _smalltalk(text)
    if friendly:
        friendly.setdefault("actions", _project_actions(None))
        return [friendly]

    insight = _insight(user, thread, text)
    if insight:
        return [insight]

    return [_read(user, portal, text)]


# Buttons send their value so the server can act on it, but the transcript
# should read the way the person spoke, not the way the protocol works.
_VERB_LABELS = {
    "confirm": "Yes, record it",
    "cancel": "Cancel",
    "help": "All commands",
    "reset": "Start over",
    "undo": "Undo that",
    "project": "Switch build",
}


def _spoken(text: str) -> str:
    if not text.startswith(VERB_PREFIX):
        return text
    verb, _, value = text[len(VERB_PREFIX):].partition(":")
    verb = verb.lower()
    if verb == "flow":
        flow = FLOWS.get(value)
        return flow.label if flow else "Start a flow"
    return _VERB_LABELS.get(verb, text)


def turn(user, thread, text: str, spoken: str | None = None) -> list[dict]:
    """One exchange, persisted: what was said, then every reply it earned."""
    text = (text or "").strip()[:MAX_BODY]
    if not text:
        return []
    events = [post(thread["id"], "user", (spoken or "").strip()[:120] or _spoken(text))]
    for reply in handle(user, thread, text):
        events.append(
            post(
                thread["id"],
                "assistant",
                reply.get("body", ""),
                actions=reply.get("actions"),
                links=reply.get("links"),
                card=reply.get("card"),
                undo=reply.get("undo"),
                undo_of=reply.get("undo_of"),
            )
        )
    if len(events) == 1:
        events.append(
            post(
                thread["id"],
                "assistant",
                "I did not catch that. Try “record 500 for cement”, or ask me a question.",
                actions=flow_menu(thread["portal"]),
            )
        )
    return events


def remember_project(thread, project_id: str) -> None:
    """Pin the build the conversation is looking at, so it stops being a guess."""
    if not thread or not project_id or thread.get("project_id") == project_id:
        return
    thread["project_id"] = project_id
    _touch(thread["id"], project_id=project_id)


def switch_project(user, thread, project_id: str) -> dict:
    project = next((item for item in projects_for(user) if item["id"] == project_id), None)
    if not project:
        raise services.ServiceError("That build is not in your workspace.")
    thread["project_id"] = project["id"]
    _touch(thread["id"], project_id=project["id"])
    return {
        "body": f"Switched to {project['name']}.",
        "card": _project_card(project),
        "actions": _project_actions(project),
    }
