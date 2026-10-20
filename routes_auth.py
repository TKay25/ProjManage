"""Registration, login and logout."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import auth
from db import execute, new_id, now_iso, query
from whatsapp import normalize_phone

bp = Blueprint("auth", __name__)

AVATAR_COLORS = ["#0F5D46", "#C8963E", "#2A7A5E", "#A9573C", "#3E6B8A", "#6B5B95"]
ATTEMPTS = {}
MAX_ATTEMPTS = 8
WINDOW = timedelta(minutes=15)
MAX_TRACKED_KEYS = 5000


def _prune_attempts(now: datetime):
    """Keeps the in-memory throttle bounded; each worker has its own map."""
    if len(ATTEMPTS) < MAX_TRACKED_KEYS:
        return
    for key, entry in list(ATTEMPTS.items()):
        if now - entry["start"] > WINDOW:
            del ATTEMPTS[key]


def _is_blocked(key: str) -> bool:
    """Only failed attempts are recorded, so a legitimate sign-in never counts."""
    now = datetime.now(timezone.utc)
    entry = ATTEMPTS.get(key)
    if not entry:
        return False
    if now - entry["start"] > WINDOW:
        del ATTEMPTS[key]
        return False
    return entry["count"] >= MAX_ATTEMPTS


def _register_failure(key: str):
    now = datetime.now(timezone.utc)
    _prune_attempts(now)

    entry = ATTEMPTS.get(key)
    if not entry or now - entry["start"] > WINDOW:
        ATTEMPTS[key] = {"start": now, "count": 1}
    else:
        entry["count"] += 1


def _clear_attempts(key: str):
    ATTEMPTS.pop(key, None)


def _colour_for(email: str) -> str:
    return AVATAR_COLORS[sum(ord(char) for char in email) % len(AVATAR_COLORS)]


@bp.get("/login")
def login():
    if g.user:
        return redirect(url_for("dashboard.index"))
    return render_template(
        "auth/login.html",
        title="Welcome back",
        email="",
        error=None,
        next=auth.safe_next(request.args.get("next", "")),
    )


@bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    next_url = auth.safe_next(request.form.get("next", ""))
    throttle_key = f"{request.remote_addr}:{email}"

    if _is_blocked(throttle_key):
        return (
            render_template(
                "auth/login.html",
                title="Welcome back",
                email=email,
                error="Too many attempts. Wait 15 minutes and try again.",
                next=next_url,
            ),
            429,
        )

    user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

    if not user or not auth.verify_password(password, user["password_hash"]):
        _register_failure(throttle_key)
        return (
            render_template(
                "auth/login.html",
                title="Welcome back",
                email=email,
                error="That email and password do not match.",
                next=next_url,
            ),
            401,
        )

    _clear_attempts(throttle_key)
    auth.login_user(user["id"])
    flash(f"Welcome back, {user['name'].split()[0]}.", "success")
    return redirect(next_url)


@bp.get("/register")
def register():
    if g.user:
        return redirect(url_for("dashboard.index"))
    return render_template("auth/register.html", title="Create your account", values={}, error=None)


@bp.post("/register")
def register_post():
    values = {
        "name": (request.form.get("name") or "").strip(),
        "email": (request.form.get("email") or "").strip().lower(),
        "phone": (request.form.get("phone") or "").strip(),
        "country": request.form.get("country") or "Zimbabwe",
        "role": request.form.get("role") or "client",
    }
    password = request.form.get("password") or ""
    error = None

    if not values["name"] or len(values["name"]) > 90:
        error = "Enter your full name."
    elif "@" not in values["email"] or "." not in values["email"].split("@")[-1]:
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif request.form.get("terms") != "yes":
        error = "Please confirm you understand what Vaka is."
    elif query("SELECT id FROM users WHERE email = ?", (values["email"],), one=True):
        error = "An account with that email already exists."

    if error:
        return render_template("auth/register.html", title="Create your account", values=values, error=error), 400

    user_id = new_id()
    role = "manager" if values["role"] == "manager" else "client"

    execute(
        """INSERT INTO users (id, name, email, password_hash, role, phone, country, avatar_color, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            values["name"],
            values["email"],
            auth.hash_password(password),
            role,
            normalize_phone(values["phone"]) or None,
            values["country"][:80],
            _colour_for(values["email"]),
            now_iso(),
        ),
    )

    auth.login_user(user_id)
    flash("Welcome to Vaka. Create your first project to get started.", "success")
    return redirect(url_for("projects.new"))


@bp.post("/logout")
def logout():
    auth.logout_user()
    flash("You have signed out.", "success")
    return redirect(url_for("public.landing"))
