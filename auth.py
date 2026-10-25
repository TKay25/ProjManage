"""Authentication, sessions and access control."""

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import execute, log_event, query

CSRF_EXEMPT_ENDPOINTS = {
    # Server-to-server calls that carry their own shared secret instead of a
    # browser session: Meta's webhook and the digest scheduler.
    "whatsapp.webhook",
    "digest.digest",
    "notifications.dispatch",
    "public.health",
}

# Paths a post-login redirect must never target: landing back on one of these
# looks like the sign-in itself failed.
AUTH_PATHS = (
    "/login",
    "/logout",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/two-factor",
)


def init_app(app):
    app.before_request(load_user)
    app.before_request(verify_csrf)


def load_user():
    user_id = session.get("uid")
    g.user = None
    if not user_id:
        return

    user = query(
        """SELECT id, name, email, role, phone, country, avatar_color,
                  density, page_size, session_epoch, onboarded_at,
                  totp_enabled, palette, created_at
           FROM users WHERE id = ?""",
        (user_id,),
        one=True,
    )
    if not user:
        session.clear()
        return

    # A password change bumps the epoch, which retires every older cookie —
    # including one an attacker already copied.
    current_epoch = int(user["session_epoch"] or 0)
    expected = session.get("epoch")
    if expected is None:
        session["epoch"] = current_epoch
    elif int(expected) != current_epoch:
        session.clear()
        return

    g.user = user


def csrf_token() -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def verify_csrf():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
        return

    expected = session.get("csrf")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")

    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, "Your form session expired. Refresh the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """YaVaKa staff only — the admin portal manages every workspace."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def login_user(user_id: str):
    row = query("SELECT session_epoch FROM users WHERE id = ?", (user_id,), one=True)
    session.clear()
    session["uid"] = user_id
    session.permanent = True
    session["csrf"] = secrets.token_urlsafe(32)
    session["epoch"] = int((row["session_epoch"] if row else 0) or 0)


def logout_user():
    session.clear()


def bump_session_epoch(user_id: str):
    """Signs this person out everywhere, then re-seats the current browser."""
    execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (user_id,))
    row = query("SELECT session_epoch FROM users WHERE id = ?", (user_id,), one=True)
    if session.get("uid") == user_id:
        session["epoch"] = int((row["session_epoch"] if row else 0) or 0)


def audit_auth(action: str, detail: str = "", user_id=None):
    """Records a security event. These have no project, so they never fan out."""
    actor = user_id or (g.user["id"] if getattr(g, "user", None) else None)
    try:
        log_event(actor, None, action, str(detail or "")[:200])
    except Exception:  # noqa: BLE001 - auditing must never break a sign-in
        current_app.logger.exception("Could not record %s", action)


THROTTLE_WINDOW = timedelta(minutes=15)


def _window_expired(stamp: str) -> bool:
    try:
        started = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - started > THROTTLE_WINDOW


def _sweep_throttle():
    """Cheap opportunistic cleanup so the table cannot grow without bound."""
    if secrets.randbelow(50):
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="microseconds")
    execute("DELETE FROM auth_throttle WHERE window_start < ?", (cutoff,))


def throttle_blocked(key: str, limit: int) -> bool:
    row = query(
        "SELECT window_start, count FROM auth_throttle WHERE key = ?", (key,), one=True
    )
    if not row:
        return False
    if _window_expired(row["window_start"]):
        execute("DELETE FROM auth_throttle WHERE key = ?", (key,))
        return False
    return int(row["count"] or 0) >= limit


def throttle_failure(key: str):
    """Counts one failed attempt. Shared by every worker, so the cap holds."""
    _sweep_throttle()
    row = query(
        "SELECT window_start FROM auth_throttle WHERE key = ?", (key,), one=True
    )
    if row and not _window_expired(row["window_start"]):
        execute("UPDATE auth_throttle SET count = count + 1 WHERE key = ?", (key,))
        return

    execute("DELETE FROM auth_throttle WHERE key = ?", (key,))
    execute(
        "INSERT INTO auth_throttle (key, window_start, count) VALUES (?, ?, 1)",
        (key, datetime.now(timezone.utc).isoformat(timespec="microseconds")),
    )


def throttle_clear(key: str):
    execute("DELETE FROM auth_throttle WHERE key = ?", (key,))


def can_manage_project(user, project) -> bool:
    if not user or not project:
        return False
    if user["role"] == "admin" or project["owner_id"] == user["id"] or project["manager_id"] == user["id"]:
        return True
    # A manager linked to the client runs every build that client owns.
    return bool(
        query(
            "SELECT id FROM manager_links WHERE client_id = ? AND manager_id = ?",
            (project["owner_id"], user["id"]),
            one=True,
        )
    )


MANAGER_ROLES = {"manager", "admin"}


def self_managed(user) -> bool:
    """A client who runs their own build.

    True when the account is a client and nobody else manages their builds: no
    assigned build manager, no linked manager, and no manager activity recorded
    against their projects. A client with nothing filed yet counts as running
    their own build, because they are the only one who could start it.
    """
    if not user or user["role"] != "client":
        return False

    cached = getattr(g, "_self_managed", None)
    if cached is not None:
        return cached

    managed = query(
        """SELECT COUNT(*) AS total FROM projects
           WHERE owner_id = ? AND manager_id IS NOT NULL AND manager_id <> owner_id""",
        (user["id"],),
        one=True,
    )
    linked = query(
        "SELECT COUNT(*) AS total FROM manager_links WHERE client_id = ?",
        (user["id"],),
        one=True,
    )
    worked = query(
        """SELECT COUNT(*) AS total FROM audit_events e
           JOIN projects p ON p.id = e.project_id
           WHERE p.owner_id = ? AND e.user_id IS NOT NULL AND e.user_id <> ?""",
        (user["id"], user["id"]),
        one=True,
    )

    value = not (managed["total"] or linked["total"] or worked["total"])
    g._self_managed = value
    return value


def runs_build(user) -> bool:
    """True when this account does the build work itself.

    Build managers and staff always do. A client does when they own their
    projects outright, because there is no manager to record money or upload
    proof for them.
    """
    if not user:
        return False
    return user["role"] in MANAGER_ROLES or self_managed(user)


def accessible_projects(user):
    """Projects this account may see. Memoised for the life of one request.

    Pages and the sidebar both need the list; caching it keeps that to a single
    query and stops a template from rendering a misleading empty sidebar just
    because its view forgot to pass the list through.
    """
    if not user:
        return []

    cached = getattr(g, "_accessible_projects", None)
    if cached is not None:
        return cached

    if user["role"] == "admin":
        projects = query("SELECT * FROM projects WHERE archived_at IS NULL ORDER BY created_at DESC")
    else:
        projects = query(
            """SELECT * FROM projects
               WHERE archived_at IS NULL
                 AND (owner_id = ?
                      OR manager_id = ?
                      OR owner_id IN (SELECT client_id FROM manager_links WHERE manager_id = ?))
               ORDER BY created_at DESC""",
            (user["id"], user["id"], user["id"]),
        )

    g._accessible_projects = projects
    return projects


def archived_projects(user):
    """Archived projects stay reachable for their record, just not in the lists."""
    if not user:
        return []
    if user["role"] == "admin":
        return query("SELECT * FROM projects WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")
    return query(
        """SELECT * FROM projects
           WHERE archived_at IS NOT NULL
             AND (owner_id = ?
                  OR manager_id = ?
                  OR owner_id IN (SELECT client_id FROM manager_links WHERE manager_id = ?))
           ORDER BY archived_at DESC""",
        (user["id"], user["id"], user["id"]),
    )


def require_project(project_id: str):
    """Loads a project the current user may access, or aborts 404."""
    project = query("SELECT * FROM projects WHERE id = ?", (project_id,), one=True)
    if not project or not can_manage_project(g.user, project):
        abort(404)
    return project


def initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0].upper() for part in parts[:2])


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def safe_next(value, fallback="/app"):
    """Where to send someone after signing in.

    Auth endpoints are refused: a `next` of /login would sign a person in and
    then bounce them straight back to the sign-in page, which reads as the
    login having failed.
    """
    target = value if isinstance(value, str) else ""
    if not target.startswith("/") or target.startswith("//"):
        return fallback

    path = target.split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()
    for blocked in AUTH_PATHS:
        if path == blocked or path.startswith(blocked + "/"):
            return fallback
    return target
