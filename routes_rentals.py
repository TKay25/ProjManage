"""Property Management: properties, tenants, leases, rent invoices and receipts.

This blueprint is the Property Management door of YaVaKa. Rental management is
the bonus module inside it: the main Project Management system runs a build from
the stand to handover, and this picks the building up afterwards and keeps the
rent and the periodic checks in the same record.

Every route is gated by ``portal_required(PROPERTY)``, so a project-only account
cannot reach it by typing a URL.
"""

import re
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    g,
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
from money import parse_money_to_cents
from routes_documents import _serve_attachment
from stages import PAYMENT_METHODS
from storage import UploadError, read_attachment, save_upload
from whatsapp import normalize_phone

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

    for _attempt in range(5):
        code = rentals.property_code()
        try:
            execute(
                """INSERT INTO properties
                     (id, owner_id, code, name, address, suburb, city, property_type,
                      bedrooms, bathrooms, rent_cents, currency, deposit_months, billing_day,
                      status, project_id, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, 'available', ?, ?, ?, ?)""",
                (
                    new_id(),
                    g.user["id"],
                    code,
                    name[:120],
                    (request.form.get("address") or "").strip()[:200] or None,
                    (request.form.get("suburb") or "").strip()[:80] or None,
                    (request.form.get("city") or "Harare").strip()[:80] or "Harare",
                    property_type,
                    _int(request.form.get("bedrooms"), 2, 0, 40),
                    _int(request.form.get("bathrooms"), 1, 0, 20),
                    parse_money_to_cents(request.form.get("rent")),
                    _int(request.form.get("deposit_months"), 1, 0, 12),
                    _int(request.form.get("billing_day"), 1, 1, 28),
                    project_id,
                    (request.form.get("notes") or "").strip()[:2000] or None,
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
        flash("Could not allocate a property reference. Try again.", "error")
        return redirect(url_for("rentals.properties"))

    log_event(g.user["id"], None, "property.created", name[:120])
    flash(f"{name} added to your portfolio.", "success")
    return redirect(url_for("rentals.properties"))


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
    project = (
        query("SELECT id, name, code FROM projects WHERE id = ?", (property_row["project_id"],), one=True)
        if property_row["project_id"]
        else None
    )

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
        project=project,
        property_types=rentals.PROPERTY_TYPES,
        property_statuses=rentals.PROPERTY_STATUSES,
        tenant_statuses=rentals.TENANT_STATUSES,
        check_types=rentals.CHECK_TYPES,
        check_ratings=rentals.CHECK_RATINGS,
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
                      tenant_signature, signed_at, status, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,
                           'awaiting_signature', ?, ?, ?)""",
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
        lease_options=_lease_rows(_scope(), "signed"),
        period=date.today().strftime("%Y-%m"),
        today=date.today().isoformat(),
    )


def _insert_invoice(*, lease, property_row, period_start: date, period_end: date, amount_cents, due_date, notes):
    """Create one invoice, retrying only when the reference number collides."""
    for _attempt in range(5):
        number = rentals.invoice_number()
        try:
            invoice_id = new_id()
            execute(
                """INSERT INTO property_invoices
                     (id, owner_id, property_id, lease_id, tenant_id, number, period_start,
                      period_end, due_date, amount_cents, currency, status, notes, issued_at,
                      created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', 'issued', ?, ?, ?, ?)""",
                (
                    invoice_id,
                    property_row["owner_id"],
                    property_row["id"],
                    lease["id"],
                    lease["tenant_id"],
                    number,
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
    lease = query("SELECT * FROM property_leases WHERE id = ?", (request.form.get("lease_id") or ""), one=True)
    if not lease:
        flash("Choose the signed lease this invoice belongs to.", "error")
        return redirect(url_for("rentals.invoices"))
    property_row = require_property(lease["property_id"])

    start, end = _period_bounds(request.form.get("period"))
    amount_cents = parse_money_to_cents(request.form.get("amount")) or int(lease["rent_cents"] or 0)
    if amount_cents <= 0:
        flash("Enter the amount to invoice.", "error")
        return redirect(url_for("rentals.invoices"))

    if query(
        "SELECT id FROM property_invoices WHERE lease_id = ? AND period_start = ?",
        (lease["id"], start.isoformat()),
        one=True,
    ):
        flash("That lease already has an invoice for this month.", "error")
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
    )
    if not invoice_id:
        flash("Could not allocate an invoice number. Try again.", "error")
        return redirect(url_for("rentals.invoices"))

    log_event(g.user["id"], None, "rent.invoice", f"{number} for {lease['reference']}")
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
            "SELECT id FROM property_invoices WHERE lease_id = ? AND period_start = ?",
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
    flash("Check scheduled. It shows on the dashboard until it is completed.", "success")
    return redirect(url_for("rentals.property_detail", property_id=property_id))


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
