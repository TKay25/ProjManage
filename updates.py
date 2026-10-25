"""What changed on a build, turned into a notification for the people who own it.

Every write already records an audit event. This module fans that event out to
the project's stakeholders (owner and build manager, never the actor) so a
client can see progress as it happens instead of reading the raw log.

Notifications are stored per person, so read state is personal and a shared
device does not mark somebody else's inbox as read.
"""

from db import execute, new_id, now_iso, query
from health import alerts as health_alerts
from queries import money_totals

# action -> (icon, short label, tone). Anything not listed still records, using
# a neutral label derived from the action name.
ACTIONS = {
    "project.created": ("building", "Project created", ""),
    "project.updated": ("settings", "Project details updated", ""),
    "project.status": ("trending-up", "Project status changed", ""),
    "project.manager": ("users", "Build manager changed", ""),
    "project.budget": ("wallet", "Budget updated", ""),
    "project.archived": ("archive", "Project archived", ""),
    "project.restored": ("refresh", "Project restored", ""),
    "stage.completed": ("check", "Stage completed", "success"),
    "stage.blocked": ("alert", "Stage blocked", "danger"),
    "stage.updated": ("clock", "Stage updated", ""),
    "funding.recorded": ("wallet", "Funding received", "success"),
    "expense.recorded": ("receipt", "Expense recorded", ""),
    "receipt.attached": ("receipt", "Receipt attached", "success"),
    "transaction.deleted": ("trash", "Ledger entry deleted", "warn"),
    "document.uploaded": ("upload", "Document uploaded", ""),
    "document.deleted": ("trash", "Document deleted", "warn"),
    "agreement.created": ("pen", "Agreement created", ""),
    "agreement.signed": ("pen", "Agreement signed", "success"),
    "agreement.void": ("pen", "Agreement voided", "warn"),
    "team.invited": ("users", "Build manager invited", ""),
    "team.linked": ("users", "Build manager added", "success"),
    "team.joined": ("users", "Build manager joined", "success"),
    "team.removed": ("users", "Build manager removed", "warn"),
    "whatsapp.reply": ("message", "New WhatsApp reply", "warn"),
    "project.over_budget": ("alert", "Budget exceeded", "danger"),
    "project.over_spent": ("alert", "Spending exceeds funding", "danger"),
    "project.deadline_passed": ("clock", "Handover date passed", "danger"),
    "project.back_on_track": ("check", "Back within budget", "success"),
}

# Housekeeping that belongs in the audit log but is not news for a person.
# Staff-level account changes have no project, so they are never fanned out
# either; listing them documents the intent.
QUIET_ACTIONS = {"digest.sent", "user.created", "user.role"}

# Filter groups on the updates page.
KINDS = {
    "all": ("Everything", None),
    "progress": ("Progress", ("stage.",)),
    "money": ("Money", ("funding.", "expense.", "receipt.", "transaction.")),
    "documents": ("Documents", ("document.",)),
    "agreements": ("Agreements", ("agreement.",)),
    "project": ("Project", ("project.",)),
    "team": ("Team", ("team.",)),
    "whatsapp": ("WhatsApp", ("whatsapp.",)),
    "alerts": ("Alerts", ("project.over_", "project.deadline", "stage.blocked")),
}


def kind_for(action: str) -> str:
    for key, (_label, prefixes) in KINDS.items():
        if prefixes and action.startswith(prefixes):
            return key
    return "all"


def _href(action: str, project_id: str) -> str:
    """Where the recipient should land when they tap the notification."""
    if action.startswith("document."):
        return f"/app/documents?project={project_id}"
    if action.startswith(("funding.", "expense.", "receipt.", "transaction.")):
        return f"/app/money?project={project_id}"
    if action.startswith("agreement."):
        return "/app/agreements"
    if action.startswith("whatsapp."):
        return "/app/whatsapp"
    return f"/app/projects/{project_id}"


def raise_health_alerts(project_id: str, actor_id=None) -> int:
    """Notify the stakeholders when money or time goes wrong on a project.

    Called after the ledger, the budget or the dates change. Only the moment a
    threshold is *crossed* notifies — re-saving a project that is already over
    budget does not send the same red alert again — so the check compares
    against what was already raised for that project.
    """
    project = query(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM stages s
                    WHERE s.project_id = p.id AND s.status = 'blocked') AS blocked_stages,
                  (SELECT COUNT(*) FROM transactions t
                    WHERE t.project_id = p.id AND t.type = 'EXPENSE'
                      AND NOT EXISTS (
                        SELECT 1 FROM attachments a WHERE a.transaction_id = t.id
                      )) AS missing_receipts
           FROM projects p WHERE p.id = ?""",
        (project_id,),
        one=True,
    )
    if not project or project["archived_at"]:
        return 0

    totals = money_totals(project_id)
    current = health_alerts(
        project,
        totals,
        blocked_stages=int(project["blocked_stages"] or 0),
        missing_receipts=int(project["missing_receipts"] or 0),
    )

    # What was already announced for this project, and is still true.
    already = {
        row["action"]
        for row in query(
            """SELECT DISTINCT action FROM notifications
               WHERE project_id = ? AND action IN
                 ('project.over_budget', 'project.over_spent', 'project.deadline_passed')""",
            (project_id,),
        )
    }

    mapping = {
        "over_budget": "project.over_budget",
        "over_funded_spend": "project.over_spent",
        "past_deadline": "project.deadline_passed",
    }

    created = 0
    live_actions = set()
    for signal in current:
        action = mapping.get(signal["key"])
        if not action:
            continue
        live_actions.add(action)
        if action in already:
            continue
        created += notify_stakeholders(
            project,
            action,
            f"{project['name']}: {signal['label']}",
            tone=signal["tone"],
        )

    # Coming back inside budget is good news worth telling once.
    if not live_actions & {"project.over_budget", "project.over_spent"} and already & {
        "project.over_budget",
        "project.over_spent",
    }:
        cleared = query(
            """SELECT COUNT(*) AS total FROM notifications
               WHERE project_id = ? AND action = 'project.back_on_track'""",
            (project_id,),
            one=True,
        )
        if not int(cleared["total"] or 0):
            created += notify_stakeholders(
                project,
                "project.back_on_track",
                f"{project['name']} is back within budget",
                tone="success",
            )

    return created


def notify_stakeholders(project, action, detail, *, tone=None) -> int:
    """Fan one notification out to the owner and manager of a project row."""
    recipients = {project["owner_id"], project.get("manager_id")} - {None}
    created = 0
    for user_id in recipients:
        created += notify(
            user_id,
            project["id"],
            action,
            detail,
            tone=tone,
        )
    return created


def describe(action: str, detail: str = "") -> dict:
    icon, title, tone = ACTIONS.get(action, ("activity", action.replace(".", " ").title(), ""))
    # The ledger detail already says "— spent"/"— received", which the action
    # label now carries, so drop the duplicate tail.
    for tail in (" — spent", " — received"):
        if detail.endswith(tail):
            detail = detail[: -len(tail)]
    return {"icon": icon, "title": title, "tone": tone, "detail": detail or "", "kind": kind_for(action)}


def notify(user_id, project_id, action, detail="", *, href=None, actor_id=None, event_id=None, tone=None) -> int:
    """Notify one named person instead of every project stakeholder.

    Used when the recipient is already known — for example the manager who has
    taken a WhatsApp conversation over and needs to see the client's reply.
    """
    if not user_id or not project_id:
        return 0

    described = describe(action, detail)
    execute(
        """INSERT INTO notifications
             (id, user_id, project_id, event_id, actor_id, action, title, body,
              href, tone, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id(),
            user_id,
            project_id,
            event_id,
            actor_id,
            action,
            described["title"],
            described["detail"][:400] or None,
            href or _href(action, project_id),
            tone or described["tone"] or None,
            now_iso(),
        ),
    )
    return 1


def record(actor_id, project_id, action, detail="", event_id=None) -> int:
    """Fan an audit event out to the project's stakeholders.

    Returns how many notifications were created. The actor is never notified of
    their own action, and a project with no other stakeholder creates nothing.
    """
    if not actor_id or not project_id or action in QUIET_ACTIONS:
        return 0

    project = query(
        """SELECT id, owner_id, manager_id FROM projects WHERE id = ?""",
        (project_id,),
        one=True,
    )
    if not project:
        return 0

    recipients = {project["owner_id"], project["manager_id"]} - {None, actor_id}
    if not recipients:
        return 0

    created = 0
    for user_id in recipients:
        created += notify(user_id, project_id, action, detail, event_id=event_id)

    return created


def _where(kind: str, user_id: str):
    prefixes = KINDS.get(kind, KINDS["all"])[1]
    where = ["n.user_id = ?"]
    params = [user_id]
    if prefixes:
        where.append("(" + " OR ".join("n.action LIKE ?" for _ in prefixes) + ")")
        params.extend(f"{prefix}%" for prefix in prefixes)
    return " AND ".join(where), params


def feed(user_id: str, kind: str = "all", limit: int = 25, offset_rows: int = 0):
    """Newest first, joined with the project and the person who did it."""
    clause, params = _where(kind, user_id)
    rows = query(
        f"""SELECT n.*, p.name AS project_name, p.code AS project_code,
                   u.name AS actor_name, u.avatar_color AS actor_color
            FROM notifications n
            JOIN projects p ON p.id = n.project_id
            LEFT JOIN users u ON u.id = n.actor_id
            WHERE {clause}
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT ? OFFSET ?""",
        [*params, limit, offset_rows],
    )
    for row in rows:
        # `body` holds the audit detail; the label/icon/tone come from the action.
        stored = row.get("tone")
        row.update(describe(row["action"], row["body"] or ""))
        row["notification_tone"] = stored
        if stored:
            row["tone"] = stored
        # Rows written before hrefs existed still need somewhere to land.
        if not row.get("href"):
            row["href"] = _href(row["action"], row["project_id"])
        row["is_unread"] = not row.get("read_at")
    return rows


def count(user_id: str, kind: str = "all") -> int:
    clause, params = _where(kind, user_id)
    row = query(
        f"SELECT COUNT(*) AS total FROM notifications n WHERE {clause}",
        params,
        one=True,
    )
    return int(row["total"] or 0)


def unread_count(user_id: str) -> int:
    row = query(
        "SELECT COUNT(*) AS total FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (user_id,),
        one=True,
    )
    return int(row["total"] or 0)


def unread_ids(user_id: str) -> set:
    rows = query(
        "SELECT id FROM notifications WHERE user_id = ? AND read_at IS NULL",
        (user_id,),
    )
    return {row["id"] for row in rows}


def latest_unread(user_id: str):
    return query(
        """SELECT n.*, p.name AS project_name
           FROM notifications n
           JOIN projects p ON p.id = n.project_id
           WHERE n.user_id = ? AND n.read_at IS NULL
           ORDER BY n.created_at DESC
           LIMIT 1""",
        (user_id,),
        one=True,
    )


def mark_all_read(user_id: str) -> int:
    """Clear the badge. Returns how many rows changed."""
    before = unread_count(user_id)
    if before:
        execute(
            "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
            (now_iso(), user_id),
        )
    return before
