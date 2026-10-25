"""Supplier directory inside the workspace."""

from flask import Blueprint, g, render_template, request

from auth import accessible_projects, login_required
from db import query
from suppliers import SUPPLIER_CATEGORIES

bp = Blueprint("suppliers", __name__)


@bp.get("/app/suppliers")
@login_required
def index():
    category = request.args.get("category", "").strip()
    search = (request.args.get("q") or "").strip()

    where = []
    params = []
    if category:
        where.append("category = ?")
        params.append(category)
    if search:
        where.append("(name LIKE ? OR description LIKE ? OR tags LIKE ?)")
        params.extend([f"%{search}%"] * 3)

    suppliers = query(
        f"""SELECT * FROM suppliers
            {'WHERE ' + ' AND '.join(where) if where else ''}
            ORDER BY position, name""",
        params,
    )

    # Counts come from the whole directory, not the filtered slice, so the
    # dropdown shows how much sits behind each option.
    category_counts = {
        row["category"]: int(row["total"])
        for row in query(
            "SELECT category, COUNT(*) AS total FROM suppliers GROUP BY category"
        )
    }

    return render_template(
        "app/suppliers.html",
        title="Suppliers",
        active="suppliers",
        projects=accessible_projects(g.user),
        suppliers=suppliers,
        categories=SUPPLIER_CATEGORIES,
        category_counts=category_counts,
        category=category,
        search=search,
    )
