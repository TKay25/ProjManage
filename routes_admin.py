"""Vaka staff portal — every client and manager workspace in one place."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import web
from auth import admin_required
from db import execute, log_event, new_id, now_iso, query
from money import format_money
from paging import offset, page_number, page_window
from queries import (
    all_projects_with_people,
    count_events,
    people_overview,
    platform_totals,
    recent_events,
)
from stages import STAGE_GROUPS, stage_by_key

bp = Blueprint("admin", __name__, url_prefix="/admin")

ROLES = {"client": "Client", "manager": "Build manager", "admin": "Vaka staff"}
PAGE_SIZE = 30


@bp.get("")
@admin_required
def overview():
    projects = all_projects_with_people()
    totals = platform_totals()
    people = people_overview()
    events = recent_events(12)

    attention = []
    for project in projects:
        if project["balance"] < 0:
            attention.append(
                {
                    "tone": "danger",
                    "icon": "alert",
                    "title": f"{project['name']} is over-funded",
                    "body": f"Spent {format_money(abs(project['balance']))} more than received.",
                    "href": url_for("admin.project", project_id=project["id"]),
                }
            )
        if project["blocked_stages"]:
            attention.append(
                {
                    "tone": "warn",
                    "icon": "clock",
                    "title": f"{project['blocked_stages']} blocked stage(s) on {project['name']}",
                    "body": "A statutory gate or site issue is holding the build.",
                    "href": url_for("admin.project", project_id=project["id"]),
                }
            )
        if project["missing_receipts"]:
            attention.append(
                {
                    "tone": "warn",
                    "icon": "receipt",
                    "title": f"{project['missing_receipts']} expense(s) without a receipt",
                    "body": f"{project['name']} · chase the build manager.",
                    "href": url_for("admin.project", project_id=project["id"]),
                }
            )
        if not project["manager_id"]:
            attention.append(
                {
                    "tone": "info",
                    "icon": "users",
                    "title": f"{project['name']} has no build manager",
                    "body": "Assign someone so expenses and receipts get posted.",
                    "href": url_for("admin.project", project_id=project["id"]),
                }
            )

    return render_template(
        "admin/overview.html",
        title="Staff overview",
        active="admin",
        admin_active="overview",
        projects=projects,
        totals=totals,
        people=people,
        events=events,
        attention=attention[:6],
        counts={
            "projects": len(projects),
            "clients": len([p for p in people if p["role"] == "client"]),
            "managers": len([p for p in people if p["role"] == "manager"]),
            "staff": len([p for p in people if p["role"] == "admin"]),
            "blocked": sum(project["blocked_stages"] for project in projects),
            "missing": sum(project["missing_receipts"] for project in projects),
        },
    )


@bp.get("/projects")
@admin_required
def projects():
    rows = all_projects_with_people()
    status = request.args.get("status", "")
    search = (request.args.get("q") or "").strip().lower()

    if status:
        rows = [row for row in rows if row["status"] == status]
    if search:
        rows = [
            row
            for row in rows
            if search in row["name"].lower()
            or search in (row["code"] or "").lower()
            or search in (row["owner_name"] or "").lower()
            or search in (row["manager_name"] or "").lower()
        ]

    filtered = rows
    total_rows = len(filtered)
    page, page_count = page_window(page_number(), total_rows, PAGE_SIZE)
    start = offset(page, PAGE_SIZE)

    return render_template(
        "admin/projects.html",
        title="All projects",
        active="admin",
        admin_active="projects",
        projects=rows[start : start + PAGE_SIZE],
        status=status,
        search=search,
        total_rows=total_rows,
        page=page,
        page_count=page_count,
        pager_endpoint="admin.projects",
        pager_args={"status": status, "q": search},
        total_funded=sum(row["funded"] for row in filtered),
        total_spent=sum(row["spent"] for row in filtered),
    )


@bp.get("/projects/<project_id>")
@admin_required
def project(project_id):
    exists = query("SELECT id FROM projects WHERE id = ?", (project_id,), one=True)
    if not exists:
        abort(404)
    # Staff get the full project workspace, which their role already permits.
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.get("/people")
@admin_required
def people():
    rows = people_overview()
    return render_template(
        "admin/people.html",
        title="People",
        active="admin",
        admin_active="people",
        people=rows,
        roles=ROLES,
        counts={
            "clients": len([p for p in rows if p["role"] == "client"]),
            "managers": len([p for p in rows if p["role"] == "manager"]),
            "staff": len([p for p in rows if p["role"] == "admin"]),
        },
    )


@bp.post("/people/<user_id>/role")
@admin_required
def update_role(user_id):
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        abort(404)

    role = request.form.get("role") or ""
    if role not in ROLES:
        message = "Choose a valid role."
        if web.wants_json():
            return web.fail(message)
        flash(message, "error")
        return redirect(url_for("admin.people"))

    if user["id"] == g.user["id"]:
        message = "You cannot change your own role."
        if web.wants_json():
            return web.fail(message)
        flash(message, "error")
        return redirect(url_for("admin.people"))

    execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    log_event(g.user["id"], None, "user.role", f"{user['name']} set to {ROLES[role]}")

    message = f"{user['name']} is now a {ROLES[role].lower()}."
    if web.wants_json():
        return web.ok(message, fields={f"[data-role-badge='{user_id}']": ROLES[role]})

    flash(message, "success")
    return redirect(url_for("admin.people"))


@bp.post("/people/invite")
@admin_required
def invite_staff():
    """Create a Vaka staff or manager account on a client's behalf."""
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    role = request.form.get("role") or "manager"

    import auth

    message = None
    if len(name) < 2:
        message = "Enter the person's full name."
    elif "@" not in email:
        message = "Enter a valid email address."
    elif len(password) < 8:
        message = "Set a temporary password of at least 8 characters."
    elif role not in ROLES:
        message = "Choose a valid role."
    elif query("SELECT id FROM users WHERE email = ?", (email,), one=True):
        message = "An account with that email already exists."

    if message:
        if web.wants_json():
            return web.fail(message)
        flash(message, "error")
        return redirect(url_for("admin.people"))

    execute(
        """INSERT INTO users (id, name, email, password_hash, role, phone, country, avatar_color, created_at)
           VALUES (?, ?, ?, ?, ?, NULL, 'Zimbabwe', '#0F5D46', ?)""",
        (new_id(), name[:90], email, auth.hash_password(password), role, now_iso()),
    )
    log_event(g.user["id"], None, "user.created", f"{name} created as {ROLES[role]}")

    created = f"Account created for {name}. Share the temporary password securely."
    if web.wants_json():
        return web.ok(created, reload=True)

    flash(created, "success")
    return redirect(url_for("admin.people"))


@bp.get("/activity")
@admin_required
def activity():
    search = (request.args.get("q") or "").strip()
    total_rows = count_events(search)
    page, page_count = page_window(page_number(), total_rows, PAGE_SIZE)
    events = recent_events(PAGE_SIZE, offset(page, PAGE_SIZE), search)
    return render_template(
        "admin/activity.html",
        title="Activity log",
        active="admin",
        admin_active="activity",
        events=events,
        search=search,
        total_rows=total_rows,
        page=page,
        page_count=page_count,
        pager_endpoint="admin.activity",
        pager_args={"q": search},
    )


@bp.get("/stages")
@admin_required
def stages():
    """Reference view of the Zimbabwe stage plan staff can quote from."""
    return render_template(
        "admin/stages.html",
        title="Stage reference",
        active="admin",
        admin_active="stages",
        groups=STAGE_GROUPS,
        stage_by_key=stage_by_key,
    )
