"""Public marketing pages, PWA assets and health check."""

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory

from suppliers import SUPPLIER_CATEGORIES, SUPPLIERS

bp = Blueprint("public", __name__)


@bp.get("/")
def landing():
    return render_template("landing.html", suppliers=SUPPLIERS[:4])


@bp.get("/suppliers")
def suppliers_directory():
    category = request.args.get("category", "").strip()
    search = request.args.get("q", "").strip()

    items = SUPPLIERS
    if category:
        items = [item for item in items if item["category"] == category]
    if search:
        needle = search.lower()
        items = [
            item
            for item in items
            if needle in item["name"].lower()
            or needle in item["description"].lower()
            or needle in " ".join(item.get("tags", [])).lower()
        ]

    return render_template(
        "suppliers_public.html",
        suppliers=items,
        categories=SUPPLIER_CATEGORIES,
        category=category,
        search=search,
    )


@bp.get("/offline")
def offline():
    return render_template("offline.html")


@bp.get("/health")
def health():
    return jsonify({"status": "ok", "app": current_app.config["APP_NAME"]})


@bp.get("/sw.js")
def service_worker():
    response = send_from_directory(
        current_app.static_folder, "sw.js", mimetype="application/javascript"
    )
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@bp.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(
        current_app.static_folder,
        "manifest.webmanifest",
        mimetype="application/manifest+json",
    )
