"""One search box across everything the user can already see.

Results are always filtered through the caller's accessible projects, so search
can never surface a build the user could not open directly.
"""

from flask import Blueprint, g, render_template, request

from auth import accessible_projects, login_required
from db import query
from stages import category_label, stage_name

bp = Blueprint("search", __name__)

RESULT_LIMIT = 12


def _project_ids(user):
    return [project["id"] for project in accessible_projects(user)]


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
