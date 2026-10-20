"""Workspaces: a banner over several projects.

A workspace is an organisational grouping, not a new permission boundary —
`auth.accessible_projects` still decides which builds a person may open. It
exists so a client, a build manager or YaVaKa staff can run several projects
under one name and filter the app down to one programme at a time.
"""

from db import execute, new_id, now_iso, query


def workspaces_for(user):
    """Workspaces the user owns, or that hold a project they can already open."""
    if not user:
        return []
    if user["role"] == "admin":
        return query("SELECT * FROM workspaces ORDER BY created_at")
    return query(
        """SELECT DISTINCT w.* FROM workspaces w
           LEFT JOIN projects p ON p.workspace_id = w.id
           WHERE w.owner_id = ? OR p.owner_id = ? OR p.manager_id = ?
           ORDER BY w.created_at""",
        (user["id"], user["id"], user["id"]),
    )


def ensure_default_workspace(user):
    """Every user gets one workspace, created the first time they need it."""
    if not user:
        return None
    existing = query(
        "SELECT * FROM workspaces WHERE owner_id = ? ORDER BY created_at LIMIT 1",
        (user["id"],),
        one=True,
    )
    if existing:
        return existing

    workspace_id = new_id()
    execute(
        "INSERT INTO workspaces (id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
        (workspace_id, f"{user['name'].split()[0]}'s workspace"[:80], user["id"], now_iso()),
    )
    return query("SELECT * FROM workspaces WHERE id = ?", (workspace_id,), one=True)


def find_workspace(user, workspace_id):
    """A workspace the user may use, or None. Never trust the query string."""
    if not workspace_id:
        return None
    return next((item for item in workspaces_for(user) if item["id"] == workspace_id), None)


def create_workspace(user, name):
    workspace_id = new_id()
    execute(
        "INSERT INTO workspaces (id, name, owner_id, created_at) VALUES (?, ?, ?, ?)",
        (workspace_id, name[:80], user["id"], now_iso()),
    )
    return query("SELECT * FROM workspaces WHERE id = ?", (workspace_id,), one=True)


def project_counts(user):
    """How many projects sit in each workspace, for the picker."""
    rows = query(
        """SELECT w.id, COUNT(p.id) AS total
           FROM workspaces w
           LEFT JOIN projects p ON p.workspace_id = w.id AND p.archived_at IS NULL
           GROUP BY w.id"""
    )
    return {row["id"]: row["total"] for row in rows}
