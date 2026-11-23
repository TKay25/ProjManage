"""Write paths shared by the pages and the conversation.

Money and stage changes used to live inline in their blueprints. They live here
so a chat command and the matching form run the same validation, write the same
audit row, raise the same red/green signal and queue the same stakeholder
notification. A reply in the chat can therefore never disagree with the ledger.

Each function raises ServiceError with a sentence a person can act on; nothing
is written when that happens.
"""

from datetime import date, datetime

from flask import url_for

from db import execute, log_event, new_id, now_iso, query, touch_project
from money import format_money
from notifications import queue_manager_update
from stages import PAYMENT_METHODS, TRANSACTION_CATEGORIES
from storage import UploadError, delete_upload, save_upload
import rentals
import updates


class ServiceError(ValueError):
    """Validation failed; the caller shows the message and nothing is written."""


VALID_METHODS = {value for value, _label in PAYMENT_METHODS}
# A deposit is always a client deposit, so the expense categories start after it.
EXPENSE_CATEGORIES = [
    (value, label) for value, label in TRANSACTION_CATEGORIES if value != "client_deposit"
]
VALID_EXPENSE_CATEGORIES = {value for value, _label in EXPENSE_CATEGORIES}
STAGE_STATUSES = {"pending", "in_progress", "complete", "blocked"}


def money_in(cents: int) -> str:
    return format_money(int(cents or 0))


def record_project_transaction(
    user,
    project,
    *,
    tx_type: str,
    amount_cents: int,
    description: str,
    category: str = "other",
    method: str = "BANK_TRANSFER",
    stage_key: str | None = None,
    reference: str | None = None,
    occurred: str | None = None,
    receipt=None,
) -> dict:
    """Record a funding or expense row, exactly as the ledger form does."""
    tx_type = (tx_type or "EXPENSE").upper()
    description = (description or "").strip()
    reference = (reference or "").strip()[:80] or None
    occurred = occurred or datetime.now().strftime("%Y-%m-%d")

    if tx_type not in {"FUNDING", "EXPENSE"}:
        raise ServiceError("Choose whether this is money in or money out.")
    if amount_cents <= 0:
        raise ServiceError("Enter an amount greater than zero.")
    if len(description) < 3:
        raise ServiceError("Add a short description so the entry makes sense later.")

    if tx_type == "FUNDING":
        category = "client_deposit"
    elif category not in VALID_EXPENSE_CATEGORIES:
        category = "other"

    if method not in VALID_METHODS:
        method = "OTHER"

    try:
        datetime.strptime(occurred, "%Y-%m-%d")
    except ValueError:
        occurred = datetime.now().strftime("%Y-%m-%d")

    saved = None
    if receipt is not None and getattr(receipt, "filename", ""):
        try:
            saved = save_upload(receipt, "receipt")
        except UploadError as error:
            raise ServiceError(str(error)) from error

    transaction_id = new_id()
    execute(
        """INSERT INTO transactions
             (id, project_id, type, amount_cents, currency, category, stage_key, description,
              method, reference, occurred_at, created_by, created_at)
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
            f"{occurred}T12:00:00+00:00",
            user["id"],
            now_iso(),
        ),
    )

    if saved:
        execute(
            """INSERT INTO attachments
                 (id, project_id, transaction_id, uploader_id, kind, filename, original_name,
                  mime_type, size, created_at)
               VALUES (?, ?, ?, ?, 'receipt', ?, ?, ?, ?, ?)""",
            (
                new_id(),
                project["id"],
                transaction_id,
                user["id"],
                saved["filename"],
                saved["original_name"],
                saved["mime_type"],
                saved["size"],
                now_iso(),
            ),
        )

    touch_project(project["id"])
    log_event(
        user["id"],
        project["id"],
        "funding.recorded" if tx_type == "FUNDING" else "expense.recorded",
        f"{description[:120]} — {'received' if tx_type == 'FUNDING' else 'spent'}",
    )
    # A payment is the moment a build can slip over budget or over its funding,
    # so this is where the red signal is raised.
    updates.raise_health_alerts(project["id"], actor_id=user["id"])
    queue_manager_update(
        project["id"],
        user["id"],
        user["name"],
        f"{'Funding received' if tx_type == 'FUNDING' else 'Expense recorded'}: {format_money(amount_cents)}",
        description[:200],
    )

    return {
        "id": transaction_id,
        "tx_type": tx_type,
        "amount_cents": amount_cents,
        "receipt_saved": bool(saved),
    }


def delete_project_transaction(user, project, transaction_id: str) -> dict:
    """Remove a ledger entry, and the receipt hanging off it.

    Used by the ledger's delete button and by "undo" in the conversation, so a
    mistaken entry is corrected the same way from either place.
    """
    transaction = query(
        "SELECT * FROM transactions WHERE id = ? AND project_id = ?",
        (transaction_id, project["id"]),
        one=True,
    )
    if not transaction:
        raise ServiceError("That entry is no longer in the ledger.")

    attachment = query(
        "SELECT * FROM attachments WHERE transaction_id = ?", (transaction_id,), one=True
    )
    if attachment:
        delete_upload(attachment["filename"])

    execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    touch_project(project["id"])
    log_event(
        user["id"], project["id"], "transaction.deleted", transaction["description"][:120]
    )
    return {
        "description": transaction["description"],
        "amount_cents": transaction["amount_cents"],
        "tx_type": transaction["type"],
    }


def change_stage_status(user, project, stage, status: str, notes: str = "") -> dict:
    """Move one stage through start / complete / block, as the checklist does."""
    status = status or ""
    notes = (notes or "").strip()[:1000]
    if status not in STAGE_STATUSES:
        raise ServiceError("Choose a valid stage status.")

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
    touch_project(project["id"])
    queue_manager_update(
        project["id"],
        user["id"],
        user["name"],
        f"Build stage: {stage['name']} — {status.replace('_', ' ')}",
        notes or stage["notes"] or "",
    )

    if status == "complete":
        log_event(user["id"], project["id"], "stage.completed", f"{stage['name']} marked complete")
        message = f"{stage['name']} marked complete."
    elif status == "blocked":
        log_event(
            user["id"],
            project["id"],
            "stage.blocked",
            f"{stage['name']} blocked: {notes or 'no reason given'}",
        )
        message = f"{stage['name']} is flagged as blocked."
    else:
        log_event(
            user["id"],
            project["id"],
            "stage.updated",
            f"{stage['name']} set to {status.replace('_', ' ')}",
        )
        message = f"{stage['name']} updated."

    if project["status"] == "planning" and status in {"in_progress", "complete"}:
        execute("UPDATE projects SET status = 'in_progress' WHERE id = ?", (project["id"],))
    return {"status": status, "message": message}


def post_project_update(user, project, message: str) -> dict:
    """A progress note from whoever is running the build.

    The owner (and any other manager) gets it in the Updates inbox, and it is
    written to the audit trail, which is what the weekly digest reads.
    """
    message = (message or "").strip()
    if len(message) < 3:
        raise ServiceError("Write the update you want the client to see.")

    touch_project(project["id"])
    log_event(user["id"], project["id"], "project.update", message[:200])
    delivered = 0
    for recipient in {project["owner_id"], project.get("manager_id")} - {None}:
        if recipient == user["id"]:
            continue
        delivered += updates.notify(
            recipient,
            project["id"],
            "project.update",
            f"{user['name']}: {message[:160]}",
            href=f"/app/updates",
            actor_id=user["id"],
        )
    return {"message": message, "delivered": delivered}


def record_rent_payment(
    user,
    property_row,
    *,
    amount_cents: int,
    method: str = "ECOCASH",
    invoice=None,
    reference: str | None = None,
    received_at: str | None = None,
    notes: str | None = None,
) -> dict:
    """Receipt rent, either against an invoice or on account."""
    if amount_cents <= 0:
        raise ServiceError("Enter the amount received.")
    if method not in VALID_METHODS:
        method = "OTHER"

    tenant_id = invoice["tenant_id"] if invoice else None
    if not tenant_id:
        tenant = rentals.tenant_in_place(property_row["id"])
        tenant_id = tenant["id"] if tenant else None

    received_at = received_at or date.today().isoformat()
    try:
        datetime.strptime(received_at, "%Y-%m-%d")
    except ValueError:
        received_at = date.today().isoformat()

    payment_id, receipt = None, None
    for _attempt in range(5):
        receipt = rentals.receipt_number()
        try:
            payment_id = new_id()
            execute(
                """INSERT INTO property_payments
                     (id, owner_id, property_id, lease_id, invoice_id, tenant_id, receipt_number,
                      amount_cents, currency, method, reference, received_at, notes, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?)""",
                (
                    payment_id,
                    property_row["owner_id"],
                    property_row["id"],
                    invoice["lease_id"] if invoice else None,
                    invoice["id"] if invoice else None,
                    tenant_id,
                    receipt,
                    amount_cents,
                    method,
                    (reference or "").strip()[:80] or None,
                    f"{received_at}T12:00:00+00:00",
                    (notes or "").strip()[:500] or None,
                    user["id"],
                    now_iso(),
                ),
            )
            break
        except Exception as error:  # noqa: BLE001 - a receipt-number clash is retried
            if "UNIQUE" not in str(error).upper() and "DUPLICATE" not in str(error).upper():
                raise
            payment_id = None
            continue

    if not payment_id:
        raise ServiceError("Could not allocate a receipt number. Try again.")

    if invoice:
        rentals.refresh_invoice_status(invoice["id"])

    log_event(
        user["id"],
        None,
        "rent.receipt",
        f"{receipt} — {amount_cents / 100:.2f} for {property_row['name'][:60]}",
    )
    rentals.log_activity(
        property_row["owner_id"],
        property_row["id"],
        user["id"],
        "rent.receipt",
        "Rent receipted",
        f"{receipt} — {format_money(amount_cents)}",
        href=url_for("rentals.payment_receipt", payment_id=payment_id),
    )
    return {"id": payment_id, "receipt": receipt, "amount_cents": amount_cents}


def reverse_rent_payment(user, property_row, payment_id: str) -> dict:
    """Undo a receipt: the payment disappears and the invoice is open again."""
    payment = query(
        "SELECT * FROM property_payments WHERE id = ? AND property_id = ?",
        (payment_id, property_row["id"]),
        one=True,
    )
    if not payment:
        raise ServiceError("That receipt has already been reversed.")

    execute("DELETE FROM property_payments WHERE id = ?", (payment_id,))
    if payment["invoice_id"]:
        rentals.refresh_invoice_status(payment["invoice_id"])
    log_event(user["id"], None, "rent.reversed", payment["receipt_number"])
    rentals.log_activity(
        property_row["owner_id"],
        property_row["id"],
        user["id"],
        "rent.reversed",
        "Receipt reversed",
        f"{payment['receipt_number']} - {format_money(payment['amount_cents'])}",
        href=url_for("rentals.payments"),
    )
    return {
        "receipt": payment["receipt_number"],
        "amount_cents": payment["amount_cents"],
    }


def delete_property_expense(user, property_row, expense_id: str) -> dict:
    expense = query(
        "SELECT * FROM property_expenses WHERE id = ? AND property_id = ?",
        (expense_id, property_row["id"]),
        one=True,
    )
    if not expense:
        raise ServiceError("That cost has already been removed.")

    execute("DELETE FROM property_expenses WHERE id = ?", (expense_id,))
    log_event(user["id"], None, "property.expense_deleted", expense["description"][:80])
    rentals.log_activity(
        property_row["owner_id"],
        property_row["id"],
        user["id"],
        "property.expense_deleted",
        "Property cost removed",
        expense["description"][:80],
        href=url_for("rentals.expenses", property=property_row["id"]),
    )
    return {"description": expense["description"], "amount_cents": expense["amount_cents"]}


def record_property_expense(
    user,
    property_row,
    *,
    category: str,
    amount_cents: int,
    description: str,
    method: str = "BANK_TRANSFER",
    reference: str | None = None,
    incurred: str | None = None,
    billable: bool = False,
) -> dict:
    """Record a cost of owning the property, as the Costs page does."""
    description = (description or "").strip()
    valid_categories = {key for key, _label in rentals.EXPENSE_CATEGORIES}
    if category not in valid_categories:
        category = "other"
    if method not in VALID_METHODS:
        method = "OTHER"
    if amount_cents <= 0:
        raise ServiceError("Enter what the cost was.")
    if len(description) < 3:
        raise ServiceError("Add a short description so the cost makes sense later.")

    incurred = incurred or date.today().isoformat()
    try:
        datetime.strptime(incurred, "%Y-%m-%d")
    except ValueError:
        incurred = date.today().isoformat()

    expense_id = new_id()
    execute(
        """INSERT INTO property_expenses
             (id, owner_id, property_id, category, amount_cents, currency, description, method,
              reference, incurred_at, billable_to_tenant, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?)""",
        (
            expense_id,
            property_row["owner_id"],
            property_row["id"],
            category,
            amount_cents,
            description[:200],
            method,
            (reference or "").strip()[:80] or None,
            incurred,
            1 if billable else 0,
            user["id"],
            now_iso(),
        ),
    )
    log_event(user["id"], None, "property.expense", f"{description[:80]} {format_money(amount_cents)}")
    rentals.log_activity(
        property_row["owner_id"],
        property_row["id"],
        user["id"],
        "property.expense",
        "Property cost recorded",
        f"{description[:80]} - {format_money(amount_cents)}",
        href=url_for("rentals.expenses", property=property_row["id"]),
    )
    return {"id": expense_id, "amount_cents": amount_cents}
