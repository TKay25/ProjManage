"""Rental management: the bonus module inside Property Management.

A YaVaKa build ends at handover, but the house does not. This module keeps the
same record going: who lives there, what the lease says, what rent is due, what
was receipted, and what the periodic property check found.

It is deliberately NOT a second Project Management. There are no stages, no
budgets against trades and no build money here — those stay in the main system.
What lives here is the landlord's side of a standing building.
"""

from datetime import date, datetime, timedelta

from db import execute, now_iso, query
from money import format_money

PROPERTY_TYPES = [
    ("house", "House"),
    ("cottage", "Cottage"),
    ("flat", "Flat / apartment"),
    ("cluster", "Cluster home"),
    ("townhouse", "Townhouse"),
    ("commercial", "Commercial unit"),
    ("land", "Stand / land"),
]

PROPERTY_STATUSES = [
    ("available", "Available"),
    ("occupied", "Occupied"),
    ("maintenance", "Under maintenance"),
]

TENANT_STATUSES = [
    ("active", "In place"),
    ("notice", "On notice"),
    ("former", "Moved out"),
]

LEASE_STATUSES = [
    ("awaiting_signature", "Awaiting signature"),
    ("signed", "Signed"),
    ("ended", "Ended"),
    ("void", "Void"),
]

CHECK_TYPES = [
    ("routine", "Routine check"),
    ("quarterly", "Quarterly inspection"),
    ("annual", "Annual inspection"),
    ("move_in", "Move-in inspection"),
    ("move_out", "Move-out inspection"),
    ("repair", "Repair follow-up"),
]

CHECK_RATINGS = [
    ("good", "Good — nothing to do"),
    ("fair", "Fair — small items noted"),
    ("poor", "Poor — action needed"),
]

CHECK_STATUSES = [
    ("scheduled", "Scheduled"),
    ("completed", "Completed"),
]

INVOICE_STATUSES = [
    ("issued", "Issued"),
    ("part_paid", "Part paid"),
    ("paid", "Paid"),
    ("void", "Void"),
]

DEFAULT_LEASE_TERMS = "\n".join(
    [
        "1. The tenant lets the property for the term recorded above and pays the monthly rent on or before the billing day.",
        "2. The deposit is held against damage and unpaid rent, and is refunded within 14 days of a satisfactory move-out inspection.",
        "3. Rent is payable in United States dollars by bank transfer, EcoCash or cash against a YaVaKa receipt.",
        "4. The tenant keeps the property in good order, reports defects promptly and allows the landlord or agent access for periodic checks on reasonable notice.",
        "5. The tenant may not sub-let, alter the property or run a business from it without written consent.",
        "6. Either party may end this lease by giving the notice period recorded above in writing.",
        "7. Water, electricity, rates and refuse charges are for the tenant's account unless recorded otherwise on this lease.",
        "8. A late payment attracts a reminder, then a written notice; persistent non-payment is dealt with under the laws of Zimbabwe.",
        "9. This lease is governed by the laws of Zimbabwe.",
    ]
)


# ----------------------------------------------------------------------
# Reference numbers
# ----------------------------------------------------------------------


def _next_number(prefix: str, table: str, column: str) -> str:
    """Next ``PREFIX-YYYY-0001`` reference.

    The table and column are module constants, never user input, so building the
    query from them is safe. The suffix is read from the rows rather than a
    counter table, which keeps the number meaningful after a restore.
    """
    stem = f"{prefix}-{datetime.now():%Y}-"
    rows = query(
        f"SELECT {column} AS reference FROM {table} WHERE {column} LIKE ?",
        (stem + "%",),
    )
    highest = 0
    for row in rows:
        suffix = str(row["reference"] or "")[len(stem) :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{stem}{highest + 1:04d}"


def invoice_number() -> str:
    return _next_number("INV", "property_invoices", "number")


def lease_reference() -> str:
    return _next_number("LEASE", "property_leases", "reference")


def receipt_number() -> str:
    return _next_number("RCPT", "property_payments", "receipt_number")


def property_code() -> str:
    return _next_number("PROP", "properties", "code")


# ----------------------------------------------------------------------
# Reading the portfolio
# ----------------------------------------------------------------------


def _month_bounds(day: date | None = None):
    day = day or date.today()
    start = day.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start.isoformat(), (next_month - timedelta(days=1)).isoformat()


def monthly_rent_roll(owner_id: str | None = None) -> int:
    """Rent on the signed leases that are running today."""
    today = date.today().isoformat()
    where = [
        "l.status = 'signed'",
        "l.start_date <= ?",
        "(l.end_date IS NULL OR l.end_date >= ?)",
    ]
    params = [today, today]
    if owner_id:
        where.append("l.owner_id = ?")
        params.append(owner_id)
    row = query(
        f"SELECT COALESCE(SUM(l.rent_cents), 0) AS total FROM property_leases l WHERE {' AND '.join(where)}",
        params,
        one=True,
    )
    return int(row["total"] or 0)


def collected_between(owner_id: str | None, start: str, end: str) -> int:
    where = ["substr(received_at, 1, 10) BETWEEN ? AND ?"]
    params = [start, end]
    if owner_id:
        where.append("owner_id = ?")
        params.append(owner_id)
    row = query(
        f"SELECT COALESCE(SUM(amount_cents), 0) AS total FROM property_payments WHERE {' AND '.join(where)}",
        params,
        one=True,
    )
    return int(row["total"] or 0)


def paid_against(invoice_id: str) -> int:
    row = query(
        "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM property_payments WHERE invoice_id = ?",
        (invoice_id,),
        one=True,
    )
    return int(row["total"] or 0)


def invoice_balance(invoice) -> int:
    return max(0, int(invoice["amount_cents"] or 0) - paid_against(invoice["id"]))


def outstanding_total(owner_id: str | None = None) -> int:
    where = ["i.status IN ('issued', 'part_paid')"]
    params = []
    if owner_id:
        where.append("i.owner_id = ?")
        params.append(owner_id)
    rows = query(
        f"""SELECT i.id, i.amount_cents,
                   COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                             WHERE p.invoice_id = i.id), 0) AS paid
            FROM property_invoices i
            WHERE {' AND '.join(where)}""",
        params,
    )
    return sum(max(0, int(row["amount_cents"] or 0) - int(row["paid"] or 0)) for row in rows)


def open_invoices(owner_id: str | None = None, limit: int = 20):
    """Issued invoices that still carry something to collect."""
    where = ["i.status IN ('issued', 'part_paid')"]
    params = []
    if owner_id:
        where.append("i.owner_id = ?")
        params.append(owner_id)
    rows = query(
        f"""SELECT i.*, pr.name AS property_name, pr.code AS property_code,
                   t.name AS tenant_name,
                   COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                             WHERE p.invoice_id = i.id), 0) AS paid
            FROM property_invoices i
            JOIN properties pr ON pr.id = i.property_id
            LEFT JOIN property_tenants t ON t.id = i.tenant_id
            WHERE {' AND '.join(where)}
            ORDER BY i.due_date ASC
            LIMIT ?""",
        [*params, limit],
    )
    for row in rows:
        row["balance_cents"] = max(0, int(row["amount_cents"] or 0) - int(row["paid"] or 0))
    return rows


def arrears(owner_id: str | None = None, limit: int = 12):
    """Issued invoices that are past their due date and still carry a balance."""
    where = [
        "i.status IN ('issued', 'part_paid')",
        "substr(i.due_date, 1, 10) < ?",
    ]
    params = [date.today().isoformat()]
    if owner_id:
        where.append("i.owner_id = ?")
        params.append(owner_id)

    rows = query(
        f"""SELECT i.*, pr.name AS property_name, pr.code AS property_code,
                   t.name AS tenant_name, t.phone AS tenant_phone,
                   COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                             WHERE p.invoice_id = i.id), 0) AS paid
            FROM property_invoices i
            JOIN properties pr ON pr.id = i.property_id
            LEFT JOIN property_tenants t ON t.id = i.tenant_id
            WHERE {' AND '.join(where)}
            ORDER BY i.due_date ASC
            LIMIT ?""",
        [*params, limit],
    )
    for row in rows:
        row["balance_cents"] = max(0, int(row["amount_cents"] or 0) - int(row["paid"] or 0))
    return rows


def refresh_invoice_status(invoice_id: str) -> str:
    """Recompute an invoice's status from the payments that point at it."""
    invoice = query("SELECT * FROM property_invoices WHERE id = ?", (invoice_id,), one=True)
    if not invoice or invoice["status"] == "void":
        return invoice["status"] if invoice else "void"

    paid = paid_against(invoice_id)
    if paid <= 0:
        status = "issued"
    elif paid >= int(invoice["amount_cents"] or 0):
        status = "paid"
    else:
        status = "part_paid"

    if status != invoice["status"]:
        execute("UPDATE property_invoices SET status = ? WHERE id = ?", (status, invoice_id))
    return status


def active_lease(property_id: str):
    today = date.today().isoformat()
    return query(
        """SELECT l.*, t.name AS tenant_name, t.phone AS tenant_phone, t.email AS tenant_email
           FROM property_leases l
           JOIN property_tenants t ON t.id = l.tenant_id
           WHERE l.property_id = ? AND l.status = 'signed'
             AND l.start_date <= ? AND (l.end_date IS NULL OR l.end_date >= ?)
           ORDER BY l.start_date DESC LIMIT 1""",
        (property_id, today, today),
        one=True,
    )


def tenant_in_place(property_id: str):
    return query(
        """SELECT * FROM property_tenants
           WHERE property_id = ? AND status IN ('active', 'notice')
           ORDER BY created_at DESC LIMIT 1""",
        (property_id,),
        one=True,
    )


def sync_property_status(property_id: str) -> str:
    """A property with a tenant reads occupied; one without reads available."""
    property_row = query("SELECT * FROM properties WHERE id = ?", (property_id,), one=True)
    if not property_row:
        return "available"
    if property_row["status"] == "maintenance":
        return "maintenance"
    status = "occupied" if tenant_in_place(property_id) else "available"
    if status != property_row["status"]:
        execute(
            "UPDATE properties SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso(), property_id),
        )
    return status


def portfolio(owner_id: str | None = None):
    """Property rows with the tenant and lease that matter today."""
    where = []
    params = []
    if owner_id:
        where.append("p.owner_id = ?")
        params.append(owner_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    rows = query(
        f"""SELECT p.*,
                   (SELECT COUNT(*) FROM property_tenants t
                     WHERE t.property_id = p.id AND t.status IN ('active', 'notice')) AS tenant_count,
                   (SELECT t.name FROM property_tenants t
                     WHERE t.property_id = p.id AND t.status IN ('active', 'notice')
                     ORDER BY t.created_at DESC LIMIT 1) AS current_tenant,
                   (SELECT l.id FROM property_leases l
                     WHERE l.property_id = p.id AND l.status = 'signed'
                       AND l.start_date <= ? AND (l.end_date IS NULL OR l.end_date >= ?)
                     ORDER BY l.start_date DESC LIMIT 1) AS active_lease_id,
                   (SELECT COALESCE(SUM(i.amount_cents), 0) FROM property_invoices i
                     WHERE i.property_id = p.id AND i.status IN ('issued', 'part_paid')) AS open_invoiced,
                   (SELECT COALESCE(SUM(pay.amount_cents), 0) FROM property_payments pay
                     WHERE pay.property_id = p.id AND pay.invoice_id IN (
                       SELECT i.id FROM property_invoices i
                        WHERE i.property_id = p.id AND i.status IN ('issued', 'part_paid')
                     )) AS open_paid
            FROM properties p
            {clause}
            ORDER BY p.created_at DESC""",
        [date.today().isoformat(), date.today().isoformat(), *params],
    )
    for row in rows:
        row["open_balance_cents"] = max(
            0, int(row["open_invoiced"] or 0) - int(row["open_paid"] or 0)
        )
    return rows


def dashboard_totals(owner_id: str | None = None):
    properties = portfolio(owner_id)
    month_start, month_end = _month_bounds()
    return {
        "properties": len(properties),
        "occupied": len([row for row in properties if row["status"] == "occupied"]),
        "vacant": len([row for row in properties if row["status"] == "available"]),
        "rent_roll": monthly_rent_roll(owner_id),
        "collected": collected_between(owner_id, month_start, month_end),
        "outstanding": outstanding_total(owner_id),
        "month_label": datetime.now().strftime("%B %Y"),
    }


def open_checks(owner_id: str | None = None, limit: int = 10):
    where = ["c.status = 'scheduled'"]
    params = []
    if owner_id:
        where.append("c.owner_id = ?")
        params.append(owner_id)
    return query(
        f"""SELECT c.*, p.name AS property_name, p.code AS property_code
            FROM property_checks c
            JOIN properties p ON p.id = c.property_id
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(c.scheduled_for, c.created_at) ASC
            LIMIT ?""",
        [*params, limit],
    )


def recent_checks(owner_id: str | None = None, limit: int = 6):
    where = ["c.status = 'completed'"]
    params = []
    if owner_id:
        where.append("c.owner_id = ?")
        params.append(owner_id)
    rows = query(
        f"""SELECT c.*, p.name AS property_name, p.code AS property_code,
                   (SELECT COUNT(*) FROM attachments a WHERE a.check_id = c.id) AS media_count,
                   (SELECT a.id FROM attachments a WHERE a.check_id = c.id
                     AND a.category = 'image' ORDER BY a.created_at LIMIT 1) AS cover_id
            FROM property_checks c
            JOIN properties p ON p.id = c.property_id
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(c.conducted_at, c.created_at) DESC
            LIMIT ?""",
        [*params, limit],
    )
    return rows


def lease_terms(
    *,
    property_row,
    tenant,
    start_date: str,
    end_date: str,
    rent_cents: int,
    deposit_cents: int,
    billing_day: int,
    notice_days: int,
) -> str:
    """Fills the letterhead facts into the standard terms, once, at creation.

    The lease stores the finished text: editing the template later must not
    silently change a lease somebody already signed.
    """
    heading = "\n".join(
        [
            f"PROPERTY: {property_row['name']} ({property_row['code']})",
            f"ADDRESS: {', '.join(part for part in (property_row['address'], property_row['suburb'], property_row['city']) if part)}",
            f"LANDLORD: {property_row.get('owner_name') or 'The account holder'}",
            f"TENANT: {tenant['name']}",
            f"TERM: {start_date} to {end_date or 'month to month'}",
            f"RENT: {format_money(rent_cents)} per month, payable by day {billing_day}",
            f"DEPOSIT: {format_money(deposit_cents)}",
            f"NOTICE: {notice_days} days in writing",
        ]
    )
    return f"{heading}\n\n{DEFAULT_LEASE_TERMS}"


# ----------------------------------------------------------------------
# Telling people what happened
# ----------------------------------------------------------------------


def notify_check(check) -> dict:
    """Send a completed property check to the owner on the system, email and WhatsApp.

    The on-system copy is the check record itself; this returns which of the
    outbound channels actually accepted the message so the page can say so
    plainly instead of implying a WhatsApp that never left.
    """
    from flask import current_app

    import downloads
    from notifications import email_configured, send_email_async
    from whatsapp import normalize_phone, send_whatsapp_text, whatsapp_configured

    owner = query("SELECT * FROM users WHERE id = ?", (check["owner_id"],), one=True)
    if not owner:
        return {"email": False, "whatsapp": False}

    property_row = query("SELECT * FROM properties WHERE id = ?", (check["property_id"],), one=True)
    media = query(
        "SELECT * FROM attachments WHERE check_id = ? ORDER BY created_at",
        (check["id"],),
    )
    label = f"{property_row['name']} ({property_row['code']})" if property_row else "your property"
    conducted = (check["conducted_at"] or check["created_at"] or "")[:10]
    lines = [
        f"Property check — {label}",
        f"{conducted} · {check['check_type'].replace('_', ' ')}",
        f"Condition: {(check['rating'] or 'not rated').title()}",
        "",
        (check["findings"] or "No findings recorded.")[:600],
    ]
    if check["action_required"]:
        lines += ["", f"Action: {check['action_required'][:300]}"]
    if media:
        lines += ["", f"{len(media)} photo{'s' if len(media) != 1 else ''}/video attached. Open the links:"]
        lines += [f"- {item['original_name']}: {downloads.absolute_url(item['id'])}" for item in media[:6]]
    body = "\n".join(lines)

    result = {"email": False, "whatsapp": False}

    if email_configured() and owner.get("email"):
        result["email"] = bool(
            send_email_async(owner["email"], f"YaVaKa property check: {label}", body)
        )

    phone = normalize_phone(owner.get("phone") or "")
    if whatsapp_configured() and phone:
        try:
            outcome = send_whatsapp_text(phone, body)
            result["whatsapp"] = outcome.get("status") in {"sent", "queued", "simulated"}
        except Exception:  # noqa: BLE001 - a failed message must not lose the check
            current_app.logger.exception("Could not send property check %s to WhatsApp", check["id"])

    if result["email"] or result["whatsapp"]:
        execute(
            "UPDATE property_checks SET reported_at = ? WHERE id = ?",
            (now_iso(), check["id"]),
        )
    return result


def media_url(attachment_id: str) -> str:
    from flask import url_for

    return url_for("rentals.media", attachment_id=attachment_id)
