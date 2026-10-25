"""Public marketing pages, PWA assets and health check."""

import os
import tempfile
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory

from suppliers import SUPPLIER_CATEGORIES, SUPPLIERS

bp = Blueprint("public", __name__)

STARTED_AT = time.time()


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
        category_counts=_category_counts(SUPPLIERS),
        category=category,
        search=search,
    )


def _category_counts(items):
    counts = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return counts


@bp.get("/offline")
def offline():
    return render_template("offline.html")


@bp.get("/health")
def health():
    """Readiness probe: database read *and* write, plus uploads writability.

    A deploy that boots against a read-only disk would otherwise look healthy
    and only fail when somebody uploads a receipt.
    """
    from db import execute, get_db, is_postgres, now_iso

    try:
        get_db().execute("SELECT 1").fetchone()
        execute(
            "CREATE TABLE IF NOT EXISTS _healthcheck (id INTEGER PRIMARY KEY, at TEXT)"
        )
        execute(
            """INSERT INTO _healthcheck (id, at) VALUES (1, ?)
               ON CONFLICT (id) DO UPDATE SET at = EXCLUDED.at""",
            (now_iso(),),
        )
    except Exception as error:  # noqa: BLE001 - health checks must never raise
        return jsonify({"status": "error", "detail": str(error)}), 503

    uploads = "ok"
    try:
        directory = Path(current_app.config["UPLOAD_FOLDER"])
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".probe-"):
            pass
    except OSError:
        uploads = "unavailable"

    return jsonify(
        {
            "status": "ok",
            "app": current_app.config["APP_NAME"],
            "database": "postgres" if is_postgres() else "sqlite",
            # SQLite on a hosted platform with no persistent disk is wiped on
            # every deploy, restart and spin-down. Say so out loud: silently
            # losing accounts is how people end up unable to sign in.
            "durable": is_postgres() or not _ephemeral_host(),
            "email": _email_channel(),
            "whatsapp": _whatsapp_channel(),
            "uploads": uploads,
            "uptime_s": round(time.time() - STARTED_AT),
        }
    )


def _whatsapp_channel() -> str:
    """live = messages really send; partial = half configured; simulator = off."""
    token = current_app.config.get("WHATSAPP_TOKEN")
    phone_id = current_app.config.get("WHATSAPP_PHONE_NUMBER_ID")
    if token and phone_id:
        return "live"
    return "partial" if (token or phone_id) else "simulator"


def _email_channel() -> str:
    """Name the outbound path so a misconfiguration is visible without logs."""
    from notifications import api_provider

    provider = api_provider()
    if provider:
        return f"{provider}-api"
    return "smtp" if current_app.config.get("SMTP_HOST") else "none"


def _ephemeral_host() -> bool:
    """True on a platform whose filesystem is discarded between deploys."""
    return any(
        os.environ.get(name)
        for name in ("RENDER", "DYNO", "FLY_APP_NAME", "VERCEL", "RAILWAY_ENVIRONMENT")
    )


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
