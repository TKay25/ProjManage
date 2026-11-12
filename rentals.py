"""Rental management: the bonus module inside Property Management.

A YaVaKa build ends at handover, but the house does not. This module keeps the
same record going: who lives there, what the lease says, what rent is due, what
was receipted, and what the periodic property check found.

It is deliberately NOT a second Project Management. There are no stages, no
budgets against trades and no build money here — those stay in the main system.
What lives here is the landlord's side of a standing building.
"""

from datetime import date, datetime, timedelta

from db import execute, new_id, now_iso, query
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
                   t.name AS tenant_name, t.phone AS tenant_phone, t.email AS tenant_email,
                   COALESCE(l.grace_days, {DEFAULT_GRACE_DAYS}) AS grace_days,
                   COALESCE((SELECT SUM(p.amount_cents) FROM property_payments p
                             WHERE p.invoice_id = i.id), 0) AS paid
            FROM property_invoices i
            JOIN properties pr ON pr.id = i.property_id
            LEFT JOIN property_tenants t ON t.id = i.tenant_id
            LEFT JOIN property_leases l ON l.id = i.lease_id
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
                     )) AS open_paid,
                   (SELECT a.id FROM attachments a
                     WHERE a.property_id = p.id AND a.category = 'image'
                     ORDER BY a.created_at LIMIT 1) AS cover_id,
                   (SELECT COUNT(*) FROM property_work_orders w
                     WHERE w.property_id = p.id AND w.status IN ('open', 'in_progress')) AS work_order_count
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
    income = collected_between(owner_id, month_start, month_end)
    expenses = expense_total(owner_id, start=month_start, end=month_end)
    occupied = len([row for row in properties if row["status"] == "occupied"])
    outstanding = outstanding_total(owner_id)

    return {
        "properties": len(properties),
        "occupied": occupied,
        "vacant": len([row for row in properties if row["status"] == "available"]),
        "occupancy": round((occupied / len(properties)) * 100) if properties else 0,
        "rent_roll": monthly_rent_roll(owner_id),
        "collected": income,
        "expenses": expenses,
        "net": income - expenses,
        "outstanding": outstanding,
        "value": portfolio_value(owner_id),
        "yield_percent": gross_yield(owner_id),
        "arrears_count": len(open_invoices(owner_id, limit=500)) if outstanding else 0,
        "checks_due": len(open_checks(owner_id, limit=50)),
        "work_orders": len(open_work_orders(owner_id, limit=50)),
        "expiring_leases": len(expiring_leases(owner_id, days=60)),
        "month_label": datetime.now().strftime("%B %Y"),
        "today": date.today().isoformat(),
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

# ----------------------------------------------------------------------
# Catalogue additions: invoice kinds, costs, work orders
# ----------------------------------------------------------------------

INVOICE_KINDS = [
    ("rent", "Rent"),
    ("deposit", "Deposit"),
    ("water", "Water"),
    ("levy", "Levy"),
    ("repair", "Repair recharge"),
    ("other", "Other"),
]

EXPENSE_CATEGORIES = [
    ("rates", "Council rates"),
    ("water", "Water and sewer"),
    ("insurance", "Insurance"),
    ("repairs", "Repairs and maintenance"),
    ("management", "Management fee"),
    ("levy", "Body corporate levy"),
    ("other", "Other"),
]

WORK_ORDER_STATUSES = [
    ("open", "Open"),
    ("in_progress", "In progress"),
    ("done", "Done"),
    ("cancelled", "Cancelled"),
]

WORK_ORDER_PRIORITIES = [
    ("low", "Low"),
    ("normal", "Normal"),
    ("urgent", "Urgent"),
]

# How soon the next check follows a completed one.
CHECK_CADENCE_DAYS = {
    "routine": 90,
    "quarterly": 90,
    "annual": 365,
}

# How overdue an invoice must be before a reminder is fair. The lease can
# override this with its own grace period.
DEFAULT_GRACE_DAYS = 5


def today_iso() -> str:
    return date.today().isoformat()


def next_check_date(check_type: str, from_day: date | None = None) -> str | None:
    """The date a follow-up check should be scheduled for, or None."""
    days = CHECK_CADENCE_DAYS.get((check_type or "").strip())
    if not days:
        return None
    return ((from_day or date.today()) + timedelta(days=days)).isoformat()


# ----------------------------------------------------------------------
# Activity: the property workspace's own readable history
# ----------------------------------------------------------------------


def log_activity(owner_id, property_id, actor_id, action, title, detail="", href=None, when=None):
    if not owner_id:
        return
    execute(
        """INSERT INTO property_activity
             (id, owner_id, property_id, actor_id, action, title, detail, href, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id(),
            owner_id,
            property_id,
            actor_id,
            action,
            str(title or "")[:160],
            str(detail or "")[:400] or None,
            href,
            when or now_iso(),
        ),
    )


def recent_activity(owner_id=None, property_id=None, limit=12):
    where, params = [], []
    if owner_id:
        where.append("a.owner_id = ?")
        params.append(owner_id)
    if property_id:
        where.append("a.property_id = ?")
        params.append(property_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return query(
        f"""SELECT a.*, p.name AS property_name, u.name AS actor_name
            FROM property_activity a
            LEFT JOIN properties p ON p.id = a.property_id
            LEFT JOIN users u ON u.id = a.actor_id
            {clause}
            ORDER BY a.created_at DESC
            LIMIT ?""",
        [*params, limit],
    )


# ----------------------------------------------------------------------
# Costs, income and yield
# ----------------------------------------------------------------------


def expense_total(owner_id=None, property_id=None, start=None, end=None) -> int:
    where, params = [], []
    if owner_id:
        where.append("owner_id = ?")
        params.append(owner_id)
    if property_id:
        where.append("property_id = ?")
        params.append(property_id)
    if start:
        where.append("substr(incurred_at, 1, 10) >= ?")
        params.append(start)
    if end:
        where.append("substr(incurred_at, 1, 10) <= ?")
        params.append(end)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    row = query(
        f"SELECT COALESCE(SUM(amount_cents), 0) AS total FROM property_expenses {clause}",
        params,
        one=True,
    )
    return int(row["total"] or 0)


def income_total(owner_id=None, property_id=None, start=None, end=None) -> int:
    return collected_between(owner_id, start or "0000-01-01", end or "9999-12-31") if property_id is None else _income_for_property(property_id, start, end)


def _income_for_property(property_id, start, end) -> int:
    where = ["property_id = ?"]
    params = [property_id]
    if start:
        where.append("substr(received_at, 1, 10) >= ?")
        params.append(start)
    if end:
        where.append("substr(received_at, 1, 10) <= ?")
        params.append(end)
    row = query(
        f"SELECT COALESCE(SUM(amount_cents), 0) AS total FROM property_payments WHERE {' AND '.join(where)}",
        params,
        one=True,
    )
    return int(row["total"] or 0)


def expenses_by_category(owner_id=None, start=None, end=None):
    where, params = [], []
    if owner_id:
        where.append("owner_id = ?")
        params.append(owner_id)
    if start:
        where.append("substr(incurred_at, 1, 10) >= ?")
        params.append(start)
    if end:
        where.append("substr(incurred_at, 1, 10) <= ?")
        params.append(end)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return query(
        f"""SELECT category, COALESCE(SUM(amount_cents), 0) AS total, COUNT(*) AS entries
            FROM property_expenses {clause}
            GROUP BY category ORDER BY total DESC""",
        params,
    )


def portfolio_value(owner_id=None) -> int:
    where, params = "", []
    if owner_id:
        where = "WHERE owner_id = ?"
        params.append(owner_id)
    row = query(
        f"SELECT COALESCE(SUM(value_cents), 0) AS total FROM properties {where}",
        params,
        one=True,
    )
    return int(row["total"] or 0)


def gross_yield(owner_id=None) -> float:
    """Annual rent roll over what the portfolio is worth, as a percentage."""
    value = portfolio_value(owner_id)
    if not value:
        return 0.0
    return round((monthly_rent_roll(owner_id) * 12 / value) * 100, 2)


def collection_trend(owner_id=None, months: int = 6):
    """Expected vs collected for the last few months, oldest first.

    Expected is the rent on leases that were running in that month, so a
    vacancy shows up as a gap rather than a zero.
    """
    today = date.today()
    first = today.replace(day=1)
    series = []
    for offset in range(months - 1, -1, -1):
        year = first.year
        month = first.month - offset
        while month <= 0:
            month += 12
            year -= 1
        start = date(year, month, 1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        where = [
            "l.status IN ('signed', 'ended')",
            "l.start_date <= ?",
            "(l.end_date IS NULL OR l.end_date >= ?)",
        ]
        params = [end.isoformat(), start.isoformat()]
        if owner_id:
            where.append("l.owner_id = ?")
            params.append(owner_id)
        expected_row = query(
            f"SELECT COALESCE(SUM(l.rent_cents), 0) AS total FROM property_leases l WHERE {' AND '.join(where)}",
            params,
            one=True,
        )
        collected = collected_between(owner_id, start.isoformat(), end.isoformat())
        series.append(
            {
                "label": start.strftime("%b"),
                "month": start.strftime("%Y-%m"),
                "expected": int(expected_row["total"] or 0),
                "collected": collected,
            }
        )
    return series


def arrears_aging(owner_id=None):
    """Buckets every unpaid invoice by how long it is past its due date."""
    rows = open_invoices(owner_id, limit=500)
    today = date.today()
    buckets = [
        {"key": "current", "label": "Not yet due", "total": 0, "count": 0},
        {"key": "1-30", "label": "1 to 30 days", "total": 0, "count": 0},
        {"key": "31-60", "label": "31 to 60 days", "total": 0, "count": 0},
        {"key": "61-90", "label": "61 to 90 days", "total": 0, "count": 0},
        {"key": "90+", "label": "Over 90 days", "total": 0, "count": 0},
    ]
    lookup = {bucket["key"]: bucket for bucket in buckets}
    for row in rows:
        try:
            due = date.fromisoformat(str(row["due_date"])[:10])
        except (TypeError, ValueError):
            due = today
        days = (today - due).days
        if days <= 0:
            bucket = lookup["current"]
        elif days <= 30:
            bucket = lookup["1-30"]
        elif days <= 60:
            bucket = lookup["31-60"]
        elif days <= 90:
            bucket = lookup["61-90"]
        else:
            bucket = lookup["90+"]
        bucket["total"] += row["balance_cents"]
        bucket["count"] += 1
    return buckets


def reminders_due(owner_id=None, limit=50):
    """Unpaid invoices that are past due plus the lease's grace period."""
    rows = open_invoices(owner_id, limit=limit)
    today = date.today()
    due = []
    for row in rows:
        try:
            due_date = date.fromisoformat(str(row["due_date"])[:10])
        except (TypeError, ValueError):
            continue
        grace = int(row.get("grace_days") or DEFAULT_GRACE_DAYS)
        if (today - due_date).days > grace:
            row["days_late"] = (today - due_date).days - grace
            due.append(row)
    return due


def tenant_statement(tenant_id: str):
    """A running account for one tenant: invoices out, receipts in.

    Returns the entries oldest first, each with a signed amount and the balance
    after it, so a statement can be printed without recomputing anything.
    """
    invoices = query(
        """SELECT id, number, kind, period_start, due_date, amount_cents, status, created_at
           FROM property_invoices
           WHERE tenant_id = ? AND status != 'void'
           ORDER BY period_start, created_at""",
        (tenant_id,),
    )
    payments = query(
        """SELECT id, receipt_number, received_at, amount_cents, method, invoice_id, created_at
           FROM property_payments
           WHERE tenant_id = ?
           ORDER BY received_at, created_at""",
        (tenant_id,),
    )

    entries = []
    for invoice in invoices:
        entries.append(
            {
                "date": str(invoice["period_start"])[:10],
                "sort": str(invoice["created_at"] or ""),
                "reference": invoice["number"],
                "description": "Rent" if invoice["kind"] == "rent" else str(invoice["kind"]).title(),
                "debit": int(invoice["amount_cents"] or 0),
                "credit": 0,
                "invoice_id": invoice["id"],
            }
        )
    for payment in payments:
        entries.append(
            {
                "date": str(payment["received_at"])[:10],
                "sort": str(payment["created_at"] or ""),
                "reference": payment["receipt_number"],
                "description": "Payment received",
                "debit": 0,
                "credit": int(payment["amount_cents"] or 0),
                "invoice_id": payment["invoice_id"],
            }
        )

    entries.sort(key=lambda item: (item["date"], item["sort"]))
    balance = 0
    for entry in entries:
        balance += entry["debit"] - entry["credit"]
        entry["balance"] = balance
    return entries


def deposit_state(lease) -> dict:
    expected = int(lease.get("deposit_cents") or 0) if hasattr(lease, "get") else int(lease["deposit_cents"] or 0)
    paid_at = lease.get("deposit_paid_at") if hasattr(lease, "get") else lease["deposit_paid_at"]
    refunded = int((lease.get("deposit_refund_cents") if hasattr(lease, "get") else lease["deposit_refund_cents"]) or 0)
    held = expected if paid_at else 0
    return {
        "expected": expected,
        "held": held,
        "refunded": refunded,
        "due_back": max(0, held - refunded),
        "received": bool(paid_at),
        "settled": bool(refunded) and refunded >= held,
    }


def expiring_leases(owner_id=None, days: int = 60):
    horizon = (date.today() + timedelta(days=days)).isoformat()
    where = [
        "l.status = 'signed'",
        "l.end_date IS NOT NULL",
        "substr(l.end_date, 1, 10) BETWEEN ? AND ?",
    ]
    params = [date.today().isoformat(), horizon]
    if owner_id:
        where.append("l.owner_id = ?")
        params.append(owner_id)
    return query(
        f"""SELECT l.*, p.name AS property_name, p.code AS property_code,
                   t.name AS tenant_name
            FROM property_leases l
            JOIN properties p ON p.id = l.property_id
            JOIN property_tenants t ON t.id = l.tenant_id
            WHERE {' AND '.join(where)}
            ORDER BY l.end_date ASC""",
        params,
    )


def open_work_orders(owner_id=None, limit=50):
    where = ["w.status IN ('open', 'in_progress')"]
    params = []
    if owner_id:
        where.append("w.owner_id = ?")
        params.append(owner_id)
    return query(
        f"""SELECT w.*, p.name AS property_name, p.code AS property_code,
                   t.name AS tenant_name
            FROM property_work_orders w
            JOIN properties p ON p.id = w.property_id
            LEFT JOIN property_tenants t ON t.id = w.tenant_id
            WHERE {' AND '.join(where)}
            ORDER BY CASE w.priority WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     w.reported_at ASC
            LIMIT ?""",
        [*params, limit],
    )


def property_income(property_id: str, start=None, end=None) -> dict:
    income = _income_for_property(property_id, start, end)
    expenses = expense_total(property_id=property_id, start=start, end=end)
    return {"income": income, "expenses": expenses, "net": income - expenses}
