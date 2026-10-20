"""Read models that aggregate money, stages and activity."""

from datetime import datetime, timezone

from db import query
from stages import project_progress


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
           LEFT JOIN attachments a ON a.transaction_id = t.id
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


def projects_with_summary(projects):
    summaries = []
    for project in projects:
        stages = stage_rows(project["id"])
        summaries.append(
            {
                **project,
                "totals": money_totals(project["id"]),
                "stages": stages,
                "progress": project_progress(stages),
            }
        )
    return summaries


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
