"""Project list, creation, detail and stage tracking."""

import re
from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import project_kinds
import updates
import web
from auth import accessible_projects, archived_projects, login_required, require_project
from db import execute, log_event, new_id, now_iso, query, touch_project
from workspaces import workspaces_for
from money import format_money, parse_money_to_cents
from notifications import queue_manager_update
from paging import offset, page_number, page_window
from queries import (
    attachments_by_stage,
    latest_activity,
    money_totals,
    next_stage,
    projects_with_summary,
    recent_transactions,
    stage_rows,
    stage_spend,
)
from stages import (
    STAGE_GROUPS,
    STAGES,
    allocate_budgets,
    project_progress,
    selected_stages,
    stage_by_key,
    stage_budget,
)
from whatsapp import display_phone, normalize_phone
from workspaces import create_workspace, ensure_default_workspace, find_workspace, workspaces_for
import team

bp = Blueprint("projects", __name__)

PAGE_SIZE = 12

PROJECT_STATUSES = {"planning", "in_progress", "on_hold", "completed"}

# Project codes carry the company initials: YVK-2601, YVK-2602, ...
PROJECT_CODE_PREFIX = "YVK"


def _next_code() -> str:
    """Sequential project number: YVK-0001, YVK-0002, ... YVK-9999.

    Derived from the highest existing number rather than a row count, so
    deleting a project never hands out a code that is already in use.
    """
    rows = query("SELECT code FROM projects")
    highest = 0
    for row in rows:
        match = re.search(r"(\d+)\s*$", row["code"] or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{PROJECT_CODE_PREFIX}-{highest + 1:04d}"


@bp.get("/app/projects")
@login_required
def index():
    status = request.args.get("status", "all")
    archived = request.args.get("archived") == "1" or status == "archived"
    if status == "archived":
        status = "all"

    workspace = find_workspace(g.user, request.args.get("workspace"))
    source = archived_projects(g.user) if archived else accessible_projects(g.user)
    if workspace:
        source = [row for row in source if row["workspace_id"] == workspace["id"]]
    projects = projects_with_summary(source)
    search = (request.args.get("q") or "").strip()

    if status != "all":
        projects = [row for row in projects if row["status"] == status]

    if search:
        needle = search.lower()
        projects = [
            row
            for row in projects
            if needle in (row["name"] or "").lower()
            or needle in (row["code"] or "").lower()
            or needle in (row["suburb"] or "").lower()
        ]

    total_rows = len(projects)
    page, page_count = page_window(page_number(), total_rows, PAGE_SIZE)
    start = offset(page, PAGE_SIZE)
    visible = projects[start : start + PAGE_SIZE]

    return render_template(
        "app/projects.html",
        title="Projects",
        active="projects",
        projects=visible,
        search=search,
        status=status,
        archived=archived,
        workspace=workspace,
        workspaces=workspaces_for(g.user),
        total_rows=total_rows,
        page=page,
        page_count=page_count,
        pager_endpoint="projects.index",
        pager_args={"q": search, "status": status},
    )


@bp.get("/app/projects/new")
@login_required
def new():
    return render_template(
        "app/project_new.html",
        title="New project",
        active="projects",
        values={},
        kinds=project_kinds.PROJECT_KINDS,
        error=None,
    )


def _read_project_form():
    return {
        "name": (request.form.get("name") or "").strip(),
        "kind": (request.form.get("kind") or project_kinds.DEFAULT_KIND).strip(),
        "city": (request.form.get("city") or "Harare").strip(),
        "suburb": (request.form.get("suburb") or "").strip(),
        "stand_number": (request.form.get("stand_number") or "").strip(),
        "description": (request.form.get("description") or "").strip(),
        "budget": (request.form.get("budget") or "").strip(),
        "start_date": (request.form.get("start_date") or "").strip(),
        "target_date": (request.form.get("target_date") or "").strip(),
        "status": (request.form.get("status") or "").strip(),
        "client_email": (request.form.get("client_email") or "").strip().lower(),
        "client_whatsapp": (request.form.get("client_whatsapp") or "").strip(),
    }


def _validate_project(values):
    budget_cents = parse_money_to_cents(values["budget"])
    client_email = values["client_email"]
    client_whatsapp = normalize_phone(values["client_whatsapp"])
    error = None

    if len(values["name"]) < 3:
        error = "Give the project a name of at least 3 characters."
    elif not project_kinds.is_valid(values.get("kind")):
        error = "Choose the kind of work this project covers."
    elif client_email and ("@" not in client_email or "." not in client_email.split("@")[-1]):
        error = "Enter a valid client email address."
    elif values["client_whatsapp"] and len(client_whatsapp) < 9:
        error = "Enter a valid client WhatsApp number."
    elif budget_cents < 10000:
        error = "Enter a build budget of at least $100."

    return budget_cents, error


@bp.post("/app/projects")
@login_required
def create():
    values = _read_project_form()
    budget_cents, error = _validate_project(values)

    if error:
        if web.wants_json():
            return web.fail(error)
        return render_template("app/project_new.html", title="New project", active="projects", values=values, kinds=project_kinds.PROJECT_KINDS, error=error), 400

    # Only a build manager (or staff) can file a build for somebody else. A
    # client creating their own project never sets a client contact, whatever
    # the form posts.
    manages_for_others = g.user["role"] in {"manager", "admin"}
    if not manages_for_others:
        values["client_email"] = ""
        values["client_whatsapp"] = ""

    project_id = new_id()
    owner_id = g.user["id"]
    manager_id = g.user["id"] if g.user["role"] == "manager" else None
    client_account = None

    if manages_for_others and values["client_email"]:
        client_account = query(
            "SELECT id, name FROM users WHERE email = ? AND role = 'client'",
            (values["client_email"],),
            one=True,
        )

    if client_account:
        # The build belongs to the client; the manager stays on it as the person
        # running the work, and the two are linked from the start.
        owner_id = client_account["id"]
        team.link(owner_id, g.user["id"], created_by=g.user["id"])
        manager_id = g.user["id"] if g.user["role"] == "manager" else manager_id

    workspace = find_workspace(g.user, request.form.get("workspace_id")) or ensure_default_workspace(g.user)

    execute(
        """INSERT INTO projects
             (id, code, name, description, owner_id, manager_id, city, suburb, stand_number,
              client_email, client_whatsapp, kind, status, budget_cents, start_date, target_date,
              workspace_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'planning', ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            _next_code(),
            values["name"][:120],
            values["description"][:2000] or None,
            owner_id,
            manager_id,
            values["city"][:80] or "Harare",
            values["suburb"][:80] or None,
            values["stand_number"][:80] or None,
            values["client_email"][:120] or None,
            normalize_phone(values["client_whatsapp"]) or None,
            values["kind"],
            budget_cents,
            values["start_date"] or None,
            values["target_date"] or None,
            workspace["id"] if workspace else None,
            now_iso(),
            now_iso(),
        ),
    )

    chosen = selected_stages(request.form.getlist("stage_keys"))
    if not chosen:
        # No choice made (or JavaScript off): use the plan this kind of work
        # normally needs, rather than the whole house sequence.
        chosen = selected_stages(project_kinds.default_stages(values["kind"]))
    if not chosen:
        chosen = list(STAGES)

    allocations = allocate_budgets(chosen, budget_cents)

    for index, stage in enumerate(chosen):
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
                allocations.get(stage["key"], 0),
            ),
        )

    log_event(g.user["id"], project_id, "project.created", f"Project {values['name']} created")

    # A build filed for an address that has no account yet waits in the manager's
    # workspace until that person signs up, then moves under their name.
    held_for = values["client_email"] if values["client_email"] and not client_account else ""

    if web.wants_json():
        created = query("SELECT * FROM projects WHERE id = ?", (project_id,), one=True)
        created["stages"] = stage_rows(project_id)
        created["totals"] = money_totals(project_id)
        created["progress"] = project_progress(created["stages"])
        note = f"{values['name']} created with the full Zimbabwe stage plan."
        if client_account:
            note += f" {client_account['name']} owns it; you are the build manager."
        elif held_for:
            note += (
                f" Tell {held_for} to sign up with that address — the build moves "
                "under their name automatically, with you as build manager."
            )
        return web.ok(
            note,
            fragment=render_template("partials/project_card.html", project=created),
            target="[data-project-grid]",
            mode="prepend",
        )

    flash("Project created. YaVaKa has added the full Zimbabwe stage plan.", "success")
    if held_for:
        flash(
            f"Tell {held_for} to sign up with that address — this build moves under "
            "their name automatically, with you as build manager.",
            "info",
        )
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.get("/app/projects/<project_id>")
@login_required
def detail(project_id):
    project = require_project(project_id)
    stages = stage_rows(project_id)
    spend = stage_spend(project_id)
    totals = money_totals(project_id)
    current = next_stage(stages)
    stage_files = attachments_by_stage(project_id)

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
                    "files": stage_files.get(stage["key"], []),
                }
            )
        groups.append({"name": group, "stages": items})

    owner = query("SELECT * FROM users WHERE id = ?", (project["owner_id"],), one=True)
    manager = (
        query("SELECT * FROM users WHERE id = ?", (project["manager_id"],), one=True)
        if project["manager_id"]
        else None
    )
    manager_invites = (
        team.pending_for_project(project["id"])
        if project["owner_id"] == g.user["id"] or g.user["role"] == "admin"
        else []
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
        manager_invites=manager_invites,
        invite_url=team.invite_url,
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
        display_phone=display_phone,
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
        if web.wants_json():
            return web.fail("Choose a valid stage status.")
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
    queue_manager_update(
        project_id,
        g.user["id"],
        g.user["name"],
        f"Build stage: {stage['name']} — {status.replace('_', ' ')}",
        notes or stage["notes"] or "",
    )

    if status == "complete":
        log_event(g.user["id"], project_id, "stage.completed", f"{stage['name']} marked complete")
        message = f"{stage['name']} marked complete."
        category = "success"
    elif status == "blocked":
        log_event(g.user["id"], project_id, "stage.blocked", f"{stage['name']} blocked: {notes or 'no reason given'}")
        message = f"{stage['name']} is flagged as blocked."
        category = "error"
    else:
        log_event(g.user["id"], project_id, "stage.updated", f"{stage['name']} set to {status.replace('_', ' ')}")
        message = f"{stage['name']} updated."
        category = "success"

    if project["status"] == "planning" and status in {"in_progress", "complete"}:
        execute("UPDATE projects SET status = 'in_progress' WHERE id = ?", (project_id,))

    if web.wants_json():
        refreshed = query("SELECT * FROM stages WHERE id = ?", (stage["id"],), one=True)
        spent = stage_spend(project_id).get(stage_key, 0)
        refreshed = {
            **refreshed,
            "definition": stage_by_key(stage_key),
            "spent": spent,
            "variance": refreshed["budget_cents"] - spent,
            "over": spent > refreshed["budget_cents"] > 0,
        }
        all_stages = stage_rows(project_id)
        return web.ok(
            message,
            fragment=render_template("partials/stage_row.html", stage=refreshed, project=project),
            target=f"#stage-{stage_key}",
            mode="replace",
            fields={
                "[data-progress-value]": f"{project_progress(all_stages)}%",
            },
        )

    flash(message, category)
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

    # Anyone with an account can be added: permission comes from the project,
    # not from the global role label.
    manager = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

    if manager:
        if manager["id"] == project["owner_id"]:
            message = "That is the client's own address; they already own this build."
            if web.wants_json():
                return web.fail(message)
            flash(message, "error")
            return redirect(url_for("projects.detail", project_id=project_id))

        execute(
            "UPDATE projects SET manager_id = ?, updated_at = ? WHERE id = ?",
            (manager["id"], now_iso(), project_id),
        )
        team.link(project["owner_id"], manager["id"], created_by=g.user["id"])
        log_event(g.user["id"], project_id, "project.manager", f"{manager['name']} assigned as build manager")
        message = f"{manager['name']} is now the build manager on this project."

        if web.wants_json():
            return web.ok(message, fields={"[data-manager-name]": manager["name"]})

        flash(message, "success")
        return redirect(url_for("projects.detail", project_id=project_id))

    # No account yet: raise an invitation that also assigns them to this build
    # when they accept. The link is shown on the project page.
    invite = team.invite(g.user, email, project_id=project_id)
    if not invite["ok"]:
        if web.wants_json():
            return web.fail(invite["message"])
        flash(invite["message"], "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    if invite["invitation"]:
        team.email_invitation(invite["invitation"], g.user, project)
        log_event(g.user["id"], project_id, "team.invited", f"Invitation sent to {email}")
        message = (
            f"{email} does not have an account yet. An invitation is ready — "
            "share the link shown under the build manager card."
        )
    else:
        message = invite["message"]

    if web.wants_json():
        return web.ok(message, reload=True)

    flash(message, "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/app/projects/<project_id>/budget")
@login_required
def update_budget(project_id):
    project = require_project(project_id)
    budget_cents = parse_money_to_cents(request.form.get("budget"))

    if budget_cents < 10000:
        message = "Enter a budget of at least $100."
        if web.wants_json():
            return web.fail(message)
        flash(message, "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    execute("UPDATE projects SET budget_cents = ?, updated_at = ? WHERE id = ?", (budget_cents, now_iso(), project_id))
    for stage in STAGES:
        execute(
            "UPDATE stages SET budget_cents = ? WHERE project_id = ? AND key = ?",
            (stage_budget(stage["weight"], budget_cents), project_id, stage["key"]),
        )

    log_event(g.user["id"], project_id, "project.budget", f"Budget set to {format_money(budget_cents)}")
    updates.raise_health_alerts(project_id, actor_id=g.user["id"])
    message = "Budget updated and stage allocations recalculated."

    if web.wants_json():
        # Stage budgets feed several regions, so let the page re-read them once.
        return web.ok(message, fields={"[data-project-budget]": format_money(budget_cents)})

    flash(message, "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/app/projects/<project_id>")
@login_required
def update(project_id):
    """The whole project record in one save, from the edit dialog."""
    project = require_project(project_id)
    values = _read_project_form()
    budget_cents, error = _validate_project(values)

    if error:
        if web.wants_json():
            return web.fail(error)
        flash(error, "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    status = values["status"] if values["status"] in PROJECT_STATUSES else project["status"]
    budget_changed = budget_cents != project["budget_cents"]

    # The contact fields are only rendered for build managers. Preserve whatever
    # is stored when someone else edits the rest of the project.
    keeps_client_contact = not {"client_email", "client_whatsapp"} & set(request.form)
    client_email = project["client_email"] if keeps_client_contact else (values["client_email"][:120] or None)
    client_whatsapp = (
        project["client_whatsapp"]
        if keeps_client_contact
        else (normalize_phone(values["client_whatsapp"]) or None)
    )

    execute(
        """UPDATE projects
           SET name = ?, city = ?, suburb = ?, stand_number = ?, description = ?,
               client_email = ?, client_whatsapp = ?, kind = ?,
               status = ?, budget_cents = ?, start_date = ?, target_date = ?, updated_at = ?
           WHERE id = ?""",
        (
            values["name"][:120],
            values["city"][:80] or "Harare",
            values["suburb"][:80] or None,
            values["stand_number"][:80] or None,
            values["description"][:2000] or None,
            client_email,
            client_whatsapp,
            values["kind"],
            status,
            budget_cents,
            values["start_date"] or None,
            values["target_date"] or None,
            now_iso(),
            project_id,
        ),
    )

    # Stage allocations are derived from the budget, so they have to follow it.
    # Only the stages this project actually has are re-split.
    if budget_changed:
        own_stages = [stage for stage in STAGES if stage["key"] in {row["key"] for row in stage_rows(project_id)}]
        allocations = allocate_budgets(own_stages, budget_cents)
        for key, amount in allocations.items():
            execute(
                "UPDATE stages SET budget_cents = ? WHERE project_id = ? AND key = ?",
                (amount, project_id, key),
            )

    log_event(g.user["id"], project_id, "project.updated", values["name"][:120])
    updates.raise_health_alerts(project_id, actor_id=g.user["id"])
    message = "Project updated and stage budgets recalculated." if budget_changed else "Project updated."

    if web.wants_json():
        return web.ok(message, reload=True)

    flash(message, "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/app/projects/<project_id>/archive")
@login_required
def archive(project_id):
    project = require_project(project_id)
    execute(
        "UPDATE projects SET archived_at = ?, updated_at = ? WHERE id = ?",
        (now_iso(), now_iso(), project_id),
    )
    log_event(g.user["id"], project_id, "project.archived", project["name"][:120])
    message = "Project archived. Its ledger, documents and agreements are kept."

    if web.wants_json():
        return web.ok(message, redirect_to=url_for("projects.index"))

    flash(message, "success")
    return redirect(url_for("projects.index"))


@bp.post("/app/projects/<project_id>/restore")
@login_required
def restore(project_id):
    project = require_project(project_id)
    execute("UPDATE projects SET archived_at = NULL, updated_at = ? WHERE id = ?", (now_iso(), project_id))
    log_event(g.user["id"], project_id, "project.restored", project["name"][:120])
    message = "Project restored to your active list."

    if web.wants_json():
        return web.ok(message, redirect_to=url_for("projects.detail", project_id=project_id))

    flash(message, "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/app/workspaces")
@login_required
def new_workspace():
    """A workspace groups several projects under one name."""
    name = (request.form.get("name") or "").strip()

    if len(name) < 2:
        message = "Give the workspace a name of at least 2 characters."
        if web.wants_json():
            return web.fail(message)
        flash(message, "error")
        return redirect(url_for("projects.index"))

    workspace = create_workspace(g.user, name)
    message = f"{workspace['name']} is ready. New projects can be filed into it."

    if web.wants_json():
        return web.ok(message, reload=True)

    flash(message, "success")
    return redirect(url_for("projects.index", workspace=workspace["id"]))


@bp.get("/app/projects/<project_id>/snapshot")
@login_required
def snapshot(project_id):
    """A read-only copy of the project for the browser's offline cache.

    Renders without forms, CSRF tokens or action buttons: the page is stored on
    the device, so it must never carry anything that could be replayed.
    """
    project = require_project(project_id)
    stages = stage_rows(project_id)

    documents = query(
        """SELECT filename, kind, created_at
           FROM attachments WHERE project_id = ?
           ORDER BY created_at DESC LIMIT 20""",
        (project_id,),
    )

    return render_template(
        "app/snapshot.html",
        project=project,
        stages=stages,
        totals=money_totals(project_id),
        transactions=recent_transactions(project_id, 12),
        documents=documents,
        progress=project_progress(stages),
        saved_at=datetime.now(),
    )
