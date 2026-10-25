"""Read models that aggregate money, stages and activity."""

from datetime import datetime, timezone

from db import query
import health
from stages import project_progress, stage_by_key


def money_totals(project_id: str) -> dict:
    row = query(
        """SELECT
             COALESCE(SUM(CASE WHEN type = 'FUNDING' THEN amount_cents END), 0) AS funded,
             COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount_cents END), 0) AS spent
           FROM transactions WHERE project_id = ?""",
        (project_id,),
        one=True,
    )
    funded = int(row["funded"] or 0)
    spent = int(row["spent"] or 0)
    return {"funded": funded, "spent": spent, "balance": funded - spent}


def totals_for_projects(project_ids) -> dict:
    ids = list(project_ids)
    if not ids:
        return {"funded": 0, "spent": 0, "balance": 0}

    placeholders = ",".join("?" for _ in ids)
    row = query(
        f"""SELECT
              COALESCE(SUM(CASE WHEN type = 'FUNDING' THEN amount_cents END), 0) AS funded,
              COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount_cents END), 0) AS spent
            FROM transactions WHERE project_id IN ({placeholders})""",
        ids,
        one=True,
    )
    funded = int(row["funded"] or 0)
    spent = int(row["spent"] or 0)
    return {"funded": funded, "spent": spent, "balance": funded - spent}


def stage_rows(project_id: str):
    return query("SELECT * FROM stages WHERE project_id = ? ORDER BY position", (project_id,))


def stage_spend(project_id: str) -> dict:
    rows = query(
        """SELECT stage_key, COALESCE(SUM(amount_cents), 0) AS spent
           FROM transactions
           WHERE project_id = ? AND type = 'EXPENSE' AND stage_key IS NOT NULL
           GROUP BY stage_key""",
        (project_id,),
    )
    return {row["stage_key"]: int(row["spent"]) for row in rows}


def attachments_by_stage(project_id: str) -> dict:
    """Files filed against a build stage, keyed by stage_key."""
    rows = query(
        """SELECT a.*, u.name AS uploader_name
           FROM attachments a
           LEFT JOIN users u ON u.id = a.uploader_id
           WHERE a.project_id = ? AND a.stage_key IS NOT NULL
           ORDER BY a.created_at DESC""",
        (project_id,),
    )
    grouped = {}
    for row in rows:
        grouped.setdefault(row["stage_key"], []).append(row)
    return grouped


def category_breakdown(project_id: str):
    rows = query(
        """SELECT category, COALESCE(SUM(amount_cents), 0) AS total
           FROM transactions
           WHERE project_id = ? AND type = 'EXPENSE'
           GROUP BY category
           ORDER BY total DESC""",
        (project_id,),
    )
    for row in rows:
        row["total"] = int(row["total"])
    return rows


def recent_transactions(project_id: str, limit: int = 6):
    return query(
        """SELECT t.*, a.id AS receipt_id
           FROM transactions t
           LEFT JOIN attachments a ON a.id = (
               SELECT id FROM attachments WHERE transaction_id = t.id
               ORDER BY created_at LIMIT 1
           )
           WHERE t.project_id = ?
           ORDER BY t.occurred_at DESC, t.created_at DESC
           LIMIT ?""",
        (project_id, limit),
    )


def monthly_cashflow(project_id: str, months: int = 6):
    now = datetime.now(timezone.utc)
    series = []

    for offset in range(months - 1, -1, -1):
        year = now.year
        month = now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        label = datetime(year, month, 1).strftime("%b")
        series.append({"key": f"{year:04d}-{month:02d}", "label": label, "funded": 0, "spent": 0})

    start_key = series[0]["key"]
    rows = query(
        """SELECT substr(occurred_at, 1, 7) AS month, type, SUM(amount_cents) AS total
           FROM transactions
           WHERE project_id = ? AND substr(occurred_at, 1, 7) >= ?
           GROUP BY month, type""",
        (project_id, start_key),
    )

    by_key = {item["key"]: item for item in series}
    for row in rows:
        bucket = by_key.get(row["month"])
        if not bucket:
            continue
        if row["type"] == "FUNDING":
            bucket["funded"] = int(row["total"])
        else:
            bucket["spent"] = int(row["total"])

    return series


def balance_sparkline(series, width=640, height=132):
    """Points for a running-balance line, computed once on the server.

    Drawn as an SVG polyline so the chart costs no JavaScript and no extra
    request. A flat or empty series renders as a centred line rather than a
    divide-by-zero.
    """
    running = 0
    values = []
    for row in series or []:
        running += int(row.get("funded", 0)) - int(row.get("spent", 0))
        values.append(running)

    if not values:
        return {"points": "", "area": "", "last": 0, "min": 0, "max": 0, "flat": True}

    low, high = min(values + [0]), max(values + [0])
    span = high - low
    if span <= 0:
        span = 1

    step = width / max(len(values) - 1, 1)
    coords = []
    for index, value in enumerate(values):
        x = round(index * step, 2)
        y = round(height - ((value - low) / span) * height, 2)
        coords.append((x, y))

    points = " ".join(f"{x},{y}" for x, y in coords)
    area = f"0,{height} " + points + f" {coords[-1][0]},{height}"
    return {
        "points": points,
        "area": area,
        "last": values[-1],
        "min": low,
        "max": high,
        "flat": len(set(values)) == 1,
    }


def projects_with_summary(projects):
    """Stages and money for every project in three queries, not three per row.

    A manager with sixty builds used to issue 120 queries to draw one list.
    """
    if not projects:
        return []

    ids = [project["id"] for project in projects]
    placeholders = ",".join("?" for _ in ids)

    stage_rows_by_project = {}
    for row in query(
        f"""SELECT * FROM stages WHERE project_id IN ({placeholders})
            ORDER BY position""",
        ids,
    ):
        stage_rows_by_project.setdefault(row["project_id"], []).append(row)

    totals_by_project = {
        row["project_id"]: {"funded": int(row["funded"] or 0), "spent": int(row["spent"] or 0)}
        for row in query(
            f"""SELECT project_id,
                     COALESCE(SUM(CASE WHEN type = 'FUNDING' THEN amount_cents END), 0) AS funded,
                     COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount_cents END), 0) AS spent
                FROM transactions WHERE project_id IN ({placeholders})
                GROUP BY project_id""",
            ids,
        )
    }

    # One extra query instead of one per row: what is blocked, and what is
    # still missing proof, both feed the red/amber flag on each card.
    flags = {
        row["project_id"]: row
        for row in query(
            f"""SELECT p.id AS project_id,
                     (SELECT COUNT(*) FROM stages s
                       WHERE s.project_id = p.id AND s.status = 'blocked') AS blocked,
                     (SELECT COUNT(*) FROM transactions t
                       WHERE t.project_id = p.id AND t.type = 'EXPENSE'
                         AND NOT EXISTS (
                           SELECT 1 FROM attachments a WHERE a.transaction_id = t.id
                         )) AS missing_receipts
                FROM projects p WHERE p.id IN ({placeholders})""",
            ids,
        )
    }

    summaries = []
    for project in projects:
        stages = stage_rows_by_project.get(project["id"], [])
        totals = totals_by_project.get(project["id"], {"funded": 0, "spent": 0})
        totals["balance"] = totals["funded"] - totals["spent"]
        found = flags.get(project["id"], {})
        summaries.append(
            {
                **project,
                "totals": totals,
                "stages": stages,
                "progress": project_progress(stages),
                "health": health.summary(
                    project,
                    totals,
                    blocked_stages=int(found.get("blocked") or 0),
                    missing_receipts=int(found.get("missing_receipts") or 0),
                ),
            }
        )
    return summaries


def stage_variance(project_id: str):
    """Budget against actual per stage, worst overrun first.

    This is the question a client actually asks at handover: which parts of the
    build went over, and by how much.
    """
    rows = query(
        """SELECT s.key, s.name, s.position, s.status, s.budget_cents,
                  COALESCE(SUM(CASE WHEN t.type = 'EXPENSE' THEN t.amount_cents END), 0) AS spent_cents
           FROM stages s
           LEFT JOIN transactions t
                  ON t.project_id = s.project_id AND t.stage_key = s.key
           WHERE s.project_id = ?
           GROUP BY s.id, s.key, s.name, s.position, s.status, s.budget_cents
           ORDER BY s.position""",
        (project_id,),
    )

    for row in rows:
        budget = int(row["budget_cents"] or 0)
        spent = int(row["spent_cents"] or 0)
        row["budget_cents"] = budget
        row["spent_cents"] = spent
        row["variance_cents"] = budget - spent
        row["percent_used"] = round((spent / budget) * 100) if budget else None
    return rows


def burn_rate(project_id: str, days: int = 90) -> dict:
    """Average daily spend over a window, and how long the balance lasts."""
    row = query(
        """SELECT COALESCE(SUM(amount_cents), 0) AS spent
           FROM transactions
           WHERE project_id = ? AND type = 'EXPENSE'
             AND substr(occurred_at, 1, 10) >= ?""",
        (project_id, _days_ago(days)),
        one=True,
    )
    spent = int(row["spent"] or 0) if row else 0
    totals = money_totals(project_id)
    daily = spent / days if days else 0
    runway_days = int(totals["balance"] / daily) if daily > 0 and totals["balance"] > 0 else None

    return {
        "spent": spent,
        "window_days": days,
        "daily": daily,
        "monthly": daily * 30,
        "runway_days": runway_days,
        "balance": totals["balance"],
    }


def _days_ago(days: int) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def missing_receipts(project_id: str):
    return query(
        """SELECT t.* FROM transactions t
           LEFT JOIN attachments a ON a.transaction_id = t.id
           WHERE t.project_id = ? AND t.type = 'EXPENSE' AND a.id IS NULL
           ORDER BY t.occurred_at DESC""",
        (project_id,),
    )


def latest_activity(project_id: str, limit: int = 6):
    return query(
        """SELECT e.*, u.name AS user_name
           FROM audit_events e
           LEFT JOIN users u ON u.id = e.user_id
           WHERE e.project_id = ?
           ORDER BY e.created_at DESC
           LIMIT ?""",
        (project_id, limit),
    )


def next_stage(stages):
    for stage in stages:
        if stage["status"] in {"in_progress", "blocked"}:
            return stage
    for stage in stages:
        if stage["status"] != "complete":
            return stage
    return None


def attention_counts(project_ids) -> dict:
    """The shell badge: the same work /app/attention lists, as counts.

    Runs on every rendered workspace page, so it is one aggregate query plus a
    single lookup of in-progress stages — never a loop over projects.
    """
    ids = list(project_ids)
    counts = {"blocked": 0, "approvals": 0, "receipts": 0, "agreements": 0, "total": 0}
    if not ids:
        return counts

    placeholders = ",".join("?" for _ in ids)
    row = query(
        f"""SELECT
              (SELECT COUNT(*) FROM stages
                WHERE project_id IN ({placeholders}) AND status = 'blocked') AS blocked,
              (SELECT COUNT(*) FROM agreements
                WHERE project_id IN ({placeholders}) AND status = 'awaiting_signature') AS agreements,
              (SELECT COUNT(*) FROM transactions t
                WHERE t.project_id IN ({placeholders}) AND t.type = 'EXPENSE'
                  AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.transaction_id = t.id)
              ) AS receipts""",
        [*ids, *ids, *ids],
        one=True,
    )

    live = query(
        f"""SELECT key FROM stages
            WHERE project_id IN ({placeholders}) AND status = 'in_progress'""",
        ids,
    )

    counts["blocked"] = int(row["blocked"] or 0)
    counts["agreements"] = int(row["agreements"] or 0)
    counts["receipts"] = int(row["receipts"] or 0)
    counts["approvals"] = sum(
        1 for stage in live if (stage_by_key(stage["key"]) or {}).get("requires_authority")
    )
    counts["total"] = (
        counts["blocked"] + counts["approvals"] + counts["receipts"] + counts["agreements"]
    )
    return counts


def platform_totals() -> dict:
    """Money across every workspace, for the staff dashboard."""
    row = query(
        """SELECT
             COALESCE(SUM(CASE WHEN type = 'FUNDING' THEN amount_cents END), 0) AS funded,
             COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount_cents END), 0) AS spent
           FROM transactions""",
        one=True,
    )
    funded = int(row["funded"] or 0)
    spent = int(row["spent"] or 0)
    return {"funded": funded, "spent": spent, "balance": funded - spent}


def all_projects_with_people():
    """Every project with its owner/manager names and money roll-up."""
    rows = query(
        """SELECT p.*,
                  owner.name AS owner_name,
                  owner.email AS owner_email,
                  manager.name AS manager_name,
                  manager.email AS manager_email,
                  (SELECT COALESCE(SUM(amount_cents), 0) FROM transactions t
                    WHERE t.project_id = p.id AND t.type = 'FUNDING') AS funded,
                  (SELECT COALESCE(SUM(amount_cents), 0) FROM transactions t
                    WHERE t.project_id = p.id AND t.type = 'EXPENSE') AS spent,
                  (SELECT COUNT(*) FROM stages s
                    WHERE s.project_id = p.id AND s.status = 'blocked') AS blocked_stages,
                  (SELECT COUNT(*) FROM transactions t
                    LEFT JOIN attachments a ON a.transaction_id = t.id
                    WHERE t.project_id = p.id AND t.type = 'EXPENSE' AND a.id IS NULL) AS missing_receipts
           FROM projects p
           LEFT JOIN users owner ON owner.id = p.owner_id
           LEFT JOIN users manager ON manager.id = p.manager_id
           ORDER BY p.updated_at DESC"""
    )

    for row in rows:
        row["funded"] = int(row["funded"] or 0)
        row["spent"] = int(row["spent"] or 0)
        row["balance"] = row["funded"] - row["spent"]
        row["budget_cents"] = int(row["budget_cents"] or 0)
        row["progress"] = project_progress(stage_rows(row["id"]))
    return rows


def people_overview():
    rows = query(
        """SELECT u.*,
                  (SELECT COUNT(*) FROM projects p WHERE p.owner_id = u.id) AS owned,
                  (SELECT COUNT(*) FROM projects p WHERE p.manager_id = u.id) AS managed,
                  (SELECT MAX(e.created_at) FROM audit_events e WHERE e.user_id = u.id) AS last_seen
           FROM users u
           ORDER BY
             CASE u.role WHEN 'admin' THEN 0 WHEN 'manager' THEN 1 ELSE 2 END,
             u.name"""
    )
    return rows


def recent_events(limit: int = 40, offset_rows: int = 0, search: str = ""):
    where, params = "", []
    if search:
        like = f"%{search}%"
        where = "WHERE e.action LIKE ? OR e.detail LIKE ? OR u.name LIKE ? OR p.name LIKE ?"
        params = [like, like, like, like]
    return query(
        f"""SELECT e.*, u.name AS user_name, p.name AS project_name, p.code AS project_code
           FROM audit_events e
           LEFT JOIN users u ON u.id = e.user_id
           LEFT JOIN projects p ON p.id = e.project_id
           {where}
           ORDER BY e.created_at DESC
           LIMIT ? OFFSET ?""",
        [*params, limit, offset_rows],
    )


def count_events(search: str = "") -> int:
    where, params = "", []
    if search:
        like = f"%{search}%"
        where = "WHERE e.action LIKE ? OR e.detail LIKE ? OR u.name LIKE ? OR p.name LIKE ?"
        params = [like, like, like, like]
    row = query(
        f"""SELECT COUNT(*) AS total
           FROM audit_events e
           LEFT JOIN users u ON u.id = e.user_id
           LEFT JOIN projects p ON p.id = e.project_id
           {where}""",
        params,
        one=True,
    )
    return int(row["total"] or 0)
