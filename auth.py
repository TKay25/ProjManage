"""Authentication, sessions and access control."""

import hmac
import secrets
from functools import wraps

from flask import abort, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import query

CSRF_EXEMPT_ENDPOINTS = {
    "whatsapp.webhook",
    "public.health",
}


def init_app(app):
    app.before_request(load_user)
    app.before_request(verify_csrf)


def load_user():
    user_id = session.get("uid")
    g.user = (
        query(
            """SELECT id, name, email, role, phone, country, avatar_color, created_at
               FROM users WHERE id = ?""",
            (user_id,),
            one=True,
        )
        if user_id
        else None
    )


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
    session.clear()
    session["uid"] = user_id
    session.permanent = True
    session["csrf"] = secrets.token_urlsafe(32)


def logout_user():
    session.clear()


def can_manage_project(user, project) -> bool:
    if not user or not project:
        return False
    return user["role"] == "admin" or project["owner_id"] == user["id"] or project["manager_id"] == user["id"]


def accessible_projects(user):
    if not user:
        return []
    if user["role"] == "admin":
        return query("SELECT * FROM projects ORDER BY created_at DESC")
    return query(
        """SELECT * FROM projects
           WHERE owner_id = ? OR manager_id = ?
           ORDER BY created_at DESC""",
        (user["id"], user["id"]),
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
    target = value if isinstance(value, str) else ""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return fallback
