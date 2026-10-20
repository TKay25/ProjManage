"""Profile, security and workspace settings."""

import re

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import auth
from auth import accessible_projects, login_required
from db import execute, query
from whatsapp import display_phone, normalize_phone

bp = Blueprint("settings", __name__)


@bp.get("/app/settings")
@login_required
def index():
    projects = accessible_projects(g.user)
    contacts = query(
        "SELECT * FROM whatsapp_contacts WHERE user_id = ? ORDER BY created_at DESC", (g.user["id"],)
    )
    counts = {
        "projects": len(projects),
        "managed": len([project for project in projects if project["manager_id"] == g.user["id"]]),
        "expenses": query(
            "SELECT COUNT(*) AS count FROM transactions WHERE created_by = ?", (g.user["id"],), one=True
        )["count"],
    }

    return render_template(
        "app/settings.html",
        title="Settings",
        active="settings",
        projects=projects,
        contacts=contacts,
        counts=counts,
        display_phone=display_phone,
    )


@bp.post("/app/settings/profile")
@login_required
def update_profile():
    name = (request.form.get("name") or "").strip()
    phone = normalize_phone(request.form.get("phone") or "")
    country = (request.form.get("country") or "").strip()
    colour = (request.form.get("avatar_color") or "").strip()

    if len(name) < 2:
        flash("Enter your full name.", "error")
        return redirect(url_for("settings.index"))

    if colour and not re.match(r"^#[0-9A-Fa-f]{6}$", colour):
        colour = g.user["avatar_color"]

    execute(
        "UPDATE users SET name = ?, phone = ?, country = ?, avatar_color = ? WHERE id = ?",
        (name[:90], phone or None, country[:80] or None, colour, g.user["id"]),
    )

    if phone:
        execute("UPDATE whatsapp_contacts SET user_id = ? WHERE phone = ?", (g.user["id"], phone))

    flash("Profile updated.", "success")
    return redirect(url_for("settings.index"))


@bp.post("/app/settings/password")
@login_required
def update_password():
    current = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""

    user = query("SELECT * FROM users WHERE id = ?", (g.user["id"],), one=True)

    if not auth.verify_password(current, user["password_hash"]):
        flash("Your current password is not correct.", "error")
    elif len(new_password) < 8:
        flash("The new password must be at least 8 characters.", "error")
    elif new_password != confirm:
        flash("The new passwords do not match.", "error")
    else:
        execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (auth.hash_password(new_password), g.user["id"]),
        )
        flash("Password changed.", "success")

    return redirect(url_for("settings.index"))
