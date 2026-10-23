"""The signed-in dashboard."""

from datetime import datetime

from flask import Blueprint, g, render_template, request

from auth import accessible_projects, login_required
from money import format_money
from queries import (
    missing_receipts,
    monthly_cashflow,
    next_stage,
    projects_with_summary,
    recent_transactions,
)
from stages import stage_by_key
import updates as update_feed

bp = Blueprint("dashboard", __name__)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


@bp.get("/app")
@login_required
def index():
    projects = projects_with_summary(accessible_projects(g.user))
    requested = request.args.get("project")
    project = next((item for item in projects if item["id"] == requested), None)
    project = project or (projects[0] if projects else None)

    context = {
        "title": "Dashboard",
        "active": "dashboard",
        "projects": projects,
        "project": project,
        "greeting": _greeting(),
        "first_name": (g.user["name"] or "").split()[0],
    }

    if not project:
        return render_template("app/dashboard.html", **context)

    stages = project["stages"]
    totals = project["totals"]
    transactions = recent_transactions(project["id"], 6)
    missing = missing_receipts(project["id"])
    alerts = []

    if totals["balance"] < 0:
        alerts.append(
            {
                "tone": "danger",
                "icon": "alert",
                "title": "Spending exceeds funding",
                "body": f"The project is {format_money(abs(totals['balance']))} over the money received.",
                "href": f"/app/money?project={project['id']}",
            }
        )

    if missing:
        alerts.append(
            {
                "tone": "warn",
                "icon": "receipt",
                "title": f"{len(missing)} expense{'s' if len(missing) != 1 else ''} need a receipt",
                "body": "Attach proof before the next tranche is released.",
                "href": f"/app/money?project={project['id']}&filter=missing",
            }
        )

    blocked = next((stage for stage in stages if stage["status"] == "blocked"), None)
    if blocked:
        definition = stage_by_key(blocked["key"])
        alerts.append(
            {
                "tone": "danger",
                "icon": "alert",
                "title": f"Blocked at {blocked['name']}",
                "body": definition["summary"] if definition else "This stage is on hold.",
                "href": f"/app/projects/{project['id']}#stage-{blocked['key']}",
            }
        )

    current = next_stage(stages)
    if current and current["status"] == "in_progress":
        definition = stage_by_key(current["key"])
        if definition and definition.get("requires_authority"):
            alerts.append(
                {
                    "tone": "info",
                    "icon": "shield",
                    "title": f"{definition['authority']} sign-off due",
                    "body": "Upload the inspection or approval before marking this stage complete.",
                    "href": f"/app/projects/{project['id']}#stage-{current['key']}",
                }
            )

    upcoming = [stage for stage in stages if stage["status"] == "pending"][:3]

    context.update(
        {
            "stages": stages,
            "totals": totals,
            "transactions": transactions,
            "flow": monthly_cashflow(project["id"]),
            "missing": missing,
            "alerts": alerts,
            "upcoming": upcoming,
            "updates": update_feed.feed(g.user["id"], limit=5),
            "current": current,
            "current_definition": stage_by_key(current["key"]) if current else None,
            "completed_count": len([stage for stage in stages if stage["status"] == "complete"]),
        }
    )

    return render_template("app/dashboard.html", **context)
