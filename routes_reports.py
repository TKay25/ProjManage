"""Portfolio reporting and the printable project pack.

Two questions this answers that the day-to-day pages do not:

* across every build, what is committed, what has been funded and what has been
  spent — with the overruns at the top;
* handed to a bank, a lawyer or a buyer, one printable document that shows the
  same record end to end.
"""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, render_template, request

from auth import accessible_projects, login_required, require_project, runs_build
from db import query
from money import format_money
from queries import attachments_by_stage, money_totals, projects_with_summary, stage_variance
from stages import STAGES, STAGE_GROUPS, project_progress

bp = Blueprint("reports", __name__)

BURN_WINDOW_DAYS = 90
DEFINITION = {stage["key"]: stage for stage in STAGES}


def _spend_since(project_ids, days: int) -> dict:
    """One query for the burn window across every project."""
    if not project_ids:
        return {}

    placeholders = ",".join("?" for _ in project_ids)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = query(
        f"""SELECT project_id, COALESCE(SUM(amount_cents), 0) AS spent
            FROM transactions
            WHERE project_id IN ({placeholders}) AND type = 'EXPENSE'
              AND substr(occurred_at, 1, 10) >= ?
            GROUP BY project_id""",
        [*project_ids, since],
    )
    return {row["project_id"]: int(row["spent"] or 0) for row in rows}


def _budget_by_project(project_ids) -> dict:
    if not project_ids:
        return {}
    placeholders = ",".join("?" for _ in project_ids)
    rows = query(
        f"""SELECT project_id, COALESCE(SUM(budget_cents), 0) AS budget
            FROM stages WHERE project_id IN ({placeholders})
            GROUP BY project_id""",
        project_ids,
    )
    return {row["project_id"]: int(row["budget"] or 0) for row in rows}


@bp.get("/app/reports")
@login_required
def index():
    summaries = projects_with_summary(accessible_projects(g.user))
    ids = [project["id"] for project in summaries]
    budgets = _budget_by_project(ids)
    recent_spend = _spend_since(ids, BURN_WINDOW_DAYS)

    rows = []
    for project in summaries:
        budget = budgets.get(project["id"], 0)
        funded = project["totals"]["funded"]
        spent = project["totals"]["spent"]
        balance = project["totals"]["balance"]
        burn_90 = recent_spend.get(project["id"], 0)
        daily = burn_90 / BURN_WINDOW_DAYS if burn_90 else 0
        runway_days = int(balance / daily) if daily > 0 and balance > 0 else None

        rows.append(
            {
                **project,
                "budget_cents": budget,
                "funded_cents": funded,
                "spent_cents": spent,
                "balance_cents": balance,
                "variance_cents": budget - spent,
                "burn_90_cents": burn_90,
                "monthly_burn_cents": round(daily * 30),
                "runway_days": runway_days,
                "over_budget": bool(budget) and spent > budget,
            }
        )

    # Overruns first (worst at the top), then the rest biggest-build-first.
    rows.sort(
        key=lambda row: (
            0 if row["variance_cents"] < 0 else 1,
            row["variance_cents"] if row["variance_cents"] < 0 else -row["budget_cents"],
        )
    )

    totals = {
        "budget": sum(row["budget_cents"] for row in rows),
        "funded": sum(row["funded_cents"] for row in rows),
        "spent": sum(row["spent_cents"] for row in rows),
        "balance": sum(row["balance_cents"] for row in rows),
        "variance": sum(row["variance_cents"] for row in rows),
    }

    overruns = [row for row in rows if row["over_budget"]]
    short_runway = [
        row for row in rows if row["runway_days"] is not None and row["runway_days"] < 60
    ]

    return render_template(
        "app/reports.html",
        title="Reports",
        active="reports",
        projects=accessible_projects(g.user),
        rows=rows,
        totals=totals,
        overruns=overruns,
        short_runway=short_runway,
        burn_window=BURN_WINDOW_DAYS,
        runs_build=runs_build(g.user),
    )


@bp.get("/app/projects/<project_id>/pack")
@login_required
def project_pack(project_id):
    """One printable document: facts, stages, money, proof and agreements."""
    project = require_project(project_id)

    stages = query("SELECT * FROM stages WHERE project_id = ? ORDER BY position", (project_id,))
    grouped = []
    for name in STAGE_GROUPS:
        group_rows = [
            row for row in stages if (DEFINITION.get(row["key"]) or {}).get("group") == name
        ]
        if group_rows:
            grouped.append({"name": name, "rows": group_rows})

    return render_template(
        "app/project_pack.html",
        title=f"{project['name']} · project pack",
        project=project,
        owner=query(
            "SELECT name, email FROM users WHERE id = ?", (project["owner_id"],), one=True
        ),
        manager=(
            query("SELECT name, email FROM users WHERE id = ?", (project["manager_id"],), one=True)
            if project["manager_id"]
            else None
        ),
        stages=stages,
        grouped=grouped,
        progress=project_progress(stages),
        totals=money_totals(project_id),
        variance=stage_variance(project_id),
        transactions=query(
            """SELECT * FROM transactions WHERE project_id = ?
               ORDER BY occurred_at ASC, created_at ASC""",
            (project_id,),
        ),
        documents=query(
            "SELECT * FROM attachments WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        ),
        agreements=query(
            "SELECT * FROM agreements WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        ),
        by_stage=attachments_by_stage(project_id),
        generated_at=datetime.now(timezone.utc),
        money=format_money,
        runs_build=runs_build(g.user),
        print_mode=request.args.get("print") == "1",
    )
