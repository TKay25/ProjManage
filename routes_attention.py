"""One cross-project list of what needs a person next.

The dashboard shows this for a single build. This page answers the question a
diaspora client actually asks — "what is waiting on me across everything?" —
without opening each project in turn.
"""

from datetime import date, datetime

from flask import Blueprint, g, render_template

from auth import accessible_projects, login_required, runs_build
from db import query
from money import format_money
from stages import stage_by_key

bp = Blueprint("attention", __name__)

# An expense is only chased once it has had a week to collect its receipt.
RECEIPT_GRACE_DAYS = 7


def _days_since(stamp: str) -> int:
    """Whole days between an ISO timestamp and today, never negative."""
    if not stamp:
        return 0
    try:
        moment = datetime.fromisoformat(stamp).date()
    except (TypeError, ValueError):
        return 0
    return max(0, (date.today() - moment).days)


def _age_label(days: int) -> str:
    if days <= 0:
        return "Today"
    if days == 1:
        return "1 day old"
    return f"{days} days old"


@bp.get("/app/attention")
@login_required
def index():
    projects = accessible_projects(g.user)
    by_id = {project["id"]: project for project in projects}
    ids = list(by_id)
    does_build = runs_build(g.user)

    approvals, blocked, overdue, recent = [], [], [], []

    if ids:
        placeholders = ",".join("?" for _ in ids)

        # Regulatory gates that are already in progress, so the sign-off is the
        # thing standing between the build and the next stage.
        live = query(
            f"""SELECT key, name, project_id, started_at
                FROM stages
                WHERE project_id IN ({placeholders}) AND status = 'in_progress'
                ORDER BY project_id, position""",
            ids,
        )
        for row in live:
            definition = stage_by_key(row["key"])
            if not definition or not definition.get("requires_authority"):
                continue
            days = _days_since(row["started_at"])
            approvals.append(
                {
                    "tone": "info",
                    "icon": "shield",
                    "title": f"{definition['authority']} sign-off due",
                    "body": f"{by_id[row['project_id']]['name']} · {row['name']}",
                    "age": days,
                    "age_label": _age_label(days),
                    "href": f"/app/projects/{row['project_id']}#stage-{row['key']}",
                }
            )

        unsigned = query(
            f"""SELECT id, title, project_id, created_at
                FROM agreements
                WHERE project_id IN ({placeholders}) AND status = 'awaiting_signature'
                ORDER BY created_at ASC""",
            ids,
        )
        for row in unsigned:
            days = _days_since(row["created_at"])
            approvals.append(
                {
                    "tone": "warn",
                    "icon": "pen",
                    "title": "Agreement awaiting signature",
                    "body": f"{by_id[row['project_id']]['name']} · {row['title']}",
                    "age": days,
                    "age_label": f"Sent {_age_label(days).lower()}" if days else "Sent today",
                    "href": f"/app/agreements/{row['id']}",
                }
            )

        blocked_rows = query(
            f"""SELECT key, name, notes, project_id, started_at
                FROM stages
                WHERE project_id IN ({placeholders}) AND status = 'blocked'
                ORDER BY project_id, position""",
            ids,
        )
        for row in blocked_rows:
            definition = stage_by_key(row["key"])
            days = _days_since(row["started_at"])
            blocked.append(
                {
                    "tone": "danger",
                    "icon": "alert",
                    "title": f"Blocked at {row['name']}",
                    "body": (row["notes"] or (definition["summary"] if definition else "This stage is on hold.")),
                    "project": by_id[row["project_id"]]["name"],
                    "age": days,
                    "age_label": _age_label(days),
                    "href": f"/app/projects/{row['project_id']}#stage-{row['key']}",
                }
            )

        expenses = query(
            f"""SELECT t.id, t.project_id, t.description, t.amount_cents, t.occurred_at
                FROM transactions t
                LEFT JOIN attachments a ON a.transaction_id = t.id
                WHERE t.project_id IN ({placeholders})
                  AND t.type = 'EXPENSE' AND a.id IS NULL
                ORDER BY t.occurred_at ASC""",
            ids,
        )
        for row in expenses:
            days = _days_since(row["occurred_at"])
            item = {
                "tone": "warn" if days > RECEIPT_GRACE_DAYS else "info",
                "icon": "receipt",
                "title": row["description"],
                "body": f"{by_id[row['project_id']]['name']} · {format_money(row['amount_cents'])}",
                "age": days,
                "age_label": _age_label(days),
                "href": f"/app/money?project={row['project_id']}&filter=missing",
            }
            (overdue if days > RECEIPT_GRACE_DAYS else recent).append(item)

    # Oldest first inside every group: the thing that has waited longest is the
    # thing most likely to be forgotten.
    for group in (approvals, blocked, overdue, recent):
        group.sort(key=lambda item: item["age"], reverse=True)

    sections = [
        {
            "key": "approvals",
            "title": "Approvals due",
            "sub": "Regulatory sign-offs and signatures that gate the next stage.",
            "rows": approvals,
            "empty": "No authority sign-off or unsigned agreement is outstanding.",
        },
        {
            "key": "blocked",
            "title": "Blocked stages",
            "sub": "Stages on hold, with whatever reason was recorded.",
            "rows": blocked,
            "empty": "No stage is flagged as blocked.",
        },
        {
            "key": "receipts",
            # A client is waiting on proof; only whoever runs the build chases it.
            "title": "Receipts to chase" if does_build else "Missing receipts",
            "sub": (
                f"Expenses with no proof attached. Overdue after {RECEIPT_GRACE_DAYS} days."
                if does_build
                else f"Payments without proof attached. Flagged after {RECEIPT_GRACE_DAYS} days."
            ),
            "rows": overdue + recent,
            "empty": (
                "Every expense has a receipt attached."
                if does_build
                else "Every payment has a receipt attached."
            ),
        },
    ]

    counts = {
        "approvals": len(approvals),
        "blocked": len(blocked),
        "receipts": len(overdue) + len(recent),
        "overdue": len(overdue),
    }

    return render_template(
        "app/attention.html",
        title="Attention",
        active="attention",
        projects=projects,
        sections=sections,
        counts=counts,
        total=counts["approvals"] + counts["blocked"] + counts["receipts"],
        grace_days=RECEIPT_GRACE_DAYS,
    )
