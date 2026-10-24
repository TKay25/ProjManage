"""What changed on a build, turned into a notification for the people who own it.

Every write already records an audit event. This module fans that event out to
the project's stakeholders (owner and build manager, never the actor) so a
client can see progress as it happens instead of reading the raw log.

Notifications are stored per person, so read state is personal and a shared
device does not mark somebody else's inbox as read.
"""

from db import execute, new_id, now_iso, query

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


def describe(action: str, detail: str = "") -> dict:
    icon, title, tone = ACTIONS.get(action, ("activity", action.replace(".", " ").title(), ""))
    # The ledger detail already says "— spent"/"— received", which the action
    # label now carries, so drop the duplicate tail.
    for tail in (" — spent", " — received"):
        if detail.endswith(tail):
            detail = detail[: -len(tail)]
    return {"icon": icon, "title": title, "tone": tone, "detail": detail or "", "kind": kind_for(action)}


def notify(user_id, project_id, action, detail="", *, href=None, actor_id=None, event_id=None) -> int:
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
              href, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        row.update(describe(row["action"], row["body"] or ""))
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
