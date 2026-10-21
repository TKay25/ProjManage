"""Funding, expenses, receipts and the project ledger."""

import csv
import io
import re
from datetime import datetime

from flask import Blueprint, flash, g, make_response, redirect, render_template, request, url_for

from auth import accessible_projects, login_required, require_project
from db import execute, log_event, new_id, now_iso, query, touch_project
from money import format_money, parse_money_to_cents
from notifications import queue_manager_update
from paging import offset, page_number, page_window
from queries import category_breakdown, missing_receipts, money_totals, stage_rows, stage_spend
from stages import TRANSACTION_CATEGORIES, category_label, method_label, stage_name
from storage import UploadError, delete_upload, save_upload
import web

bp = Blueprint("money", __name__)

VALID_CATEGORIES = {value for value, _label in TRANSACTION_CATEGORIES}
VALID_METHODS = {"BANK_TRANSFER", "CARD", "ECOCASH", "INN_BUCKS", "CASH", "OTHER"}

PAGE_SIZE = 25

CSV_COLUMNS = [
    "Date",
    "Direction",
    "Description",
    "Category",
    "Stage",
    "Paid with",
    "Reference",
    "Money in",
    "Money out",
    "Balance",
    "Receipt",
]


def _selected_project():
    projects = accessible_projects(g.user)
    requested = request.args.get("project")
    project = next((item for item in projects if item["id"] == requested), None)
    return projects, project or (projects[0] if projects else None)


def _ledger_filters(project):
    """The WHERE clause behind the ledger, shared by the page and the export."""
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

    return where, params, filter_type, search, stage_filter


def _ledger_count(where, params) -> int:
    row = query(
        f"""SELECT COUNT(*) AS total
            FROM transactions t
            LEFT JOIN attachments a ON a.transaction_id = t.id
            WHERE {' AND '.join(where)}""",
        params,
        one=True,
    )
    return int(row["total"] or 0)


def _csv_amount(cents: int) -> str:
    """Plain decimal for spreadsheets, using integer maths so nothing drifts."""
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def _csv_safe(value) -> str:
    """Stops a description from being read as a spreadsheet formula."""
    text = str(value or "")
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@bp.get("/app/money/export")
@login_required
def export():
    """A statement a diaspora client can keep and open in Excel or Sheets."""
    _projects, project = _selected_project()
    if not project:
        return redirect(url_for("money.index"))

    where, params, _f, _s, _st = _ledger_filters(project)

    rows = query(
        f"""SELECT t.*, a.id AS receipt_id
            FROM transactions t
            LEFT JOIN attachments a ON a.transaction_id = t.id
            WHERE {' AND '.join(where)}
            ORDER BY t.occurred_at ASC, t.created_at ASC""",
        params,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)

    balance = 0
    money_in = 0
    money_out = 0

    for row in rows:
        amount = int(row["amount_cents"] or 0)
        is_funding = row["type"] == "FUNDING"
        balance += amount if is_funding else -amount
        if is_funding:
            money_in += amount
        else:
            money_out += amount

        writer.writerow(
            [
                (row["occurred_at"] or "")[:10],
                "Money in" if is_funding else "Money out",
                _csv_safe(row["description"]),
                category_label(row["category"]),
                stage_name(row["stage_key"]) if row["stage_key"] else "",
                method_label(row["method"]),
                _csv_safe(row["reference"]),
                _csv_amount(amount) if is_funding else "",
                "" if is_funding else _csv_amount(amount),
                _csv_amount(balance),
                "Yes" if row["receipt_id"] else "No",
            ]
        )

    writer.writerow([])
    writer.writerow(
        ["", "", "Totals", "", "", "", "", _csv_amount(money_in), _csv_amount(money_out), _csv_amount(balance), ""]
    )

    slug = re.sub(r"[^a-z0-9]+", "-", project["name"].lower()).strip("-")[:40] or "project"
    filename = f"vaka-ledger-{slug}-{datetime.now():%Y-%m-%d}.csv"

    # The BOM keeps Excel from mangling accented supplier names.
    response = make_response("\ufeff" + buffer.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.get("/app/money")
@login_required
def index():
    projects, project = _selected_project()

    if not project:
        return render_template("app/money.html", title="Money", active="money", projects=[], project=None)

    filter_type = request.args.get("filter", "all")
    search = (request.args.get("q") or "").strip()
    stage_filter = request.args.get("stage", "")

    where, params, filter_type, search, stage_filter = _ledger_filters(project)
    total_rows = _ledger_count(where, params)
    page, page_count = page_window(page_number(), total_rows, PAGE_SIZE)

    transactions = query(
        f"""SELECT t.*, a.id AS receipt_id, a.filename AS receipt_file
            FROM transactions t
            LEFT JOIN attachments a ON a.transaction_id = t.id
            WHERE {' AND '.join(where)}
            ORDER BY t.occurred_at DESC, t.created_at DESC
            LIMIT ? OFFSET ?""",
        [*params, PAGE_SIZE, offset(page, PAGE_SIZE)],
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
        page=page,
        page_count=page_count,
        total_rows=total_rows,
        pager_endpoint="money.index",
        pager_args={"project": project["id"], "filter": filter_type, "q": search, "stage": stage_filter},
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
        if web.wants_json():
            return web.fail("Choose whether this is money in or money out.")
        flash("Choose whether this is money in or money out.", "error")
        return redirect(url_for("money.index", project=project["id"]))

    if amount_cents <= 0:
        if web.wants_json():
            return web.fail("Enter an amount greater than zero.")
        flash("Enter an amount greater than zero.", "error")
        return redirect(url_for("money.index", project=project["id"]))

    if len(description) < 3:
        if web.wants_json():
            return web.fail("Add a short description so the entry makes sense later.")
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
            if web.wants_json():
                return web.fail(str(error))
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
    queue_manager_update(
        project["id"],
        g.user["id"],
        g.user["name"],
        f"{'Funding received' if tx_type == 'FUNDING' else 'Expense recorded'}: {format_money(amount_cents)}",
        description[:200],
    )

    if tx_type == "FUNDING":
        message = "Deposit recorded."
    elif saved:
        message = "Expense recorded with its receipt."
    else:
        message = "Expense recorded — add a receipt when you have it."

    if web.wants_json():
        totals = money_totals(project["id"])
        fields = {
            "[data-kpi-balance]": format_money(totals["balance"]),
            "[data-kpi-funded]": format_money(totals["funded"]),
            "[data-kpi-spent]": format_money(totals["spent"]),
            "[data-balance-hint]": f"Balance after this entry: {format_money(totals['balance'])}",
        }

        # Other pages (the dashboard) show derived figures we do not patch, so
        # they re-read the project once instead of receiving stale numbers.
        if request.form.get("_return") == "page":
            return web.ok(message, fields=fields, reload=True)

        row = query(
            """SELECT t.*, a.id AS receipt_id
               FROM transactions t LEFT JOIN attachments a ON a.transaction_id = t.id
               WHERE t.id = ?""",
            (transaction_id,),
            one=True,
        )
        return web.ok(
            message,
            fragment=render_template("partials/ledger_row.html", tx=row),
            target="[data-ledger-list]",
            mode="prepend",
            fields=fields,
        )

    flash(message, "success")
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
        if web.wants_json():
            return web.fail(str(error))
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

    if web.wants_json():
        row = query(
            """SELECT t.*, a.id AS receipt_id
               FROM transactions t LEFT JOIN attachments a ON a.transaction_id = t.id
               WHERE t.id = ?""",
            (transaction_id,),
            one=True,
        )
        totals = money_totals(project["id"])
        return web.ok(
            "Receipt attached to the expense.",
            fragment=render_template("partials/ledger_row.html", tx=row),
            target=f"#tx-{transaction_id}",
            mode="replace",
            fields={
                "[data-kpi-balance]": format_money(totals["balance"]),
                "[data-kpi-funded]": format_money(totals["funded"]),
                "[data-kpi-spent]": format_money(totals["spent"]),
            },
        )

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

    if web.wants_json():
        totals = money_totals(project["id"])
        return web.ok(
            "Entry deleted.",
            fragment="",
            target=f"#tx-{transaction_id}",
            mode="remove",
            fields={
                "[data-kpi-balance]": format_money(totals["balance"]),
                "[data-kpi-funded]": format_money(totals["funded"]),
                "[data-kpi-spent]": format_money(totals["spent"]),
            },
        )

    flash("Entry deleted.", "success")
    return redirect(url_for("money.index", project=project["id"]))
