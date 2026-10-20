"""Funding, expenses, receipts and the project ledger."""

from datetime import datetime

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from auth import accessible_projects, login_required, require_project
from db import execute, log_event, new_id, now_iso, query, touch_project
from money import parse_money_to_cents
from queries import category_breakdown, missing_receipts, money_totals, stage_rows, stage_spend
from stages import TRANSACTION_CATEGORIES
from storage import UploadError, delete_upload, save_upload

bp = Blueprint("money", __name__)

VALID_CATEGORIES = {value for value, _label in TRANSACTION_CATEGORIES}
VALID_METHODS = {"BANK_TRANSFER", "CARD", "ECOCASH", "INN_BUCKS", "CASH", "OTHER"}


def _selected_project():
    projects = accessible_projects(g.user)
    requested = request.args.get("project")
    project = next((item for item in projects if item["id"] == requested), None)
    return projects, project or (projects[0] if projects else None)


@bp.get("/app/money")
@login_required
def index():
    projects, project = _selected_project()

    if not project:
        return render_template("app/money.html", title="Money", active="money", projects=[], project=None)

    filter_type = request.args.get("filter", "all")
    search = (request.args.get("q") or "").strip()
    stage_filter = request.args.get("stage", "")

    where = ["t.project_id = ?"]
    params = [project["id"]]

    if filter_type == "funding":
        where.append("t.type = 'FUNDING'")
    elif filter_type == "expense":
        where.append("t.type = 'EXPENSE'")
    elif filter_type == "missing":
        where.append("t.type = 'EXPENSE' AND a.id IS NULL")

    if search:
        where.append("(t.description LIKE ? OR t.reference LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if stage_filter:
        where.append("t.stage_key = ?")
        params.append(stage_filter)

    transactions = query(
        f"""SELECT t.*, a.id AS receipt_id, a.filename AS receipt_file
            FROM transactions t
            LEFT JOIN attachments a ON a.transaction_id = t.id
            WHERE {' AND '.join(where)}
            ORDER BY t.occurred_at DESC, t.created_at DESC
            LIMIT 250""",
        params,
    )

    totals = money_totals(project["id"])
    stages = stage_rows(project["id"])
    breakdown = category_breakdown(project["id"])
    spent_total = totals["spent"] or 1

    return render_template(
        "app/money.html",
        title="Money",
        active="money",
        projects=projects,
        project=project,
        transactions=transactions,
        totals=totals,
        stages=stages,
        breakdown=breakdown,
        spent_total=spent_total,
        missing_count=len(missing_receipts(project["id"])),
        stage_spend=stage_spend(project["id"]),
        filter_type=filter_type,
        search=search,
        stage_filter=stage_filter,
        today=datetime.now().strftime("%Y-%m-%d"),
    )


@bp.post("/app/money")
@login_required
def create():
    project = require_project(request.form.get("project_id") or "")
    tx_type = request.form.get("type") or "EXPENSE"
    amount_cents = parse_money_to_cents(request.form.get("amount"))
    description = (request.form.get("description") or "").strip()
    category = request.form.get("category") or "other"
    method = request.form.get("method") or "BANK_TRANSFER"
    stage_key = request.form.get("stage_key") or None
    reference = (request.form.get("reference") or "").strip()[:80] or None
    occurred = request.form.get("occurred_at") or datetime.now().strftime("%Y-%m-%d")
    receipt = request.files.get("receipt")

    if tx_type not in {"FUNDING", "EXPENSE"}:
        flash("Choose whether this is money in or money out.", "error")
        return redirect(url_for("money.index", project=project["id"]))

    if amount_cents <= 0:
        flash("Enter an amount greater than zero.", "error")
        return redirect(url_for("money.index", project=project["id"]))

    if len(description) < 3:
        flash("Add a short description so the entry makes sense later.", "error")
        return redirect(url_for("money.index", project=project["id"]))

    if tx_type == "FUNDING":
        category = "client_deposit"
    elif category not in VALID_CATEGORIES:
        category = "other"

    if method not in VALID_METHODS:
        method = "OTHER"

    try:
        datetime.strptime(occurred, "%Y-%m-%d")
    except ValueError:
        occurred = datetime.now().strftime("%Y-%m-%d")

    saved = None
    if receipt and receipt.filename:
        try:
            saved = save_upload(receipt, "receipt")
        except UploadError as error:
            flash(str(error), "error")
            return redirect(url_for("money.index", project=project["id"]))

    transaction_id = new_id()
    occurred_at = f"{occurred}T12:00:00+00:00"

    execute(
        """INSERT INTO transactions
             (id, project_id, type, amount_cents, currency, category, stage_key, description, method, reference, occurred_at, created_by, created_at)
           VALUES (?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            transaction_id,
            project["id"],
            tx_type,
            amount_cents,
            category,
            stage_key,
            description[:200],
            method,
            reference,
            occurred_at,
            g.user["id"],
            now_iso(),
        ),
    )

    if saved:
        execute(
            """INSERT INTO attachments
                 (id, project_id, transaction_id, uploader_id, kind, filename, original_name, mime_type, size, created_at)
               VALUES (?, ?, ?, ?, 'receipt', ?, ?, ?, ?, ?)""",
            (
                new_id(),
                project["id"],
                transaction_id,
                g.user["id"],
                saved["filename"],
                saved["original_name"],
                saved["mime_type"],
                saved["size"],
                now_iso(),
            ),
        )

    touch_project(project["id"])
    log_event(
        g.user["id"],
        project["id"],
        "funding.recorded" if tx_type == "FUNDING" else "expense.recorded",
        f"{description[:120]} — {'received' if tx_type == 'FUNDING' else 'spent'}",
    )

    flash(
        "Deposit recorded." if tx_type == "FUNDING" else "Expense recorded" + (" with receipt." if saved else " — add a receipt when you have it."),
        "success",
    )
    return redirect(url_for("money.index", project=project["id"]))


@bp.post("/app/money/<transaction_id>/receipt")
@login_required
def attach_receipt(transaction_id):
    transaction = query("SELECT * FROM transactions WHERE id = ?", (transaction_id,), one=True)

    if not transaction:
        flash("That transaction no longer exists.", "error")
        return redirect(url_for("money.index"))

    project = require_project(transaction["project_id"])
    file = request.files.get("receipt")

    try:
        saved = save_upload(file, "receipt")
    except UploadError as error:
        flash(str(error), "error")
        return redirect(url_for("money.index", project=project["id"]))

    existing = query("SELECT * FROM attachments WHERE transaction_id = ?", (transaction_id,), one=True)
    if existing:
        delete_upload(existing["filename"])
        execute("DELETE FROM attachments WHERE id = ?", (existing["id"],))

    execute(
        """INSERT INTO attachments
             (id, project_id, transaction_id, uploader_id, kind, filename, original_name, mime_type, size, created_at)
           VALUES (?, ?, ?, ?, 'receipt', ?, ?, ?, ?, ?)""",
        (
            new_id(),
            project["id"],
            transaction_id,
            g.user["id"],
            saved["filename"],
            saved["original_name"],
            saved["mime_type"],
            saved["size"],
            now_iso(),
        ),
    )

    log_event(g.user["id"], project["id"], "receipt.attached", f"Receipt attached to {transaction['description'][:80]}")
    flash("Receipt attached to the expense.", "success")
    return redirect(url_for("money.index", project=project["id"]))


@bp.post("/app/money/<transaction_id>/delete")
@login_required
def delete(transaction_id):
    transaction = query("SELECT * FROM transactions WHERE id = ?", (transaction_id,), one=True)

    if not transaction:
        flash("That transaction no longer exists.", "error")
        return redirect(url_for("money.index"))

    project = require_project(transaction["project_id"])

    attachment = query("SELECT * FROM attachments WHERE transaction_id = ?", (transaction_id,), one=True)
    if attachment:
        delete_upload(attachment["filename"])

    execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    touch_project(project["id"])
    log_event(g.user["id"], project["id"], "transaction.deleted", transaction["description"][:120])
    flash("Entry deleted.", "success")
    return redirect(url_for("money.index", project=project["id"]))
