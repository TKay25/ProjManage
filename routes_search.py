"""One search box across everything the user can already see.

Results are always filtered through the caller's accessible projects, so search
can never surface a build the user could not open directly.
"""

from flask import Blueprint, g, jsonify, render_template, request

from auth import accessible_projects, login_required
from db import query
from money import format_money
from stages import category_label, stage_name

bp = Blueprint("search", __name__)

RESULT_LIMIT = 12
QUICK_LIMIT = 5


def _project_ids(user):
    return [project["id"] for project in accessible_projects(user)]


@bp.get("/app/api/quick-find")
@login_required
def quick_find():
    """Compact JSON feed for the command palette.

    Same access rules as the full search page: only projects the caller may
    already open, and never more than a handful of rows per group.
    """
    term = (request.args.get("q") or "").strip()
    projects = accessible_projects(g.user)
    groups = []

    if term:
        like = f"%{term}%"
        ids = [project["id"] for project in projects]

        if ids:
            placeholders = ",".join("?" for _ in ids)

            matched = query(
                f"""SELECT id, name, code FROM projects
                    WHERE id IN ({placeholders})
                      AND (name LIKE ? OR code LIKE ? OR suburb LIKE ? OR city LIKE ?)
                    ORDER BY created_at DESC LIMIT ?""",
                [*ids, like, like, like, like, QUICK_LIMIT],
            )
            if matched:
                groups.append(
                    {
                        "label": "Projects",
                        "items": [
                            {
                                "title": row["name"],
                                "meta": row["code"],
                                "href": f"/app/projects/{row['id']}",
                            }
                            for row in matched
                        ],
                    }
                )

            money_rows = query(
                f"""SELECT t.id, t.description, t.amount_cents, t.type, t.project_id
                    FROM transactions t
                    WHERE t.project_id IN ({placeholders})
                      AND (t.description LIKE ? OR t.reference LIKE ?)
                    ORDER BY t.occurred_at DESC LIMIT ?""",
                [*ids, like, like, QUICK_LIMIT],
            )
            if money_rows:
                groups.append(
                    {
                        "label": "Money",
                        "items": [
                            {
                                "title": row["description"],
                                "meta": (
                                    ("+" if row["type"] == "FUNDING" else "−")
                                    + format_money(row["amount_cents"])
                                ),
                                "href": f"/app/money?project={row['project_id']}&q={term}",
                            }
                            for row in money_rows
                        ],
                    }
                )

            docs = query(
                f"""SELECT a.id, a.original_name, a.kind, a.project_id
                    FROM attachments a
                    WHERE a.project_id IN ({placeholders}) AND a.original_name LIKE ?
                    ORDER BY a.created_at DESC LIMIT ?""",
                [*ids, like, QUICK_LIMIT],
            )
            if docs:
                groups.append(
                    {
                        "label": "Documents",
                        "items": [
                            {
                                "title": row["original_name"],
                                "meta": row["kind"].title(),
                                "href": f"/app/documents?project={row['project_id']}&q={term}",
                            }
                            for row in docs
                        ],
                    }
                )

            agreements = query(
                f"""SELECT ag.id, ag.title, ag.status, ag.project_id
                    FROM agreements ag
                    WHERE ag.project_id IN ({placeholders}) AND ag.title LIKE ?
                    ORDER BY ag.created_at DESC LIMIT ?""",
                [*ids, like, QUICK_LIMIT],
            )
            if agreements:
                groups.append(
                    {
                        "label": "Agreements",
                        "items": [
                            {
                                "title": row["title"],
                                "meta": row["status"].replace("_", " ").title(),
                                "href": f"/app/agreements?project={row['project_id']}",
                            }
                            for row in agreements
                        ],
                    }
                )

    return jsonify({"ok": True, "term": term, "groups": groups})


@bp.get("/app/search")
@login_required
def index():
    term = (request.args.get("q") or "").strip()
    projects = accessible_projects(g.user)
    by_id = {project["id"]: project for project in projects}

    results = {"projects": [], "money": [], "documents": [], "agreements": [], "stages": []}
    if not term or not projects:
        return render_template(
            "app/search.html",
            title="Search",
            active="search",
            term=term,
            results=results,
            total=0,
        )

    like = f"%{term}%"
    ids = list(by_id)
    placeholders = ",".join("?" for _ in ids)

    for row in query(
        f"""SELECT * FROM projects
            WHERE id IN ({placeholders})
              AND (name LIKE ? OR code LIKE ? OR suburb LIKE ? OR city LIKE ?
                   OR stand_number LIKE ? OR description LIKE ?)
            ORDER BY created_at DESC LIMIT ?""",
        [*ids, like, like, like, like, like, like, RESULT_LIMIT],
    ):
        results["projects"].append(row)

    for row in query(
        f"""SELECT t.*, p.name AS project_name, p.code AS project_code
            FROM transactions t JOIN projects p ON p.id = t.project_id
            WHERE t.project_id IN ({placeholders})
              AND (t.description LIKE ? OR t.reference LIKE ? OR t.category LIKE ?)
            ORDER BY t.occurred_at DESC LIMIT ?""",
        [*ids, like, like, like, RESULT_LIMIT],
    ):
        row = dict(row)
        row["category_label"] = category_label(row["category"])
        results["money"].append(row)

    for row in query(
        f"""SELECT a.*, p.name AS project_name, s.name AS stage_name
            FROM attachments a
            JOIN projects p ON p.id = a.project_id
            LEFT JOIN stages s ON s.project_id = a.project_id AND s.key = a.stage_key
            WHERE a.project_id IN ({placeholders})
              AND (a.original_name LIKE ? OR a.kind LIKE ?)
            ORDER BY a.created_at DESC LIMIT ?""",
        [*ids, like, like, RESULT_LIMIT],
    ):
        results["documents"].append(row)

    for row in query(
        f"""SELECT ag.*, p.name AS project_name
            FROM agreements ag JOIN projects p ON p.id = ag.project_id
            WHERE ag.project_id IN ({placeholders})
              AND (ag.title LIKE ? OR ag.scope LIKE ? OR ag.client_name LIKE ?)
            ORDER BY ag.created_at DESC LIMIT ?""",
        [*ids, like, like, like, RESULT_LIMIT],
    ):
        results["agreements"].append(row)

    # Stage names come from the code, not the database, so match them here.
    needle = term.lower()
    for project_id, project in by_id.items():
        for row in query(
            "SELECT * FROM stages WHERE project_id = ? ORDER BY position", (project_id,)
        ):
            if needle in stage_name(row["key"]).lower():
                results["stages"].append({**row, "project_name": project["name"]})
                if len(results["stages"]) >= RESULT_LIMIT:
                    break

    total = sum(len(items) for items in results.values())

    return render_template(
        "app/search.html",
        title="Search",
        active="search",
        term=term,
        results=results,
        total=total,
        by_id=by_id,
    )
