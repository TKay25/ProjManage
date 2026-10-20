"""Project list, creation, detail and stage tracking."""

from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from auth import accessible_projects, can_manage_project, login_required, require_project
from db import execute, log_event, new_id, now_iso, query, touch_project
from money import format_money, parse_money_to_cents
from queries import (
    latest_activity,
    money_totals,
    next_stage,
    projects_with_summary,
    recent_transactions,
    stage_rows,
    stage_spend,
)
from stages import STAGE_GROUPS, STAGES, project_progress, stage_by_key, stage_budget
from storage import UploadError, save_upload

bp = Blueprint("projects", __name__)


def _next_code() -> str:
    count = query("SELECT COUNT(*) AS count FROM projects", one=True)["count"]
    return f"VK-{datetime.now():%y}{count + 1:02d}"


@bp.get("/app/projects")
@login_required
def index():
    projects = projects_with_summary(accessible_projects(g.user))
    return render_template("app/projects.html", title="Projects", active="projects", projects=projects)


@bp.get("/app/projects/new")
@login_required
def new():
    return render_template(
        "app/project_new.html",
        title="New project",
        active="projects",
        values={},
        error=None,
    )


@bp.post("/app/projects")
@login_required
def create():
    values = {
        "name": (request.form.get("name") or "").strip(),
        "city": (request.form.get("city") or "Harare").strip(),
        "suburb": (request.form.get("suburb") or "").strip(),
        "stand_number": (request.form.get("stand_number") or "").strip(),
        "description": (request.form.get("description") or "").strip(),
        "budget": (request.form.get("budget") or "").strip(),
        "start_date": (request.form.get("start_date") or "").strip(),
        "target_date": (request.form.get("target_date") or "").strip(),
    }

    budget_cents = parse_money_to_cents(values["budget"])
    error = None

    if len(values["name"]) < 3:
        error = "Give the project a name of at least 3 characters."
    elif budget_cents < 10000:
        error = "Enter a build budget of at least $100."

    if error:
        return render_template("app/project_new.html", title="New project", active="projects", values=values, error=error), 400

    project_id = new_id()
    manager_id = g.user["id"] if g.user["role"] == "manager" else None

    execute(
        """INSERT INTO projects
             (id, code, name, description, owner_id, manager_id, city, suburb, stand_number, status, budget_cents, start_date, target_date, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planning', ?, ?, ?, ?, ?)""",
        (
            project_id,
            _next_code(),
            values["name"][:120],
            values["description"][:2000] or None,
            g.user["id"],
            manager_id,
            values["city"][:80] or "Harare",
            values["suburb"][:80] or None,
            values["stand_number"][:80] or None,
            budget_cents,
            values["start_date"] or None,
            values["target_date"] or None,
            now_iso(),
            now_iso(),
        ),
    )

    for index, stage in enumerate(STAGES):
        execute(
            """INSERT INTO stages
                 (id, project_id, key, name, position, status, budget_cents, notes, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL, NULL, NULL)""",
            (
                new_id(),
                project_id,
                stage["key"],
                stage["name"],
                index + 1,
                stage_budget(stage["weight"], budget_cents),
            ),
        )

    log_event(g.user["id"], project_id, "project.created", f"Project {values['name']} created")
    flash("Project created. Vaka has added the full Zimbabwe stage plan.", "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.get("/app/projects/<project_id>")
@login_required
def detail(project_id):
    project = require_project(project_id)
    stages = stage_rows(project_id)
    spend = stage_spend(project_id)
    totals = money_totals(project_id)
    current = next_stage(stages)

    groups = []
    for group in STAGE_GROUPS:
        items = []
        for stage in stages:
            definition = stage_by_key(stage["key"])
            if not definition or definition["group"] != group:
                continue
            spent = spend.get(stage["key"], 0)
            items.append(
                {
                    **stage,
                    "definition": definition,
                    "spent": spent,
                    "variance": stage["budget_cents"] - spent,
                    "over": spent > stage["budget_cents"] > 0,
                }
            )
        groups.append({"name": group, "stages": items})

    owner = query("SELECT * FROM users WHERE id = ?", (project["owner_id"],), one=True)
    manager = (
        query("SELECT * FROM users WHERE id = ?", (project["manager_id"],), one=True)
        if project["manager_id"]
        else None
    )

    agreements = query(
        "SELECT * FROM agreements WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
    )
    attachments = query(
        "SELECT a.*, u.name AS uploader_name FROM attachments a LEFT JOIN users u ON u.id = a.uploader_id "
        "WHERE a.project_id = ? ORDER BY a.created_at DESC LIMIT 8",
        (project_id,),
    )

    return render_template(
        "app/project_detail.html",
        title=project["name"],
        active="projects",
        projects=accessible_projects(g.user),
        project=project,
        owner=owner,
        manager=manager,
        stages=stages,
        groups=groups,
        totals=totals,
        current=current,
        current_definition=stage_by_key(current["key"]) if current else None,
        transactions=recent_transactions(project_id, 5),
        agreements=agreements,
        attachments=attachments,
        activity=latest_activity(project_id, 5),
        completed_count=len([stage for stage in stages if stage["status"] == "complete"]),
        progress=project_progress(stages),
        spend=spend,
    )


@bp.post("/app/projects/<project_id>/stages/<stage_key>")
@login_required
def update_stage(project_id, stage_key):
    project = require_project(project_id)
    stage = query(
        "SELECT * FROM stages WHERE project_id = ? AND key = ?", (project_id, stage_key), one=True
    )
    if not stage:
        abort(404)

    status = request.form.get("status") or ""
    notes = (request.form.get("notes") or "").strip()[:1000]

    if status not in {"pending", "in_progress", "complete", "blocked"}:
        flash("Choose a valid stage status.", "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    started_at = stage["started_at"]
    completed_at = stage["completed_at"]
    stamp = now_iso()

    if status == "in_progress" and not started_at:
        started_at = stamp
    if status == "complete":
        started_at = started_at or stamp
        completed_at = stamp
    if status in {"pending", "blocked"}:
        completed_at = None

    execute(
        "UPDATE stages SET status = ?, notes = ?, started_at = ?, completed_at = ? WHERE id = ?",
        (status, notes or stage["notes"], started_at, completed_at, stage["id"]),
    )
    touch_project(project_id)

    if status == "complete":
        log_event(g.user["id"], project_id, "stage.completed", f"{stage['name']} marked complete")
        flash(f"{stage['name']} marked complete.", "success")
    elif status == "blocked":
        log_event(g.user["id"], project_id, "stage.blocked", f"{stage['name']} blocked: {notes or 'no reason given'}")
        flash(f"{stage['name']} is flagged as blocked.", "error")
    else:
        log_event(g.user["id"], project_id, "stage.updated", f"{stage['name']} set to {status.replace('_', ' ')}")
        flash(f"{stage['name']} updated.", "success")

    if project["status"] == "planning" and status in {"in_progress", "complete"}:
        execute("UPDATE projects SET status = 'in_progress' WHERE id = ?", (project_id,))

    return redirect(f"{url_for('projects.detail', project_id=project_id)}#stage-{stage_key}")


@bp.post("/app/projects/<project_id>/status")
@login_required
def update_status(project_id):
    require_project(project_id)
    status = request.form.get("status") or ""

    if status not in {"planning", "in_progress", "on_hold", "completed"}:
        flash("Choose a valid project status.", "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    execute("UPDATE projects SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), project_id))
    log_event(g.user["id"], project_id, "project.status", f"Project status set to {status.replace('_', ' ')}")
    flash("Project status updated.", "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/app/projects/<project_id>/manager")
@login_required
def assign_manager(project_id):
    project = require_project(project_id)

    if project["owner_id"] != g.user["id"] and g.user["role"] != "admin":
        abort(403)

    email = (request.form.get("email") or "").strip().lower()
    manager = query("SELECT * FROM users WHERE email = ? AND role IN ('manager', 'admin')", (email,), one=True)

    if not manager:
        flash("No build manager account matches that email. Ask them to register first.", "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    execute("UPDATE projects SET manager_id = ?, updated_at = ? WHERE id = ?", (manager["id"], now_iso(), project_id))
    log_event(g.user["id"], project_id, "project.manager", f"{manager['name']} assigned as build manager")
    flash(f"{manager['name']} is now the build manager on this project.", "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/app/projects/<project_id>/budget")
@login_required
def update_budget(project_id):
    project = require_project(project_id)
    budget_cents = parse_money_to_cents(request.form.get("budget"))

    if budget_cents < 10000:
        flash("Enter a budget of at least $100.", "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    execute("UPDATE projects SET budget_cents = ?, updated_at = ? WHERE id = ?", (budget_cents, now_iso(), project_id))
    for stage in STAGES:
        execute(
            "UPDATE stages SET budget_cents = ? WHERE project_id = ? AND key = ?",
            (stage_budget(stage["weight"], budget_cents), project_id, stage["key"]),
        )

    log_event(g.user["id"], project_id, "project.budget", f"Budget set to {format_money(budget_cents)}")
    flash("Budget updated and stage allocations recalculated.", "success")
    return redirect(url_for("projects.detail", project_id=project_id))
