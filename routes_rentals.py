"""Property Management: properties, tenants, leases, rent invoices and receipts.

This blueprint is the Property Management door of YaVaKa. Rental management is
the bonus module inside it: the main Project Management system runs a build from
the stand to handover, and this picks the building up afterwards and keeps the
rent and the periodic checks in the same record.

Every route is gated by ``portal_required(PROPERTY)``, so a project-only account
cannot reach it by typing a URL.
"""

import csv
import io
import re
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)

import auth
import portals
import rentals
import web
from auth import accessible_properties, portal_required, require_property
from db import execute, log_event, new_id, now_iso, query
from money import format_money, parse_money_to_cents
from notifications import email_configured, send_email_async
from routes_documents import _serve_attachment
from stages import PAYMENT_METHODS
from storage import UploadError, read_attachment, save_upload
from whatsapp import normalize_phone, send_whatsapp_text, whatsapp_configured

bp = Blueprint("rentals", __name__)

VALID_METHODS = {value for value, _label in PAYMENT_METHODS}
SIGNATURE_PATTERN = re.compile(r"^data:image/(png|jpeg);base64,[A-Za-z0-9+/=]+$")


def _retryable(error: Exception) -> bool:
    """True only when the write lost a race for a generated reference.

    Swallowing every failure would turn a real constraint error into a
    misleading "could not allocate a number" five times over.
    """
    text = str(error).lower()
    return "unique" in text or "duplicate key" in text


def _scope():
    """Owner filter: staff see the whole portfolio, everyone else their own."""
    return None if g.user["role"] == "admin" else g.user["id"]


def _owner_name(property_row):
    owner = query("SELECT name FROM users WHERE id = ?", (property_row["owner_id"],), one=True)
    return owner["name"] if owner else "The account holder"


def _choice_label(choices, value) -> str:
    for key, label in choices:
        if key == value:
            return label
    return (value or "").replace("_", " ").title()


def _int(raw, default=0, low=0, high=999) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _money_value(raw) -> int:
    return max(0, parse_money_to_cents(raw))


def _store_property_upload(property_row, upload, kind="document", check_id=None):
    """Files a document or photo against the property, in the shared vault."""
    if not upload or not upload.filename:
        return None
    try:
        file_row = save_upload(upload, kind)
    except UploadError as error:
        flash(str(error), "error")
        return None

    attachment_id = new_id()
    execute(
        """INSERT INTO attachments
             (id, project_id, transaction_id, uploader_id, kind, filename, original_name,
              mime_type, size, created_at, data, category, property_id, check_id)
           VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            attachment_id,
            g.user["id"],
            "photo" if file_row["category"] == "image" else kind,
            file_row["filename"],
            file_row["original_name"],
            file_row["mime_type"],
            file_row["size"],
            now_iso(),
            file_row["data"],
            file_row["category"],
            property_row["id"],
            check_id,
        ),
    )
    return attachment_id


def _csv_amount(cents) -> str:
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def _csv_safe(value) -> str:
    text = str(value or "")
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _property_scope(property_row):
    return {"id": property_row["id"], "owner_id": property_row["owner_id"]}


def _period_bounds(period: str):
    try:
        year, month = (int(part) for part in str(period).split("-", 1))
        start = date(year, month, 1)
    except (TypeError, ValueError):
        start = date.today().replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return start, end


def _due_date(start: date, billing_day: int) -> str:
    last_day = ((start + timedelta(days=32)).replace(day=1) - timedelta(days=1)).day
    return start.replace(day=max(1, min(billing_day, last_day))).isoformat()


def _invoice_rows(owner_id, status="all", limit=200):
    where, params = [], []
    if owner_id:
        where.append("i.owner_id = ?")
        params.append(owner_id)
    if status in {"issued", "part_paid", "paid", "void"}:
        where.append("i.status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = query(
        f"""SELECT i.*, pr.name AS property_name, pr.code AS property_code,
                   t.name AS tenant_name, t.phone AS tenant_phone,
                   COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                             WHERE p.invoice_id = i.id), 0) AS paid
            FROM property_invoices i
            JOIN properties pr ON pr.id = i.property_id
            LEFT JOIN property_tenants t ON t.id = i.tenant_id
            {clause}
            ORDER BY i.period_start DESC, i.created_at DESC
            LIMIT ?""",
        [*params, limit],
    )
    for row in rows:
        row["balance_cents"] = max(0, int(row["amount_cents"] or 0) - int(row["paid"] or 0))
    return rows


def _lease_rows(owner_id, status="all"):
    where, params = [], []
    if owner_id:
        where.append("l.owner_id = ?")
        params.append(owner_id)
    if status in {"awaiting_signature", "signed", "ended", "void"}:
        where.append("l.status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return query(
        f"""SELECT l.*, pr.name AS property_name, pr.code AS property_code,
                   t.name AS tenant_name
            FROM property_leases l
            JOIN properties pr ON pr.id = l.property_id
            JOIN property_tenants t ON t.id = l.tenant_id
            {clause}
            ORDER BY l.created_at DESC""",
        params,
    )


# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------


@bp.get("/property")
@portal_required(portals.PROPERTY)
def dashboard():
    owner_id = _scope()
    totals = rentals.dashboard_totals(owner_id)
    properties = rentals.portfolio(owner_id)[:6]
    arrears = rentals.arrears(owner_id, limit=6)
    checks = rentals.open_checks(owner_id, limit=4)
    recent_checks = rentals.recent_checks(owner_id, limit=3)
    recent_payments = query(
        """SELECT pay.*, pr.name AS property_name, t.name AS tenant_name
           FROM property_payments pay
           JOIN properties pr ON pr.id = pay.property_id
           LEFT JOIN property_tenants t ON t.id = pay.tenant_id
           WHERE (? IS NULL OR pay.owner_id = ?)
           ORDER BY pay.received_at DESC, pay.created_at DESC
           LIMIT 6""",
        (owner_id, owner_id),
    )
    unsigned = query(
        """SELECT l.*, pr.name AS property_name, t.name AS tenant_name
           FROM property_leases l
           JOIN properties pr ON pr.id = l.property_id
           JOIN property_tenants t ON t.id = l.tenant_id
           WHERE l.status = 'awaiting_signature' AND (? IS NULL OR l.owner_id = ?)
           ORDER BY l.created_at DESC LIMIT 5""",
        (owner_id, owner_id),
    )
    trend = rentals.collection_trend(owner_id, months=6)
    aging = rentals.arrears_aging(owner_id)
    expiring = rentals.expiring_leases(owner_id, days=60)
    work_orders = rentals.open_work_orders(owner_id, limit=5)
    activity = rentals.recent_activity(owner_id, limit=8)
    reminders = rentals.reminders_due(owner_id, limit=50)
    peak = max([1] + [max(item["expected"], item["collected"]) for item in trend])

    return render_template(
        "property/dashboard.html",
        title="Property Management",
        active="property_dashboard",
        totals=totals,
        properties=properties,
        arrears=arrears,
        checks=checks,
        recent_checks=recent_checks,
        recent_payments=recent_payments,
        unsigned_leases=unsigned,
        trend=trend,
        peak=peak,
        aging=aging,
        expiring=expiring,
        work_orders=work_orders,
        activity=activity,
        reminders=reminders,
        today=date.today().isoformat(),
    )


# ----------------------------------------------------------------------
# Properties
# ----------------------------------------------------------------------


@bp.get("/property/properties")
@portal_required(portals.PROPERTY)
def properties():
    owner_id = _scope()
    status = request.args.get("status", "all")
    search = (request.args.get("q") or "").strip()

    rows = rentals.portfolio(owner_id)
    if status in {"available", "occupied", "maintenance"}:
        rows = [row for row in rows if row["status"] == status]
    if search:
        needle = search.lower()
        rows = [
            row
            for row in rows
            if needle in (row["name"] or "").lower()
            or needle in (row["code"] or "").lower()
            or needle in (row["suburb"] or "").lower()
            or needle in (row["address"] or "").lower()
        ]

    return render_template(
        "property/properties.html",
        title="Properties",
        active="properties",
        properties=rows,
        status=status,
        search=search,
        project_choices=accessible_properties_for_owner(owner_id),
        property_types=rentals.PROPERTY_TYPES,
        property_statuses=rentals.PROPERTY_STATUSES,
    )


def accessible_properties_for_owner(owner_id):
    """Builds an owner may link a rental property to, for the picker."""
    if owner_id:
        return query(
            "SELECT id, name, code FROM projects WHERE owner_id = ? AND archived_at IS NULL ORDER BY created_at DESC",
            (owner_id,),
        )
    return query("SELECT id, name, code FROM projects WHERE archived_at IS NULL ORDER BY created_at DESC")


@bp.post("/property/properties")
@portal_required(portals.PROPERTY)
def create_property():
    name = (request.form.get("name") or "").strip()
    if len(name) < 3:
        flash("Give the property a name people will recognise.", "error")
        return redirect(url_for("rentals.properties"))

    property_type = request.form.get("property_type") or "house"
    if property_type not in {key for key, _label in rentals.PROPERTY_TYPES}:
        property_type = "house"

    project_id = request.form.get("project_id") or None
    if project_id and not query(
        "SELECT id FROM projects WHERE id = ? AND owner_id = ?",
        (project_id, g.user["id"]),
        one=True,
    ):
        # Staff may link any build; everyone else only their own.
        if g.user["role"] != "admin" or not query(
            "SELECT id FROM projects WHERE id = ?", (project_id,), one=True
        ):
            project_id = None

    property_id = None
    for _attempt in range(5):
        code = rentals.property_code()
        try:
            property_id = new_id()
            execute(
                """INSERT INTO properties
                     (id, owner_id, code, name, address, suburb, city, property_type,
                      bedrooms, bathrooms, rent_cents, currency, deposit_months, billing_day,
                      status, value_cents, rates_cents, insurance_cents, insurance_expiry,
                      caretaker_name, caretaker_phone, ya_vaka_checks, project_id, notes,
                      created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, 'available',
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    property_id,
                    g.user["id"],
                    code,
                    name[:120],
                    (request.form.get("address") or "").strip()[:200] or None,
                    (request.form.get("suburb") or "").strip()[:80] or None,
                    (request.form.get("city") or "Harare").strip()[:80] or "Harare",
                    property_type,
                    _int(request.form.get("bedrooms"), 2, 0, 40),
                    _int(request.form.get("bathrooms"), 1, 0, 20),
                    _money_value(request.form.get("rent")),
                    _int(request.form.get("deposit_months"), 1, 0, 12),
                    _int(request.form.get("billing_day"), 1, 1, 28),
                    _money_value(request.form.get("value")),
                    _money_value(request.form.get("rates")),
                    _money_value(request.form.get("insurance")),
                    request.form.get("insurance_expiry") or None,
                    (request.form.get("caretaker_name") or "").strip()[:120] or None,
                    normalize_phone(request.form.get("caretaker_phone") or "") or None,
                    _int(request.form.get("ya_vaka_checks"), 1, 0, 1),
                    project_id,
                    (request.form.get("notes") or "").strip()[:2000] or None,
                    now_iso(),
                    now_iso(),
                ),
            )
            break
        except Exception as error:  # noqa: BLE001 - a reference clash is retried
            property_id = None
            if not _retryable(error):
                raise
            continue
    if not property_id:
        flash("Could not allocate a property reference. Try again.", "error")
        return redirect(url_for("rentals.properties"))

    _store_property_upload({"id": property_id, "owner_id": g.user["id"]}, request.files.get("photo"))
    log_event(g.user["id"], None, "property.created", name[:120])
    rentals.log_activity(
        g.user["id"], property_id, g.user["id"], "property.created", "Property added", name,
        href=url_for("rentals.property_detail", property_id=property_id),
    )
    flash(f"{name} added to your portfolio.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_id))


@bp.get("/property/properties/<property_id>")
@portal_required(portals.PROPERTY)
def property_detail(property_id):
    property_row = require_property(property_id)
    property_row = {**property_row, "owner_name": _owner_name(property_row)}

    tenants = query(
        "SELECT * FROM property_tenants WHERE property_id = ? ORDER BY created_at DESC",
        (property_id,),
    )
    leases = query(
        """SELECT l.*, t.name AS tenant_name FROM property_leases l
           JOIN property_tenants t ON t.id = l.tenant_id
           WHERE l.property_id = ? ORDER BY l.created_at DESC""",
        (property_id,),
    )
    invoices = query(
        """SELECT i.*, t.name AS tenant_name,
                  COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                            WHERE p.invoice_id = i.id), 0) AS paid
           FROM property_invoices i
           LEFT JOIN property_tenants t ON t.id = i.tenant_id
           WHERE i.property_id = ?
           ORDER BY i.period_start DESC, i.created_at DESC""",
        (property_id,),
    )
    for invoice in invoices:
        invoice["balance_cents"] = max(0, int(invoice["amount_cents"] or 0) - int(invoice["paid"] or 0))

    payments = query(
        """SELECT pay.*, t.name AS tenant_name FROM property_payments pay
           LEFT JOIN property_tenants t ON t.id = pay.tenant_id
           WHERE pay.property_id = ?
           ORDER BY pay.received_at DESC, pay.created_at DESC""",
        (property_id,),
    )
    checks = query(
        """SELECT c.*, (SELECT COUNT(*) FROM attachments a WHERE a.check_id = c.id) AS media_count
           FROM property_checks c WHERE c.property_id = ?
           ORDER BY c.created_at DESC""",
        (property_id,),
    )
    media = query(
        """SELECT a.* FROM attachments a
           JOIN property_checks c ON c.id = a.check_id
           WHERE c.property_id = ? ORDER BY a.created_at DESC LIMIT 12""",
        (property_id,),
    )
    documents = query(
        """SELECT * FROM attachments
           WHERE property_id = ? AND check_id IS NULL
           ORDER BY created_at DESC""",
        (property_id,),
    )
    expenses = query(
        """SELECT * FROM property_expenses WHERE property_id = ?
           ORDER BY incurred_at DESC, created_at DESC LIMIT 20""",
        (property_id,),
    )
    work_orders = query(
        """SELECT w.*, t.name AS tenant_name FROM property_work_orders w
           LEFT JOIN property_tenants t ON t.id = w.tenant_id
           WHERE w.property_id = ?
           ORDER BY CASE w.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                    CASE w.priority WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    w.created_at DESC""",
        (property_id,),
    )
    activity = rentals.recent_activity(property_id=property_id, limit=12)
    active_lease = rentals.active_lease(property_id)
    deposit = rentals.deposit_state(active_lease) if active_lease else None
    project = (
        query("SELECT id, name, code FROM projects WHERE id = ?", (property_row["project_id"],), one=True)
        if property_row["project_id"]
        else None
    )
    year_start = f"{date.today().year}-01-01"
    finances = rentals.property_income(property_id, year_start, date.today().isoformat())

    tab = request.args.get("tab") or "overview"
    if tab not in {"overview", "tenants", "leases", "money", "checks", "documents", "maintenance"}:
        tab = "overview"

    return render_template(
        "property/property_detail.html",
        title=property_row["name"],
        active="properties",
        property=property_row,
        tenants=tenants,
        leases=leases,
        invoices=invoices,
        payments=payments,
        checks=checks,
        media=media,
        documents=documents,
        expenses=expenses,
        work_orders=work_orders,
        activity=activity,
        active_lease=active_lease,
        deposit=deposit,
        finances=finances,
        tab=tab,
        project=project,
        property_types=rentals.PROPERTY_TYPES,
        property_statuses=rentals.PROPERTY_STATUSES,
        tenant_statuses=rentals.TENANT_STATUSES,
        check_types=rentals.CHECK_TYPES,
        check_ratings=rentals.CHECK_RATINGS,
        expense_categories=rentals.EXPENSE_CATEGORIES,
        work_order_statuses=rentals.WORK_ORDER_STATUSES,
        work_order_priorities=rentals.WORK_ORDER_PRIORITIES,
        invoice_kinds=rentals.INVOICE_KINDS,
        payment_methods=PAYMENT_METHODS,
        today=date.today().isoformat(),
    )


@bp.post("/property/properties/<property_id>/status")
@portal_required(portals.PROPERTY)
def set_property_status(property_id):
    property_row = require_property(property_id)
    status = request.form.get("status") or ""
    if status not in {"available", "occupied", "maintenance"}:
        flash("Choose a valid property status.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_id))

    execute(
        "UPDATE properties SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), property_id),
    )
    log_event(g.user["id"], None, "property.status", f"{property_row['name']} → {status}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.status",
        "Property status changed", status, href=url_for("rentals.property_detail", property_id=property_id),
    )
    flash("Property status updated.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_id))


# ----------------------------------------------------------------------
# Tenants
# ----------------------------------------------------------------------


@bp.post("/property/properties/<property_id>/tenants")
@portal_required(portals.PROPERTY)
def add_tenant(property_id):
    property_row = require_property(property_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 2:
        flash("Enter the tenant's full name.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_id))

    tenant_id = new_id()
    execute(
        """INSERT INTO property_tenants
             (id, property_id, owner_id, name, email, phone, national_id, status,
              moved_in, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (
            tenant_id,
            property_id,
            property_row["owner_id"],
            name[:120],
            (request.form.get("email") or "").strip().lower()[:120] or None,
            normalize_phone(request.form.get("phone") or "") or None,
            (request.form.get("national_id") or "").strip()[:40] or None,
            request.form.get("moved_in") or date.today().isoformat(),
            (request.form.get("notes") or "").strip()[:1000] or None,
            now_iso(),
            now_iso(),
        ),
    )
    rentals.sync_property_status(property_id)
    log_event(g.user["id"], None, "tenant.added", f"{name[:80]} at {property_row['name'][:60]}")
    rentals.log_activity(
        property_row["owner_id"], property_id, g.user["id"], "tenant.added",
        "Tenant added", name, href=url_for("rentals.property_detail", property_id=property_id),
    )
    flash(f"{name} added to {property_row['name']}. Draft the lease next.", "success")
    return redirect(
        url_for("rentals.new_lease", property=property_id, tenant=tenant_id)
    )


@bp.get("/property/tenants")
@portal_required(portals.PROPERTY)
def tenants():
    owner_id = _scope()
    status = request.args.get("status", "all")
    where, params = [], []
    if owner_id:
        where.append("t.owner_id = ?")
        params.append(owner_id)
    if status in {"active", "notice", "former"}:
        where.append("t.status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = query(
        f"""SELECT t.*, pr.name AS property_name, pr.code AS property_code,
                   (SELECT l.id FROM property_leases l WHERE l.tenant_id = t.id
                     ORDER BY l.created_at DESC LIMIT 1) AS lease_id,
                   (SELECT l.status FROM property_leases l WHERE l.tenant_id = t.id
                     ORDER BY l.created_at DESC LIMIT 1) AS lease_status
            FROM property_tenants t
            JOIN properties pr ON pr.id = t.property_id
            {clause}
            ORDER BY t.created_at DESC""",
        params,
    )
    return render_template(
        "property/tenants.html",
        title="Tenants",
        active="tenants",
        tenants=rows,
        status=status,
        tenant_statuses=rentals.TENANT_STATUSES,
    )


@bp.post("/property/tenants/<tenant_id>/status")
@portal_required(portals.PROPERTY)
def set_tenant_status(tenant_id):
    tenant = query("SELECT * FROM property_tenants WHERE id = ?", (tenant_id,), one=True)
    if not tenant:
        abort(404)
    property_row = require_property(tenant["property_id"])

    status = request.form.get("status") or ""
    if status not in {"active", "notice", "former"}:
        flash("Choose a valid tenant status.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))

    moved_out = request.form.get("moved_out") or (
        date.today().isoformat() if status == "former" else None
    )
    execute(
        "UPDATE property_tenants SET status = ?, moved_out = ?, updated_at = ? WHERE id = ?",
        (status, moved_out, now_iso(), tenant_id),
    )
    if status == "former":
        execute(
            "UPDATE property_leases SET status = 'ended', updated_at = ? WHERE tenant_id = ? AND status = 'signed'",
            (now_iso(), tenant_id),
        )
    rentals.sync_property_status(property_row["id"])
    log_event(g.user["id"], None, "tenant.status", f"{tenant['name'][:60]} → {status}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "tenant.status",
        "Tenant status changed", f"{tenant['name']} → {status}",
        href=url_for("rentals.property_detail", property_id=property_row["id"]),
    )
    flash(f"{tenant['name']} marked {_choice_label(rentals.TENANT_STATUSES, status).lower()}.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))


# ----------------------------------------------------------------------
# Leases
# ----------------------------------------------------------------------


@bp.get("/property/leases")
@portal_required(portals.PROPERTY)
def leases():
    status = request.args.get("status", "all")
    return render_template(
        "property/leases.html",
        title="Leases",
        active="leases",
        leases=_lease_rows(_scope(), status),
        status=status,
        lease_statuses=rentals.LEASE_STATUSES,
    )


@bp.get("/property/leases/new")
@portal_required(portals.PROPERTY)
def new_lease():
    properties = accessible_properties(g.user)
    if not properties:
        flash("Add a property and a tenant before drafting a lease.", "error")
        return redirect(url_for("rentals.properties"))

    property_id = request.args.get("property") or properties[0]["id"]
    property_row = next((row for row in properties if row["id"] == property_id), properties[0])
    tenant_rows = query(
        "SELECT * FROM property_tenants WHERE property_id = ? AND status IN ('active', 'notice') ORDER BY created_at DESC",
        (property_row["id"],),
    )
    tenant_id = request.args.get("tenant") or (tenant_rows[0]["id"] if tenant_rows else "")
    tenant = next((row for row in tenant_rows if row["id"] == tenant_id), None)

    today = date.today()
    end = today.replace(year=today.year + 1) - timedelta(days=1)

    return render_template(
        "property/lease_new.html",
        title="New lease",
        active="leases",
        properties=properties,
        property=property_row,
        tenants=tenant_rows,
        tenant=tenant,
        values={
            "start_date": today.isoformat(),
            "end_date": end.isoformat(),
            "rent": f"{(property_row['rent_cents'] or 0) / 100:.2f}",
            "deposit": f"{((property_row['rent_cents'] or 0) * (property_row['deposit_months'] or 1)) / 100:.2f}",
            "billing_day": property_row["billing_day"] or 1,
            "notice_days": 30,
            "escalation_percent": 10,
            "grace_days": rentals.DEFAULT_GRACE_DAYS,
            "title": f"Lease — {property_row['name']}",
        },
        error=None,
    )


@bp.post("/property/leases")
@portal_required(portals.PROPERTY)
def create_lease():
    property_row = require_property(request.form.get("property_id") or "")
    tenant = query(
        "SELECT * FROM property_tenants WHERE id = ? AND property_id = ?",
        (request.form.get("tenant_id") or "", property_row["id"]),
        one=True,
    )
    if not tenant:
        flash("Choose the tenant this lease is for.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))

    start_date = request.form.get("start_date") or date.today().isoformat()
    end_date = request.form.get("end_date") or None
    rent_cents = parse_money_to_cents(request.form.get("rent"))
    deposit_cents = parse_money_to_cents(request.form.get("deposit"))
    billing_day = _int(request.form.get("billing_day"), 1, 1, 28)
    notice_days = _int(request.form.get("notice_days"), 30, 0, 180)
    grace_days = _int(request.form.get("grace_days"), rentals.DEFAULT_GRACE_DAYS, 0, 60)
    try:
        escalation_percent = max(0.0, min(100.0, float(request.form.get("escalation_percent") or 0)))
    except ValueError:
        escalation_percent = 0.0
    title = (request.form.get("title") or f"Lease — {property_row['name']}").strip()

    if rent_cents <= 0:
        flash("Enter the monthly rent.", "error")
        return redirect(url_for("rentals.new_lease", property=property_row["id"], tenant=tenant["id"]))

    for _attempt in range(5):
        reference = rentals.lease_reference()
        try:
            lease_id = new_id()
            execute(
                """INSERT INTO property_leases
                     (id, owner_id, property_id, tenant_id, reference, title, start_date, end_date,
                      rent_cents, deposit_cents, billing_day, notice_days, terms, tenant_name,
                      tenant_signature, signed_at, status, escalation_percent, grace_days,
                      created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,
                           'awaiting_signature', ?, ?, ?, ?, ?)""",
                (
                    lease_id,
                    property_row["owner_id"],
                    property_row["id"],
                    tenant["id"],
                    reference,
                    title[:160],
                    start_date,
                    end_date,
                    rent_cents,
                    deposit_cents,
                    billing_day,
                    notice_days,
                    rentals.lease_terms(
                        property_row={**property_row, "owner_name": _owner_name(property_row)},
                        tenant=tenant,
                        start_date=start_date,
                        end_date=end_date or "",
                        rent_cents=rent_cents,
                        deposit_cents=deposit_cents,
                        billing_day=billing_day,
                        notice_days=notice_days,
                    ),
                    tenant["name"][:120],
                    escalation_percent,
                    grace_days,
                    g.user["id"],
                    now_iso(),
                    now_iso(),
                ),
            )
            break
        except Exception as error:  # noqa: BLE001 - a reference clash is retried
            if not _retryable(error):
                raise
            continue
    else:
        flash("Could not allocate a lease reference. Try again.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))

    execute(
        "UPDATE properties SET rent_cents = ?, billing_day = ?, updated_at = ? WHERE id = ?",
        (rent_cents, billing_day, now_iso(), property_row["id"]),
    )
    log_event(g.user["id"], None, "lease.created", f"{reference} for {tenant['name'][:60]}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "lease.created",
        "Lease produced", f"{reference} for {tenant['name']}",
        href=url_for("rentals.lease_detail", lease_id=lease_id),
    )
    flash("Lease drafted and waiting for the tenant's signature.", "success")
    return redirect(url_for("rentals.lease_detail", lease_id=lease_id))


@bp.get("/property/leases/<lease_id>")
@portal_required(portals.PROPERTY)
def lease_detail(lease_id):
    lease = query("SELECT * FROM property_leases WHERE id = ?", (lease_id,), one=True)
    if not lease:
        abort(404)
    property_row = require_property(lease["property_id"])
    property_row = {**property_row, "owner_name": _owner_name(property_row)}
    tenant = query("SELECT * FROM property_tenants WHERE id = ?", (lease["tenant_id"],), one=True)
    invoices = query(
        """SELECT i.*, COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                                 WHERE p.invoice_id = i.id), 0) AS paid
           FROM property_invoices i WHERE i.lease_id = ?
           ORDER BY i.period_start DESC""",
        (lease_id,),
    )
    for invoice in invoices:
        invoice["balance_cents"] = max(0, int(invoice["amount_cents"] or 0) - int(invoice["paid"] or 0))

    return render_template(
        "property/lease_detail.html",
        title=lease["title"],
        active="leases",
        lease=lease,
        property=property_row,
        tenant=tenant,
        invoices=invoices,
        deposit=rentals.deposit_state(lease),
        today=date.today().isoformat(),
    )


@bp.post("/property/leases/<lease_id>/sign")
@portal_required(portals.PROPERTY)
def sign_lease(lease_id):
    lease = query("SELECT * FROM property_leases WHERE id = ?", (lease_id,), one=True)
    if not lease:
        abort(404)
    property_row = require_property(lease["property_id"])

    signature = request.form.get("signature") or ""
    signed_name = (request.form.get("signed_name") or lease["tenant_name"]).strip()

    if signature and not SIGNATURE_PATTERN.match(signature):
        flash("The signature could not be read. Try signing again.", "error")
        return redirect(url_for("rentals.lease_detail", lease_id=lease_id))
    if len(signature) > 1_500_000:
        flash("That signature image is too large.", "error")
        return redirect(url_for("rentals.lease_detail", lease_id=lease_id))

    execute(
        """UPDATE property_leases
           SET tenant_signature = ?, signed_at = ?, tenant_name = ?, status = 'signed', updated_at = ?
           WHERE id = ?""",
        (signature or None, now_iso(), signed_name[:120], now_iso(), lease_id),
    )
    rentals.sync_property_status(property_row["id"])
    log_event(g.user["id"], None, "lease.signed", f"{lease['reference']} signed by {signed_name[:60]}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "lease.signed",
        "Lease signed", f"{lease['reference']} by {signed_name}",
        href=url_for("rentals.lease_detail", lease_id=lease_id),
    )
    flash("Lease signed. You can raise this month's rent invoice now.", "success")
    return redirect(url_for("rentals.lease_detail", lease_id=lease_id))


@bp.post("/property/leases/<lease_id>/end")
@portal_required(portals.PROPERTY)
def end_lease(lease_id):
    lease = query("SELECT * FROM property_leases WHERE id = ?", (lease_id,), one=True)
    if not lease:
        abort(404)
    property_row = require_property(lease["property_id"])

    execute(
        "UPDATE property_leases SET status = 'ended', updated_at = ? WHERE id = ?",
        (now_iso(), lease_id),
    )
    execute(
        "UPDATE property_tenants SET status = 'former', moved_out = ?, updated_at = ? WHERE id = ?",
        (date.today().isoformat(), now_iso(), lease["tenant_id"]),
    )
    rentals.sync_property_status(property_row["id"])
    log_event(g.user["id"], None, "lease.ended", lease["reference"])
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "lease.ended",
        "Lease ended", lease["reference"], href=url_for("rentals.property_detail", property_id=property_row["id"]),
    )
    flash("Lease ended and the property released back to available.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))


@bp.get("/property/leases/<lease_id>/print")
@portal_required(portals.PROPERTY)
def lease_print(lease_id):
    lease = query("SELECT * FROM property_leases WHERE id = ?", (lease_id,), one=True)
    if not lease:
        abort(404)
    property_row = require_property(lease["property_id"])
    return render_template(
        "property/lease_print.html",
        lease=lease,
        property=property_row,
        owner_name=_owner_name(property_row),
    )


# ----------------------------------------------------------------------
# Rent invoices
# ----------------------------------------------------------------------


@bp.get("/property/invoices")
@portal_required(portals.PROPERTY)
def invoices():
    status = request.args.get("status", "all")
    return render_template(
        "property/invoices.html",
        title="Rent invoices",
        active="rent_invoices",
        invoices=_invoice_rows(_scope(), status),
        status=status,
        invoice_statuses=rentals.INVOICE_STATUSES,
        invoice_kinds=rentals.INVOICE_KINDS,
        lease_options=_lease_rows(_scope(), "signed"),
        period=date.today().strftime("%Y-%m"),
        reminders=rentals.reminders_due(_scope(), limit=50),
        today=date.today().isoformat(),
    )


def _insert_invoice(*, lease, property_row, period_start: date, period_end: date, amount_cents, due_date, notes, kind="rent"):
    """Create one invoice, retrying only when the reference number collides."""
    for _attempt in range(5):
        number = rentals.invoice_number()
        try:
            invoice_id = new_id()
            execute(
                """INSERT INTO property_invoices
                     (id, owner_id, property_id, lease_id, tenant_id, number, kind, period_start,
                      period_end, due_date, amount_cents, currency, status, notes, issued_at,
                      created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', 'issued', ?, ?, ?, ?)""",
                (
                    invoice_id,
                    property_row["owner_id"],
                    property_row["id"],
                    lease["id"],
                    lease["tenant_id"],
                    number,
                    kind,
                    period_start.isoformat(),
                    period_end.isoformat(),
                    due_date,
                    amount_cents,
                    notes,
                    now_iso(),
                    g.user["id"],
                    now_iso(),
                ),
            )
            return invoice_id, number
        except Exception as error:  # noqa: BLE001
            if not _retryable(error):
                raise
            continue
    return None, None


@bp.post("/property/invoices")
@portal_required(portals.PROPERTY)
def create_invoice():
    lease = query(
        "SELECT * FROM property_leases WHERE id = ?",
        (request.form.get("lease_id") or "",),
        one=True,
    )
    if not lease:
        flash("Choose the signed lease this invoice belongs to.", "error")
        return redirect(url_for("rentals.invoices"))
    property_row = require_property(lease["property_id"])

    start, end = _period_bounds(request.form.get("period"))
    kind = request.form.get("kind") or "rent"
    if kind not in {key for key, _label in rentals.INVOICE_KINDS}:
        kind = "rent"

    amount_cents = parse_money_to_cents(request.form.get("amount")) or (
        int(lease["rent_cents"] or 0) if kind == "rent" else 0
    )
    if amount_cents <= 0:
        flash("Enter the amount to invoice.", "error")
        return redirect(url_for("rentals.invoices"))

    if query(
        "SELECT id FROM property_invoices WHERE lease_id = ? AND period_start = ? AND kind = ?",
        (lease["id"], start.isoformat(), kind),
        one=True,
    ):
        flash("That lease already has this kind of invoice for the month.", "error")
        return redirect(url_for("rentals.invoices"))

    due = request.form.get("due_date") or _due_date(start, lease["billing_day"] or 1)
    invoice_id, number = _insert_invoice(
        lease=lease,
        property_row=property_row,
        period_start=start,
        period_end=end,
        amount_cents=amount_cents,
        due_date=due,
        notes=(request.form.get("notes") or "").strip()[:500] or None,
        kind=kind,
    )
    if not invoice_id:
        flash("Could not allocate an invoice number. Try again.", "error")
        return redirect(url_for("rentals.invoices"))

    log_event(g.user["id"], None, "rent.invoice", f"{number} for {lease['reference']}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "rent.invoice",
        "Rent invoice raised", f"{number} for {lease['reference']}",
        href=url_for("rentals.invoices"),
    )
    flash(f"Invoice {number} raised for {start:%B %Y}.", "success")
    return redirect(url_for("rentals.invoices"))


@bp.post("/property/invoices/generate")
@portal_required(portals.PROPERTY)
def generate_invoices():
    """Raise this month's rent for every signed lease that has not been billed."""
    start, end = _period_bounds(request.form.get("period"))
    owner_id = _scope()

    leases = query(
        """SELECT l.*, pr.name AS property_name FROM property_leases l
           JOIN properties pr ON pr.id = l.property_id
           WHERE l.status = 'signed' AND l.start_date <= ?
             AND (l.end_date IS NULL OR l.end_date >= ?)
             AND (? IS NULL OR l.owner_id = ?)
           ORDER BY pr.name""",
        (end.isoformat(), start.isoformat(), owner_id, owner_id),
    )

    raised, skipped = 0, 0
    for lease in leases:
        if query(
            "SELECT id FROM property_invoices WHERE lease_id = ? AND period_start = ? AND kind = 'rent'",
            (lease["id"], start.isoformat()),
            one=True,
        ):
            skipped += 1
            continue
        property_row = query("SELECT * FROM properties WHERE id = ?", (lease["property_id"],), one=True)
        invoice_id, _number = _insert_invoice(
            lease=lease,
            property_row=property_row,
            period_start=start,
            period_end=end,
            amount_cents=int(lease["rent_cents"] or 0),
            due_date=_due_date(start, lease["billing_day"] or 1),
            notes=None,
            kind="rent",
        )
        if invoice_id:
            raised += 1
        else:
            skipped += 1

    message = f"{raised} rent invoice{'s' if raised != 1 else ''} raised for {start:%B %Y}."
    if skipped:
        message += f" {skipped} lease{'s' if skipped != 1 else ''} already had one."
    flash(message, "success" if raised else "error")
    return redirect(url_for("rentals.invoices"))


@bp.post("/property/invoices/<invoice_id>/void")
@portal_required(portals.PROPERTY)
def void_invoice(invoice_id):
    invoice = query("SELECT * FROM property_invoices WHERE id = ?", (invoice_id,), one=True)
    if not invoice:
        abort(404)
    require_property(invoice["property_id"])

    if rentals.paid_against(invoice_id):
        flash("That invoice has payments against it. Void the receipt first.", "error")
        return redirect(url_for("rentals.invoices"))

    execute("UPDATE property_invoices SET status = 'void' WHERE id = ?", (invoice_id,))
    log_event(g.user["id"], None, "rent.invoice_void", invoice["number"])
    rentals.log_activity(
        invoice["owner_id"], invoice["property_id"], g.user["id"], "rent.invoice_void",
        "Rent invoice voided", invoice["number"], href=url_for("rentals.invoices"),
    )
    flash(f"Invoice {invoice['number']} voided.", "success")
    return redirect(url_for("rentals.invoices"))


@bp.get("/property/invoices/<invoice_id>/print")
@portal_required(portals.PROPERTY)
def invoice_print(invoice_id):
    invoice = query("SELECT * FROM property_invoices WHERE id = ?", (invoice_id,), one=True)
    if not invoice:
        abort(404)
    property_row = require_property(invoice["property_id"])
    tenant = (
        query("SELECT * FROM property_tenants WHERE id = ?", (invoice["tenant_id"],), one=True)
        if invoice["tenant_id"]
        else None
    )
    paid = rentals.paid_against(invoice_id)
    return render_template(
        "property/invoice_print.html",
        invoice=invoice,
        property=property_row,
        tenant=tenant,
        paid=paid,
        balance=max(0, int(invoice["amount_cents"] or 0) - paid),
        owner_name=_owner_name(property_row),
    )


# ----------------------------------------------------------------------
# Receipting rent
# ----------------------------------------------------------------------


@bp.get("/property/payments")
@portal_required(portals.PROPERTY)
def payments():
    owner_id = _scope()
    rows = query(
        """SELECT pay.*, pr.name AS property_name, pr.code AS property_code,
                  t.name AS tenant_name, i.number AS invoice_number
           FROM property_payments pay
           JOIN properties pr ON pr.id = pay.property_id
           LEFT JOIN property_tenants t ON t.id = pay.tenant_id
           LEFT JOIN property_invoices i ON i.id = pay.invoice_id
           WHERE (? IS NULL OR pay.owner_id = ?)
           ORDER BY pay.received_at DESC, pay.created_at DESC
           LIMIT 300""",
        (owner_id, owner_id),
    )
    open_invoices = [
        invoice
        for invoice in _invoice_rows(owner_id, "all")
        if invoice["status"] in {"issued", "part_paid"}
    ]
    return render_template(
        "property/payments.html",
        title="Rent receipts",
        active="rent_payments",
        payments=rows,
        open_invoices=open_invoices,
        properties=accessible_properties(g.user),
        payment_methods=PAYMENT_METHODS,
        today=date.today().isoformat(),
    )


@bp.post("/property/payments")
@portal_required(portals.PROPERTY)
def create_payment():
    invoice = None
    if request.form.get("invoice_id"):
        invoice = query(
            "SELECT * FROM property_invoices WHERE id = ?",
            (request.form.get("invoice_id"),),
            one=True,
        )
        if not invoice:
            flash("That invoice no longer exists.", "error")
            return redirect(url_for("rentals.payments"))

    property_id = invoice["property_id"] if invoice else (request.form.get("property_id") or "")
    property_row = require_property(property_id)

    amount_cents = parse_money_to_cents(request.form.get("amount"))
    if amount_cents <= 0:
        flash("Enter the amount received.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))

    method = request.form.get("method") or "ECOCASH"
    if method not in VALID_METHODS:
        method = "OTHER"

    tenant_id = invoice["tenant_id"] if invoice else None
    if not tenant_id:
        tenant_in_place = rentals.tenant_in_place(property_row["id"])
        tenant_id = tenant_in_place["id"] if tenant_in_place else None

    received_at = request.form.get("received_at") or date.today().isoformat()
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
                    (request.form.get("reference") or "").strip()[:80] or None,
                    f"{received_at}T12:00:00+00:00",
                    (request.form.get("notes") or "").strip()[:500] or None,
                    g.user["id"],
                    now_iso(),
                ),
            )
            break
        except Exception as error:  # noqa: BLE001 - a receipt-number clash is retried
            if not _retryable(error):
                raise
            payment_id = None
            continue

    if not payment_id:
        flash("Could not allocate a receipt number. Try again.", "error")
        return redirect(url_for("rentals.payments"))

    if invoice:
        rentals.refresh_invoice_status(invoice["id"])

    log_event(
        g.user["id"],
        None,
        "rent.receipt",
        f"{receipt} — {amount_cents / 100:.2f} for {property_row['name'][:60]}",
    )
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "rent.receipt",
        "Rent receipted", f"{receipt} — {format_money(amount_cents)}",
        href=url_for("rentals.payment_receipt", payment_id=payment_id),
    )
    flash(f"Receipt {receipt} recorded.", "success")
    return redirect(url_for("rentals.payment_receipt", payment_id=payment_id))


@bp.get("/property/payments/<payment_id>/receipt")
@portal_required(portals.PROPERTY)
def payment_receipt(payment_id):
    payment = query("SELECT * FROM property_payments WHERE id = ?", (payment_id,), one=True)
    if not payment:
        abort(404)
    property_row = require_property(payment["property_id"])
    tenant = (
        query("SELECT * FROM property_tenants WHERE id = ?", (payment["tenant_id"],), one=True)
        if payment["tenant_id"]
        else None
    )
    invoice = (
        query("SELECT * FROM property_invoices WHERE id = ?", (payment["invoice_id"],), one=True)
        if payment["invoice_id"]
        else None
    )
    return render_template(
        "property/payment_receipt.html",
        payment=payment,
        property=property_row,
        tenant=tenant,
        invoice=invoice,
        owner_name=_owner_name(property_row),
    )


# ----------------------------------------------------------------------
# Periodic property checks
# ----------------------------------------------------------------------


@bp.post("/property/properties/<property_id>/checks")
@portal_required(portals.PROPERTY)
def schedule_check(property_id):
    property_row = require_property(property_id)
    check_type = request.form.get("check_type") or "routine"
    if check_type not in {key for key, _label in rentals.CHECK_TYPES}:
        check_type = "routine"

    scheduled_for = request.form.get("scheduled_for") or date.today().isoformat()
    execute(
        """INSERT INTO property_checks
             (id, owner_id, property_id, check_type, scheduled_for, status, created_by,
              created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?)""",
        (new_id(), property_row["owner_id"], property_id, check_type, scheduled_for, g.user["id"], now_iso(), now_iso()),
    )
    log_event(g.user["id"], None, "property.check_scheduled", f"{property_row['name'][:60]} on {scheduled_for}")
    rentals.log_activity(
        property_row["owner_id"], property_id, g.user["id"], "property.check_scheduled",
        "Property check scheduled", scheduled_for,
        href=url_for("rentals.property_detail", property_id=property_id, tab="checks"),
    )
    flash("Check scheduled. It shows on the dashboard until it is completed.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_id))


@bp.post("/property/properties/<property_id>/inspect")
@portal_required(portals.PROPERTY)
def request_inspection(property_id):
    """Ask YaVaKa to go on site and report back.

    The check is the same record the owner can see; what differs is who attends.
    YaVaKa inspects, photographs the building and sends the report to the owner
    on the system, by email and over WhatsApp.
    """
    property_row = require_property(property_id)
    scheduled_for = request.form.get("on") or (date.today() + timedelta(days=7)).isoformat()
    try:
        datetime.strptime(scheduled_for, "%Y-%m-%d")
    except ValueError:
        scheduled_for = (date.today() + timedelta(days=7)).isoformat()

    execute(
        """INSERT INTO property_checks
             (id, owner_id, property_id, check_type, scheduled_for, status, created_by,
              created_at, updated_at)
           VALUES (?, ?, ?, 'routine', ?, 'scheduled', ?, ?, ?)""",
        (new_id(), property_row["owner_id"], property_id, scheduled_for, g.user["id"], now_iso(), now_iso()),
    )
    log_event(g.user["id"], None, "property.check_requested", f"{property_row['name'][:60]} on {scheduled_for}")
    rentals.log_activity(
        property_row["owner_id"], property_id, g.user["id"], "property.check_requested",
        "Inspection requested", f"YaVaKa to attend on {scheduled_for}",
        href=url_for("rentals.property_detail", property_id=property_id, tab="checks"),
    )
    flash(
        f"Inspection requested for {scheduled_for}. YaVaKa will attend, inspect the "
        "building and send the report here, by email and on WhatsApp.",
        "success",
    )
    return redirect(url_for("rentals.property_detail", property_id=property_id, tab="checks"))


@bp.post("/property/checks/<check_id>/complete")
@portal_required(portals.PROPERTY)
def complete_check(check_id):
    check = query("SELECT * FROM property_checks WHERE id = ?", (check_id,), one=True)
    if not check:
        abort(404)
    property_row = require_property(check["property_id"])

    rating = request.form.get("rating") or "good"
    if rating not in {key for key, _label in rentals.CHECK_RATINGS}:
        rating = "good"

    findings = (request.form.get("findings") or "").strip()
    if len(findings) < 10:
        flash("Write a sentence or two about what you found.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))

    conducted_at = request.form.get("conducted_at") or date.today().isoformat()
    execute(
        """UPDATE property_checks
           SET status = 'completed', conducted_at = ?, rating = ?, findings = ?,
               action_required = ?, updated_at = ?
           WHERE id = ?""",
        (
            conducted_at,
            rating,
            findings[:4000],
            (request.form.get("action_required") or "").strip()[:1000] or None,
            now_iso(),
            check_id,
        ),
    )

    saved = 0
    for upload in request.files.getlist("media"):
        if not upload or not upload.filename:
            continue
        try:
            file_row = save_upload(upload, "check")
        except UploadError as error:
            flash(str(error), "error")
            continue
        execute(
            """INSERT INTO attachments
                 (id, project_id, transaction_id, uploader_id, kind, filename, original_name,
                  mime_type, size, created_at, data, category, property_id, check_id)
               VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id(),
                g.user["id"],
                "photo" if file_row["category"] == "image" else "document",
                file_row["filename"],
                file_row["original_name"],
                file_row["mime_type"],
                file_row["size"],
                now_iso(),
                file_row["data"],
                file_row["category"],
                property_row["id"],
                check_id,
            ),
        )
        saved += 1

    log_event(
        g.user["id"],
        None,
        "property.check_completed",
        f"{property_row['name'][:60]} — {rating} ({saved} file{'s' if saved != 1 else ''})",
    )
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.check_completed",
        "Property check completed", f"{rating} ({saved} file{'s' if saved != 1 else ''})",
        href=url_for("rentals.property_detail", property_id=property_row["id"], tab="checks"),
    )

    follow_up = rentals.next_check_date(str(check["check_type"] or ""), from_day=date.today())
    if follow_up:
        execute(
            """INSERT INTO property_checks
                 (id, owner_id, property_id, check_type, scheduled_for, status, created_by,
                  created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?)""",
            (
                new_id(), property_row["owner_id"], property_row["id"], check["check_type"],
                follow_up, g.user["id"], now_iso(), now_iso(),
            ),
        )

    completed = query("SELECT * FROM property_checks WHERE id = ?", (check_id,), one=True)
    delivery = rentals.notify_check(completed)

    channels = [name for name, sent in (("email", delivery["email"]), ("WhatsApp", delivery["whatsapp"])) if sent]
    message = "Check saved to the property record."
    if channels:
        message += f" Sent to you by {' and '.join(channels)}."
    else:
        message += " It is on the property record; email and WhatsApp are not configured on this deployment."
    flash(message, "success")
    return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))


@bp.post("/property/checks/<check_id>/report")
@portal_required(portals.PROPERTY)
def report_check(check_id):
    check = query("SELECT * FROM property_checks WHERE id = ?", (check_id,), one=True)
    if not check:
        abort(404)
    property_row = require_property(check["property_id"])

    delivery = rentals.notify_check(check)
    channels = [name for name, sent in (("email", delivery["email"]), ("WhatsApp", delivery["whatsapp"])) if sent]
    if channels:
        flash(f"Check resent by {' and '.join(channels)}.", "success")
    else:
        flash("Nothing was sent: email and WhatsApp are not configured on this deployment.", "error")
    return redirect(url_for("rentals.property_detail", property_id=property_row["id"]))


@bp.get("/property/media/<attachment_id>")
@portal_required(portals.PROPERTY)
def media(attachment_id):
    attachment = query("SELECT * FROM attachments WHERE id = ?", (attachment_id,), one=True)
    if not attachment or not attachment.get("property_id"):
        abort(404)
    property_row = query("SELECT * FROM properties WHERE id = ?", (attachment["property_id"],), one=True)
    if not auth.can_manage_property(g.user, property_row):
        abort(404)
    if read_attachment(attachment) is None:
        abort(404)
    return _serve_attachment(attachment, as_download=request.args.get("download") == "1")

# ----------------------------------------------------------------------
# Editing a property, its documents and its photos
# ----------------------------------------------------------------------


@bp.post("/property/properties/<property_id>/edit")
@portal_required(portals.PROPERTY)
def edit_property(property_id):
    property_row = require_property(property_id)
    name = (request.form.get("name") or "").strip()
    if len(name) < 3:
        flash("Give the property a name people will recognise.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_id))

    property_type = request.form.get("property_type") or "house"
    if property_type not in {key for key, _label in rentals.PROPERTY_TYPES}:
        property_type = "house"

    project_id = request.form.get("project_id") or None
    if project_id and not query("SELECT id FROM projects WHERE id = ?", (project_id,), one=True):
        project_id = None

    execute(
        """UPDATE properties
           SET name = ?, address = ?, suburb = ?, city = ?, property_type = ?,
               bedrooms = ?, bathrooms = ?, rent_cents = ?, deposit_months = ?, billing_day = ?,
               value_cents = ?, rates_cents = ?, insurance_cents = ?, insurance_expiry = ?,
               caretaker_name = ?, caretaker_phone = ?, ya_vaka_checks = ?, project_id = ?,
               notes = ?, updated_at = ?
           WHERE id = ?""",
        (
            name[:120],
            (request.form.get("address") or "").strip()[:200] or None,
            (request.form.get("suburb") or "").strip()[:80] or None,
            (request.form.get("city") or "Harare").strip()[:80] or "Harare",
            property_type,
            _int(request.form.get("bedrooms"), 2, 0, 40),
            _int(request.form.get("bathrooms"), 1, 0, 20),
            _money_value(request.form.get("rent")),
            _int(request.form.get("deposit_months"), 1, 0, 12),
            _int(request.form.get("billing_day"), 1, 1, 28),
            _money_value(request.form.get("value")),
            _money_value(request.form.get("rates")),
            _money_value(request.form.get("insurance")),
            request.form.get("insurance_expiry") or None,
            (request.form.get("caretaker_name") or "").strip()[:120] or None,
            normalize_phone(request.form.get("caretaker_phone") or "") or None,
            _int(request.form.get("ya_vaka_checks"), 1, 0, 1),
            project_id,
            (request.form.get("notes") or "").strip()[:2000] or None,
            now_iso(),
            property_id,
        ),
    )
    _store_property_upload(property_row, request.files.get("photo"))
    log_event(g.user["id"], None, "property.updated", name[:120])
    rentals.log_activity(
        property_row["owner_id"], property_id, g.user["id"], "property.updated",
        "Property details updated", name,
        href=url_for("rentals.property_detail", property_id=property_id),
    )
    flash("Property updated.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_id, tab="overview"))


@bp.post("/property/properties/<property_id>/documents")
@portal_required(portals.PROPERTY)
def upload_property_document(property_id):
    property_row = require_property(property_id)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a document or photo to upload.", "error")
        return redirect(url_for("rentals.property_detail", property_id=property_id, tab="documents"))

    saved = _store_property_upload(property_row, upload)
    if saved:
        label = (request.form.get("label") or upload.filename or "")[:120]
        log_event(g.user["id"], None, "property.document", label)
        rentals.log_activity(
            property_row["owner_id"], property_id, g.user["id"], "property.document",
            "Document added", label,
            href=url_for("rentals.property_detail", property_id=property_id, tab="documents"),
        )
        flash("Document filed with the property.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_id, tab="documents"))


@bp.post("/property/documents/<attachment_id>/delete")
@portal_required(portals.PROPERTY)
def delete_property_document(attachment_id):
    attachment = query("SELECT * FROM attachments WHERE id = ?", (attachment_id,), one=True)
    if not attachment or not attachment.get("property_id") or attachment.get("check_id"):
        abort(404)
    property_row = require_property(attachment["property_id"])

    execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    log_event(g.user["id"], None, "property.document_deleted", attachment["original_name"])
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.document_deleted",
        "Document removed", attachment["original_name"],
        href=url_for("rentals.property_detail", property_id=property_row["id"], tab="documents"),
    )
    flash("Document removed.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_row["id"], tab="documents"))


# ----------------------------------------------------------------------
# Tenant account and statement
# ----------------------------------------------------------------------


@bp.get("/property/tenants/<tenant_id>")
@portal_required(portals.PROPERTY)
def tenant_detail(tenant_id):
    tenant = query("SELECT * FROM property_tenants WHERE id = ?", (tenant_id,), one=True)
    if not tenant:
        abort(404)
    property_row = require_property(tenant["property_id"])

    entries = rentals.tenant_statement(tenant_id)
    leases = query(
        "SELECT * FROM property_leases WHERE tenant_id = ? ORDER BY created_at DESC",
        (tenant_id,),
    )
    balance = entries[-1]["balance"] if entries else 0
    invoices = query(
        """SELECT i.*, COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                                 WHERE p.invoice_id = i.id), 0) AS paid
           FROM property_invoices i WHERE i.tenant_id = ?
           ORDER BY i.period_start DESC, i.created_at DESC""",
        (tenant_id,),
    )
    payments = query(
        "SELECT * FROM property_payments WHERE tenant_id = ? ORDER BY received_at DESC, created_at DESC",
        (tenant_id,),
    )

    return render_template(
        "property/tenant_detail.html",
        title=tenant["name"],
        active="tenants",
        tenant=tenant,
        property=property_row,
        entries=entries,
        balance=balance,
        leases=leases,
        invoices=invoices,
        payments=payments,
        tenant_statuses=rentals.TENANT_STATUSES,
        payment_methods=PAYMENT_METHODS,
        today=date.today().isoformat(),
    )


@bp.get("/property/tenants/<tenant_id>/statement")
@portal_required(portals.PROPERTY)
def tenant_statement_print(tenant_id):
    tenant = query("SELECT * FROM property_tenants WHERE id = ?", (tenant_id,), one=True)
    if not tenant:
        abort(404)
    property_row = require_property(tenant["property_id"])
    entries = rentals.tenant_statement(tenant_id)
    return render_template(
        "property/tenant_statement.html",
        tenant=tenant,
        property=property_row,
        owner_name=_owner_name(property_row),
        entries=entries,
        balance=entries[-1]["balance"] if entries else 0,
        generated=date.today(),
    )


# ----------------------------------------------------------------------
# Lease lifecycle: deposit and renewal
# ----------------------------------------------------------------------


@bp.post("/property/leases/<lease_id>/deposit")
@portal_required(portals.PROPERTY)
def lease_deposit(lease_id):
    lease = query("SELECT * FROM property_leases WHERE id = ?", (lease_id,), one=True)
    if not lease:
        abort(404)
    property_row = require_property(lease["property_id"])
    action = request.form.get("action") or "receive"

    if action == "receive":
        execute(
            "UPDATE property_leases SET deposit_paid_at = ?, updated_at = ? WHERE id = ?",
            (request.form.get("received_on") or date.today().isoformat(), now_iso(), lease_id),
        )
        title, detail = "Deposit received", format_money(lease["deposit_cents"])
    elif action == "refund":
        refund = _money_value(request.form.get("amount")) or int(lease["deposit_cents"] or 0)
        refund = min(refund, int(lease["deposit_cents"] or 0))
        execute(
            """UPDATE property_leases
               SET deposit_refund_cents = ?, deposit_refunded_at = ?, updated_at = ?
               WHERE id = ?""",
            (refund, request.form.get("refunded_on") or date.today().isoformat(), now_iso(), lease_id),
        )
        title, detail = "Deposit refunded", format_money(refund)
    else:
        flash("Choose whether the deposit was received or refunded.", "error")
        return redirect(url_for("rentals.lease_detail", lease_id=lease_id))

    log_event(g.user["id"], None, "property.deposit", f"{title} - {lease['reference']}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.deposit",
        title, f"{lease['reference']} {detail}",
        href=url_for("rentals.lease_detail", lease_id=lease_id),
    )
    flash(f"{title} recorded.", "success")
    return redirect(url_for("rentals.lease_detail", lease_id=lease_id))


@bp.post("/property/leases/<lease_id>/renew")
@portal_required(portals.PROPERTY)
def renew_lease(lease_id):
    lease = query("SELECT * FROM property_leases WHERE id = ?", (lease_id,), one=True)
    if not lease:
        abort(404)
    property_row = require_property(lease["property_id"])
    tenant = query("SELECT * FROM property_tenants WHERE id = ?", (lease["tenant_id"],), one=True)
    if not tenant:
        abort(404)

    start_raw = request.form.get("start_date") or date.today().isoformat()
    try:
        start = date.fromisoformat(start_raw)
    except ValueError:
        start = date.today()
    end = request.form.get("end_date") or None
    rent_cents = _money_value(request.form.get("rent")) or int(lease["rent_cents"] or 0)
    deposit_cents = _money_value(request.form.get("deposit")) or int(lease["deposit_cents"] or 0)
    escalation = request.form.get("escalation_percent")
    try:
        escalation_percent = (
            max(0.0, float(escalation))
            if escalation not in (None, "")
            else float(lease["escalation_percent"] or 0)
        )
    except ValueError:
        escalation_percent = float(lease["escalation_percent"] or 0)

    previous_end = (start - timedelta(days=1)).isoformat()
    execute(
        "UPDATE property_leases SET status = 'ended', end_date = ?, updated_at = ? WHERE id = ?",
        (previous_end, now_iso(), lease_id),
    )

    new_lease_id = None
    for _attempt in range(5):
        reference = rentals.lease_reference()
        try:
            new_lease_id = new_id()
            execute(
                """INSERT INTO property_leases
                     (id, owner_id, property_id, tenant_id, reference, title, start_date, end_date,
                      rent_cents, deposit_cents, billing_day, notice_days, terms, tenant_name,
                      tenant_signature, signed_at, status, escalation_percent, grace_days,
                      deposit_paid_at, renewed_from, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,
                           'awaiting_signature', ?, ?, NULL, ?, ?, ?, ?)""",
                (
                    new_lease_id,
                    property_row["owner_id"],
                    property_row["id"],
                    tenant["id"],
                    reference,
                    f"Lease - {property_row['name']}"[:160],
                    start.isoformat(),
                    end,
                    rent_cents,
                    deposit_cents,
                    _int(lease["billing_day"], 1, 1, 28),
                    _int(lease["notice_days"], 30, 0, 180),
                    rentals.lease_terms(
                        property_row={**property_row, "owner_name": _owner_name(property_row)},
                        tenant=tenant,
                        start_date=start.isoformat(),
                        end_date=end or "",
                        rent_cents=rent_cents,
                        deposit_cents=deposit_cents,
                        billing_day=_int(lease["billing_day"], 1, 1, 28),
                        notice_days=_int(lease["notice_days"], 30, 0, 180),
                    ),
                    tenant["name"][:120],
                    escalation_percent,
                    _int(lease["grace_days"], rentals.DEFAULT_GRACE_DAYS, 0, 60),
                    lease_id,
                    g.user["id"],
                    now_iso(),
                    now_iso(),
                ),
            )
            break
        except Exception as error:  # noqa: BLE001
            new_lease_id = None
            if not _retryable(error):
                raise
            continue

    if not new_lease_id:
        execute(
            "UPDATE property_leases SET status = 'signed', end_date = ?, updated_at = ? WHERE id = ?",
            (lease["end_date"], now_iso(), lease_id),
        )
        flash("Could not allocate a lease reference. Try again.", "error")
        return redirect(url_for("rentals.lease_detail", lease_id=lease_id))

    execute(
        "UPDATE properties SET rent_cents = ?, updated_at = ? WHERE id = ?",
        (rent_cents, now_iso(), property_row["id"]),
    )
    log_event(g.user["id"], None, "property.renewed", f"{lease['reference']} renewed")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.renewed",
        "Lease renewed", f"{lease['reference']} renewed from {start.isoformat()}",
        href=url_for("rentals.lease_detail", lease_id=new_lease_id),
    )
    flash("Lease renewed. The new lease is waiting for the tenant's signature.", "success")
    return redirect(url_for("rentals.lease_detail", lease_id=new_lease_id))


# ----------------------------------------------------------------------
# Reminders and reversals
# ----------------------------------------------------------------------


def _reminder_body(invoice, property_row, tenant) -> str:
    balance = max(0, int(invoice["amount_cents"] or 0) - rentals.paid_against(invoice["id"]))
    lines = [
        f"Rent reminder - {property_row['name']} ({property_row['code']})",
        f"Invoice {invoice['number']} for {str(invoice['period_start'])[:7]}",
        f"Due date: {str(invoice['due_date'])[:10]}",
        f"Still outstanding: {format_money(balance)}",
    ]
    if tenant:
        lines.insert(0, f"Hello {tenant['name']},")
    lines += [
        "",
        "Please pay the outstanding amount and ask for a YaVaKa receipt against the invoice number.",
        "If you have already paid, send the payment reference so it can be matched.",
    ]
    return "\n".join(lines)


def _send_reminder(invoice, property_row):
    tenant = (
        query("SELECT * FROM property_tenants WHERE id = ?", (invoice["tenant_id"],), one=True)
        if invoice.get("tenant_id")
        else None
    )
    body = _reminder_body(invoice, property_row, tenant)
    sent = {"email": False, "whatsapp": False}
    if tenant:
        if email_configured() and tenant.get("email"):
            sent["email"] = bool(
                send_email_async(tenant["email"], f"Rent reminder: {property_row['name']}", body)
            )
        phone = normalize_phone(tenant.get("phone") or "")
        if whatsapp_configured() and phone:
            try:
                outcome = send_whatsapp_text(phone, body)
                sent["whatsapp"] = outcome.get("status") in {"sent", "queued", "simulated"}
            except Exception:  # noqa: BLE001 - a failed reminder must not lose the record
                pass
    return sent


@bp.post("/property/invoices/<invoice_id>/remind")
@portal_required(portals.PROPERTY)
def remind_invoice(invoice_id):
    invoice = query("SELECT * FROM property_invoices WHERE id = ?", (invoice_id,), one=True)
    if not invoice:
        abort(404)
    property_row = require_property(invoice["property_id"])
    if invoice["status"] in {"paid", "void"}:
        flash("That invoice is settled or void, so there is nothing to remind about.", "error")
        return redirect(url_for("rentals.invoices"))

    sent = _send_reminder(invoice, property_row)
    channels = [name for name, ok in (("email", sent["email"]), ("WhatsApp", sent["whatsapp"])) if ok]
    if channels:
        rentals.log_activity(
            property_row["owner_id"], property_row["id"], g.user["id"], "rent.reminder",
            "Rent reminder sent", f"{invoice['number']} by {' and '.join(channels)}",
            href=url_for("rentals.invoices"),
        )
        flash(f"Reminder sent by {' and '.join(channels)}.", "success")
    else:
        flash(
            "Nothing was sent: the tenant has no email on file and WhatsApp/email is not configured.",
            "error",
        )
    return redirect(url_for("rentals.invoices"))


@bp.post("/property/invoices/remind-overdue")
@portal_required(portals.PROPERTY)
def remind_overdue():
    owner_id = _scope()
    rows = rentals.reminders_due(owner_id, limit=50)
    sent = 0
    for invoice in rows:
        property_row = query("SELECT * FROM properties WHERE id = ?", (invoice["property_id"],), one=True)
        outcome = _send_reminder(invoice, property_row)
        if outcome["email"] or outcome["whatsapp"]:
            sent += 1
            rentals.log_activity(
                property_row["owner_id"], property_row["id"], g.user["id"], "rent.reminder",
                "Overdue reminder sent", invoice["number"], href=url_for("rentals.invoices"),
            )

    if sent:
        flash(f"{sent} reminder{'s' if sent != 1 else ''} sent.", "success")
    else:
        flash(
            "No reminders went out: check the tenants' email and phone, and the email/WhatsApp configuration.",
            "error",
        )
    return redirect(url_for("rentals.invoices"))


@bp.post("/property/payments/<payment_id>/reverse")
@portal_required(portals.PROPERTY)
def reverse_payment(payment_id):
    payment = query("SELECT * FROM property_payments WHERE id = ?", (payment_id,), one=True)
    if not payment:
        abort(404)
    property_row = require_property(payment["property_id"])

    execute("DELETE FROM property_payments WHERE id = ?", (payment_id,))
    if payment["invoice_id"]:
        rentals.refresh_invoice_status(payment["invoice_id"])
    log_event(g.user["id"], None, "rent.reversed", payment["receipt_number"])
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "rent.reversed",
        "Receipt reversed", f"{payment['receipt_number']} - {format_money(payment['amount_cents'])}",
        href=url_for("rentals.payments"),
    )
    flash(f"Receipt {payment['receipt_number']} reversed. The invoice is open again.", "success")
    return redirect(url_for("rentals.payments"))


# ----------------------------------------------------------------------
# Property costs
# ----------------------------------------------------------------------


@bp.get("/property/expenses")
@portal_required(portals.PROPERTY)
def expenses():
    owner_id = _scope()
    property_id = request.args.get("property") or ""
    start = request.args.get("from") or f"{date.today().year}-01-01"
    end = request.args.get("to") or date.today().isoformat()

    where, params = [], []
    if owner_id:
        where.append("e.owner_id = ?")
        params.append(owner_id)
    if property_id:
        where.append("e.property_id = ?")
        params.append(property_id)
    where += ["substr(e.incurred_at, 1, 10) >= ?", "substr(e.incurred_at, 1, 10) <= ?"]
    params += [start, end]

    rows = query(
        f"""SELECT e.*, p.name AS property_name, p.code AS property_code
            FROM property_expenses e
            JOIN properties p ON p.id = e.property_id
            WHERE {' AND '.join(where)}
            ORDER BY e.incurred_at DESC, e.created_at DESC
            LIMIT 300""",
        params,
    )
    totals = rentals.expense_total(owner_id, property_id or None, start, end)
    income = rentals.collected_between(owner_id, start, end)
    by_category = rentals.expenses_by_category(owner_id, start, end)

    return render_template(
        "property/expenses.html",
        title="Property costs",
        active="expenses",
        expenses=rows,
        totals=totals,
        income=income,
        net=income - totals,
        by_category=by_category,
        properties=accessible_properties(g.user),
        property_id=property_id,
        expense_categories=rentals.EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        start=start,
        end=end,
        today=date.today().isoformat(),
    )


@bp.post("/property/expenses")
@portal_required(portals.PROPERTY)
def create_expense():
    property_row = require_property(request.form.get("property_id") or "")
    amount = _money_value(request.form.get("amount"))
    description = (request.form.get("description") or "").strip()
    category = request.form.get("category") or "other"
    if category not in {key for key, _label in rentals.EXPENSE_CATEGORIES}:
        category = "other"
    method = request.form.get("method") or "BANK_TRANSFER"
    if method not in VALID_METHODS:
        method = "OTHER"

    if amount <= 0:
        flash("Enter what the cost was.", "error")
        return redirect(url_for("rentals.expenses", property=property_row["id"]))
    if len(description) < 3:
        flash("Add a short description so the cost makes sense later.", "error")
        return redirect(url_for("rentals.expenses", property=property_row["id"]))

    incurred = request.form.get("incurred_at") or date.today().isoformat()
    try:
        datetime.strptime(incurred, "%Y-%m-%d")
    except ValueError:
        incurred = date.today().isoformat()

    execute(
        """INSERT INTO property_expenses
             (id, owner_id, property_id, category, amount_cents, currency, description, method,
              reference, incurred_at, billable_to_tenant, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id(),
            property_row["owner_id"],
            property_row["id"],
            category,
            amount,
            description[:200],
            method,
            (request.form.get("reference") or "").strip()[:80] or None,
            incurred,
            1 if request.form.get("billable") else 0,
            g.user["id"],
            now_iso(),
        ),
    )
    log_event(g.user["id"], None, "property.expense", f"{description[:80]} {format_money(amount)}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.expense",
        "Property cost recorded", f"{description[:80]} - {format_money(amount)}",
        href=url_for("rentals.expenses", property=property_row["id"]),
    )
    flash("Cost recorded.", "success")
    return redirect(url_for("rentals.expenses", property=property_row["id"]))


@bp.post("/property/expenses/<expense_id>/delete")
@portal_required(portals.PROPERTY)
def delete_expense(expense_id):
    expense = query("SELECT * FROM property_expenses WHERE id = ?", (expense_id,), one=True)
    if not expense:
        abort(404)
    property_row = require_property(expense["property_id"])

    execute("DELETE FROM property_expenses WHERE id = ?", (expense_id,))
    log_event(g.user["id"], None, "property.expense_deleted", expense["description"][:80])
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.expense_deleted",
        "Property cost removed", expense["description"][:80],
        href=url_for("rentals.expenses", property=property_row["id"]),
    )
    flash("Cost removed.", "success")
    return redirect(url_for("rentals.expenses", property=property_row["id"]))


# ----------------------------------------------------------------------
# Work orders
# ----------------------------------------------------------------------


@bp.get("/property/work-orders")
@portal_required(portals.PROPERTY)
def work_orders():
    owner_id = _scope()
    status = request.args.get("status", "open")
    where, params = [], []
    if owner_id:
        where.append("w.owner_id = ?")
        params.append(owner_id)
    if status in {"open", "in_progress", "done", "cancelled"}:
        where.append("w.status = ?")
        params.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    rows = query(
        f"""SELECT w.*, p.name AS property_name, p.code AS property_code,
                   t.name AS tenant_name
            FROM property_work_orders w
            JOIN properties p ON p.id = w.property_id
            LEFT JOIN property_tenants t ON t.id = w.tenant_id
            {clause}
            ORDER BY CASE w.priority WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     w.created_at DESC
            LIMIT 200""",
        params,
    )
    return render_template(
        "property/work_orders.html",
        title="Work orders",
        active="work_orders",
        work_orders=rows,
        status=status,
        properties=accessible_properties(g.user),
        work_order_statuses=rentals.WORK_ORDER_STATUSES,
        work_order_priorities=rentals.WORK_ORDER_PRIORITIES,
        expense_categories=rentals.EXPENSE_CATEGORIES,
        today=date.today().isoformat(),
    )


@bp.post("/property/work-orders")
@portal_required(portals.PROPERTY)
def create_work_order():
    property_row = require_property(request.form.get("property_id") or "")
    title = (request.form.get("title") or "").strip()
    if len(title) < 4:
        flash("Say what needs fixing.", "error")
        return redirect(url_for("rentals.work_orders"))

    tenant = rentals.tenant_in_place(property_row["id"])
    priority = request.form.get("priority") or "normal"
    if priority not in {key for key, _label in rentals.WORK_ORDER_PRIORITIES}:
        priority = "normal"

    execute(
        """INSERT INTO property_work_orders
             (id, owner_id, property_id, tenant_id, title, description, priority, status,
              reported_at, scheduled_for, contractor_name, contractor_phone, cost_cents,
              created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)""",
        (
            new_id(),
            property_row["owner_id"],
            property_row["id"],
            tenant["id"] if tenant else None,
            title[:160],
            (request.form.get("description") or "").strip()[:2000] or None,
            priority,
            request.form.get("reported_at") or date.today().isoformat(),
            request.form.get("scheduled_for") or None,
            (request.form.get("contractor_name") or "").strip()[:120] or None,
            normalize_phone(request.form.get("contractor_phone") or "") or None,
            g.user["id"],
            now_iso(),
            now_iso(),
        ),
    )
    log_event(g.user["id"], None, "property.work_order", title[:120])
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.work_order",
        "Work order opened", title,
        href=url_for("rentals.work_orders"),
    )
    flash("Work order opened.", "success")
    return redirect(url_for("rentals.work_orders"))


@bp.post("/property/work-orders/<work_order_id>/status")
@portal_required(portals.PROPERTY)
def update_work_order(work_order_id):
    work_order = query("SELECT * FROM property_work_orders WHERE id = ?", (work_order_id,), one=True)
    if not work_order:
        abort(404)
    property_row = require_property(work_order["property_id"])

    status = request.form.get("status") or "open"
    if status not in {key for key, _label in rentals.WORK_ORDER_STATUSES}:
        status = "open"

    cost = _money_value(request.form.get("cost")) or int(work_order["cost_cents"] or 0)
    expense_id = work_order["expense_id"]

    execute(
        """UPDATE property_work_orders
           SET status = ?, contractor_name = ?, contractor_phone = ?, cost_cents = ?,
               completed_at = ?, updated_at = ?
           WHERE id = ?""",
        (
            status,
            (request.form.get("contractor_name") or "").strip()[:120] or work_order["contractor_name"],
            normalize_phone(request.form.get("contractor_phone") or "") or work_order["contractor_phone"],
            cost,
            date.today().isoformat() if status == "done" else None,
            now_iso(),
            work_order_id,
        ),
    )

    if status == "done" and cost > 0 and not expense_id:
        expense_id = new_id()
        execute(
            """INSERT INTO property_expenses
                 (id, owner_id, property_id, category, amount_cents, currency, description, method,
                  reference, incurred_at, billable_to_tenant, work_order_id, created_by, created_at)
               VALUES (?, ?, ?, 'repairs', ?, 'USD', ?, 'OTHER', NULL, ?, 0, ?, ?, ?)""",
            (
                expense_id,
                property_row["owner_id"],
                property_row["id"],
                cost,
                f"Work order: {work_order['title']}"[:200],
                date.today().isoformat(),
                work_order_id,
                g.user["id"],
                now_iso(),
            ),
        )
        execute(
            "UPDATE property_work_orders SET expense_id = ? WHERE id = ?",
            (expense_id, work_order_id),
        )

    log_event(g.user["id"], None, "property.work_order_status", f"{work_order['title'][:80]} -> {status}")
    rentals.log_activity(
        property_row["owner_id"], property_row["id"], g.user["id"], "property.work_order_status",
        "Work order updated", f"{work_order['title'][:80]} -> {status}",
        href=url_for("rentals.work_orders"),
    )
    suffix = " The cost was added to property expenses." if status == "done" and cost else ""
    flash(f"Work order updated.{suffix}", "success")
    return redirect(url_for("rentals.work_orders"))


# ----------------------------------------------------------------------
# Reports and exports
# ----------------------------------------------------------------------


@bp.get("/property/reports")
@portal_required(portals.PROPERTY)
def reports():
    owner_id = _scope()
    today = date.today()
    year_start = f"{today.year}-01-01"
    income = rentals.collected_between(owner_id, year_start, today.isoformat())
    expenses_total = rentals.expense_total(owner_id, start=year_start)
    by_category = rentals.expenses_by_category(owner_id, start=year_start)
    aging = rentals.arrears_aging(owner_id)
    trend = rentals.collection_trend(owner_id, months=12)
    peak = max([1] + [max(item["expected"], item["collected"]) for item in trend])

    rows = []
    for property_row in rentals.portfolio(owner_id):
        figures = rentals.property_income(property_row["id"], year_start, today.isoformat())
        rent_roll = int(property_row["rent_cents"] or 0)
        value = int(property_row["value_cents"] or 0)
        rows.append(
            {
                **property_row,
                **figures,
                "gross_yield": round((rent_roll * 12 / value) * 100, 2) if value else 0.0,
            }
        )

    return render_template(
        "property/reports.html",
        title="Property reports",
        active="reports",
        totals=rentals.dashboard_totals(owner_id),
        income=income,
        expenses_total=expenses_total,
        net=income - expenses_total,
        by_category=by_category,
        aging=aging,
        trend=trend,
        peak=peak,
        rows=rows,
        year=today.year,
        today=today.isoformat(),
    )


@bp.get("/property/reports/export")
@portal_required(portals.PROPERTY)
def export_report():
    owner_id = _scope()
    dataset = request.args.get("dataset", "invoices")
    today = date.today()

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")

    if dataset == "expenses":
        rows = query(
            """SELECT e.*, p.name AS property_name FROM property_expenses e
               JOIN properties p ON p.id = e.property_id
               WHERE (? IS NULL OR e.owner_id = ?)
               ORDER BY e.incurred_at""",
            (owner_id, owner_id),
        )
        writer.writerow(["Date", "Property", "Category", "Description", "Method", "Reference", "Amount"])
        for row in rows:
            writer.writerow([
                str(row["incurred_at"])[:10],
                _csv_safe(row["property_name"]),
                row["category"],
                _csv_safe(row["description"]),
                row["method"],
                _csv_safe(row["reference"]),
                _csv_amount(row["amount_cents"]),
            ])
    elif dataset == "payments":
        rows = query(
            """SELECT pay.*, p.name AS property_name, t.name AS tenant_name, i.number AS invoice_number
               FROM property_payments pay
               JOIN properties p ON p.id = pay.property_id
               LEFT JOIN property_tenants t ON t.id = pay.tenant_id
               LEFT JOIN property_invoices i ON i.id = pay.invoice_id
               WHERE (? IS NULL OR pay.owner_id = ?)
               ORDER BY pay.received_at""",
            (owner_id, owner_id),
        )
        writer.writerow(["Received", "Receipt", "Property", "Tenant", "Invoice", "Method", "Reference", "Amount"])
        for row in rows:
            writer.writerow([
                str(row["received_at"])[:10],
                row["receipt_number"],
                _csv_safe(row["property_name"]),
                _csv_safe(row["tenant_name"]),
                row["invoice_number"] or "",
                row["method"],
                _csv_safe(row["reference"]),
                _csv_amount(row["amount_cents"]),
            ])
    elif dataset == "arrears":
        writer.writerow(["Due", "Invoice", "Property", "Tenant", "Kind", "Invoiced", "Paid", "Balance"])
        for row in rentals.open_invoices(owner_id, limit=500):
            writer.writerow([
                str(row["due_date"])[:10],
                row["number"],
                _csv_safe(row["property_name"]),
                _csv_safe(row["tenant_name"]),
                row["kind"],
                _csv_amount(row["amount_cents"]),
                _csv_amount(row["paid"]),
                _csv_amount(row["balance_cents"]),
            ])
    else:
        writer.writerow(
            ["Period", "Invoice", "Property", "Tenant", "Kind", "Due", "Invoiced", "Paid", "Balance", "Status"]
        )
        for row in _invoice_rows(owner_id, "all", limit=2000):
            writer.writerow([
                str(row["period_start"])[:10],
                row["number"],
                _csv_safe(row["property_name"]),
                _csv_safe(row["tenant_name"]),
                row["kind"],
                str(row["due_date"])[:10],
                _csv_amount(row["amount_cents"]),
                _csv_amount(row["paid"]),
                _csv_amount(row["balance_cents"]),
                row["status"],
            ])

    response = make_response("\ufeff" + buffer.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="yavaka-property-{dataset}-{today.isoformat()}.csv"'
    )
    return response


# ----------------------------------------------------------------------
# Property search
# ----------------------------------------------------------------------


@bp.get("/property/search")
@portal_required(portals.PROPERTY)
def search():
    owner_id = _scope()
    needle = (request.args.get("q") or "").strip()
    results = {"properties": [], "tenants": [], "leases": [], "invoices": [], "payments": [], "work_orders": []}

    if needle:
        like = f"%{needle}%"
        scope = "(? IS NULL OR {column} = ?)"

        results["properties"] = query(
            f"""SELECT * FROM properties
                WHERE (name LIKE ? OR code LIKE ? OR address LIKE ? OR suburb LIKE ?)
                  AND {scope.format(column='owner_id')}
                ORDER BY name LIMIT 8""",
            [like, like, like, like, owner_id, owner_id],
        )
        results["tenants"] = query(
            f"""SELECT t.*, p.name AS property_name FROM property_tenants t
                JOIN properties p ON p.id = t.property_id
                WHERE (t.name LIKE ? OR t.phone LIKE ? OR t.email LIKE ?)
                  AND {scope.format(column='t.owner_id')}
                ORDER BY t.name LIMIT 8""",
            [like, like, like, owner_id, owner_id],
        )
        results["leases"] = query(
            f"""SELECT l.*, p.name AS property_name FROM property_leases l
                JOIN properties p ON p.id = l.property_id
                WHERE (l.reference LIKE ? OR l.title LIKE ? OR l.tenant_name LIKE ?)
                  AND {scope.format(column='l.owner_id')}
                ORDER BY l.created_at DESC LIMIT 8""",
            [like, like, like, owner_id, owner_id],
        )
        results["invoices"] = query(
            f"""SELECT i.*, p.name AS property_name FROM property_invoices i
                JOIN properties p ON p.id = i.property_id
                WHERE (i.number LIKE ? OR i.notes LIKE ?)
                  AND {scope.format(column='i.owner_id')}
                ORDER BY i.created_at DESC LIMIT 8""",
            [like, like, owner_id, owner_id],
        )
        results["payments"] = query(
            f"""SELECT pay.*, p.name AS property_name FROM property_payments pay
                JOIN properties p ON p.id = pay.property_id
                WHERE (pay.receipt_number LIKE ? OR pay.reference LIKE ?)
                  AND {scope.format(column='pay.owner_id')}
                ORDER BY pay.created_at DESC LIMIT 8""",
            [like, like, owner_id, owner_id],
        )
        results["work_orders"] = query(
            f"""SELECT w.*, p.name AS property_name FROM property_work_orders w
                JOIN properties p ON p.id = w.property_id
                WHERE (w.title LIKE ? OR w.description LIKE ? OR w.contractor_name LIKE ?)
                  AND {scope.format(column='w.owner_id')}
                ORDER BY w.created_at DESC LIMIT 8""",
            [like, like, like, owner_id, owner_id],
        )

    total = sum(len(items) for items in results.values())
    return render_template(
        "property/search.html",
        title="Search",
        active="",
        q=needle,
        results=results,
        total=total,
    )
