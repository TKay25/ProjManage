"""Client agreements: scope, payment milestones and e-signature."""

import json
import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import web
from auth import accessible_projects, login_required, require_project
from db import execute, log_event, new_id, now_iso, query
from money import parse_money_to_cents

bp = Blueprint("agreements", __name__)

DEFAULT_TERMS = "\n".join(
    [
        "1. The contractor will build in accordance with the council-approved drawings and the specifications attached to this agreement.",
        "2. The contract price is payable against the milestones set out in the payment schedule.",
        "3. Client funds are held in the project account and released per completed and inspected milestone.",
        "4. Any variation must be agreed in writing before the work is carried out and will be priced separately.",
        "5. The contractor is responsible for site safety and for statutory inspections at foundation, roofing and completion stages.",
        "6. Practical completion is targeted for the date recorded on this agreement, subject to council approvals and client-funded materials arriving on time.",
        "7. The contractor holds 5% retention from each payment until the snag list is closed, then releases it within 14 days.",
        "8. Either party may refer a dispute to mediation, then arbitration under the Arbitration Act [Chapter 7:15] of Zimbabwe.",
        "9. This agreement is governed by the laws of Zimbabwe.",
    ]
)


@bp.get("/app/agreements")
@login_required
def index():
    projects = accessible_projects(g.user)
    project_id = request.args.get("project", "")
    project = next((item for item in projects if item["id"] == project_id), None)

    params = []
    where = []
    if project:
        where.append("g.project_id = ?")
        params.append(project["id"])
    elif projects:
        placeholders = ",".join("?" for _ in projects)
        where.append(f"g.project_id IN ({placeholders})")
        params.extend([item["id"] for item in projects])

    agreements = []
    if where:
        agreements = query(
            f"""SELECT g.*, p.name AS project_name, u.name AS author_name
                FROM agreements g
                JOIN projects p ON p.id = g.project_id
                LEFT JOIN users u ON u.id = g.created_by
                WHERE {' AND '.join(where)}
                ORDER BY g.created_at DESC""",
            params,
        )

    for agreement in agreements:
        try:
            agreement["schedule"] = json.loads(agreement["payment_schedule"] or "[]")
        except json.JSONDecodeError:
            agreement["schedule"] = []

    return render_template(
        "app/agreements.html",
        title="Agreements",
        active="agreements",
        projects=projects,
        project=project,
        agreements=agreements,
    )


@bp.get("/app/agreements/new")
@login_required
def new():
    projects = accessible_projects(g.user)
    project_id = request.args.get("project", "")
    project = next((item for item in projects if item["id"] == project_id), None)
    project = project or (projects[0] if projects else None)

    if not project:
        flash("Create a project first, then build its agreement.", "error")
        return redirect(url_for("projects.new"))

    return render_template(
        "app/agreement_new.html",
        title="New agreement",
        active="agreements",
        projects=projects,
        project=project,
        terms=DEFAULT_TERMS,
        values={},
        error=None,
    )


@bp.post("/app/agreements")
@login_required
def create():
    project = require_project(request.form.get("project_id") or "")
    title = (request.form.get("title") or "").strip()
    scope = (request.form.get("scope") or "").strip()
    terms = (request.form.get("terms") or "").strip()
    client_name = (request.form.get("client_name") or "").strip()
    contract_value_cents = parse_money_to_cents(request.form.get("contract_value"))
    agreement_type = request.form.get("type") or "build_contract"

    if agreement_type not in {"build_contract", "stage_scope", "variation"}:
        agreement_type = "build_contract"

    error = None
    if len(title) < 4:
        error = "Give the agreement a clear title."
    elif len(scope) < 20:
        error = "Describe the scope of works (at least 20 characters)."
    elif not client_name:
        error = "Enter the client's full name."
    elif contract_value_cents <= 0:
        error = "Enter the contract value."

    schedule = []
    labels = request.form.getlist("milestone_label")
    amounts = request.form.getlist("milestone_amount")
    for label, amount in zip(labels, amounts):
        label = label.strip()
        cents = parse_money_to_cents(amount)
        if label and cents > 0:
            schedule.append({"label": label[:120], "amountCents": cents})

    if error:
        if web.wants_json():
            return web.fail(error)
        return (
            render_template(
                "app/agreement_new.html",
                title="New agreement",
                active="agreements",
                projects=accessible_projects(g.user),
                project=project,
                terms=terms,
                values={
                    "title": title,
                    "scope": scope,
                    "client_name": client_name,
                    "contract_value": request.form.get("contract_value"),
                    "type": agreement_type,
                },
                error=error,
            ),
            400,
        )

    agreement_id = new_id()
    execute(
        """INSERT INTO agreements
             (id, project_id, type, title, contract_value_cents, currency, scope, terms, payment_schedule,
              client_name, client_signature, signed_at, status, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, NULL, NULL, 'awaiting_signature', ?, ?)""",
        (
            agreement_id,
            project["id"],
            agreement_type,
            title[:160],
            contract_value_cents,
            scope[:6000],
            terms[:8000],
            json.dumps(schedule),
            client_name[:120],
            g.user["id"],
            now_iso(),
        ),
    )

    log_event(g.user["id"], project["id"], "agreement.created", title[:120])

    if web.wants_json():
        created = query(
            """SELECT g.*, p.name AS project_name
               FROM agreements g JOIN projects p ON p.id = g.project_id
               WHERE g.id = ?""",
            (agreement_id,),
            one=True,
        )
        created["schedule"] = schedule
        return web.ok(
            "Agreement saved and awaiting the client's signature.",
            fragment=render_template("partials/agreement_card.html", agreement=created),
            target="[data-agreement-list]",
            mode="prepend",
            redirect_to=url_for("agreements.detail", agreement_id=agreement_id),
        )

    flash("Agreement saved. Send it to the client for signature.", "success")
    return redirect(url_for("agreements.detail", agreement_id=agreement_id))


@bp.get("/app/agreements/<agreement_id>")
@login_required
def detail(agreement_id):
    agreement = query("SELECT * FROM agreements WHERE id = ?", (agreement_id,), one=True)

    if not agreement:
        abort(404)

    project = require_project(agreement["project_id"])
    author = query("SELECT name, role FROM users WHERE id = ?", (agreement["created_by"],), one=True)

    try:
        schedule = json.loads(agreement["payment_schedule"] or "[]")
    except json.JSONDecodeError:
        schedule = []

    return render_template(
        "app/agreement_detail.html",
        title=agreement["title"],
        active="agreements",
        projects=accessible_projects(g.user),
        project=project,
        agreement=agreement,
        author=author,
        schedule=schedule,
        scheduled_total=sum(item.get("amountCents", 0) for item in schedule),
    )


@bp.post("/app/agreements/<agreement_id>/sign")
@login_required
def sign(agreement_id):
    agreement = query("SELECT * FROM agreements WHERE id = ?", (agreement_id,), one=True)

    if not agreement:
        abort(404)

    project = require_project(agreement["project_id"])
    signature = request.form.get("signature") or ""
    signed_name = (request.form.get("signed_name") or agreement["client_name"]).strip()

    if signature and not re.match(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$", signature):
        message = "The signature could not be read. Try signing again."
        if web.wants_json():
            return web.fail(message)
        flash(message, "error")
        return redirect(url_for("agreements.detail", agreement_id=agreement_id))

    if len(signature) > 1_500_000:
        message = "That signature image is too large."
        if web.wants_json():
            return web.fail(message)
        flash(message, "error")
        return redirect(url_for("agreements.detail", agreement_id=agreement_id))

    execute(
        "UPDATE agreements SET client_signature = ?, signed_at = ?, status = 'signed', client_name = ? WHERE id = ?",
        (signature or None, now_iso(), signed_name[:120], agreement_id),
    )
    log_event(g.user["id"], project["id"], "agreement.signed", agreement["title"][:120])
    message = "Agreement signed and locked to the project record."

    if web.wants_json():
        signed = query("SELECT * FROM agreements WHERE id = ?", (agreement_id,), one=True)
        return web.ok(
            message,
            fragment=render_template("partials/signature_panel.html", agreement=signed, user=g.user),
            target="[data-signature-panel]",
            mode="replace",
        )

    flash(message, "success")
    return redirect(url_for("agreements.detail", agreement_id=agreement_id))


@bp.post("/app/agreements/<agreement_id>/void")
@login_required
def void(agreement_id):
    agreement = query("SELECT * FROM agreements WHERE id = ?", (agreement_id,), one=True)

    if not agreement:
        abort(404)

    project = require_project(agreement["project_id"])
    execute("UPDATE agreements SET status = 'void' WHERE id = ?", (agreement_id,))
    log_event(g.user["id"], project["id"], "agreement.void", agreement["title"][:120])

    if web.wants_json():
        return web.ok("Agreement marked as void.", fields={"[data-agreement-status]": "Void"})

    flash("Agreement marked as void.", "success")
    return redirect(url_for("agreements.detail", agreement_id=agreement_id))


@bp.get("/app/agreements/<agreement_id>/print")
@login_required
def print_view(agreement_id):
    agreement = query("SELECT * FROM agreements WHERE id = ?", (agreement_id,), one=True)

    if not agreement:
        abort(404)

    project = require_project(agreement["project_id"])

    try:
        schedule = json.loads(agreement["payment_schedule"] or "[]")
    except json.JSONDecodeError:
        schedule = []

    return render_template(
        "app/agreement_print.html",
        agreement=agreement,
        project=project,
        schedule=schedule,
        scheduled_total=sum(item.get("amountCents", 0) for item in schedule),
    )
