"""Vaka — construction project management for Zimbabwe's diaspora.

Flask application factory. Run with:
    python app.py
"""

import os
from datetime import datetime
from pathlib import Path

from flask import Flask, g, render_template, request

import auth
import db
import seed
from config import Config
from money import (
    cents_to_input,
    format_date,
    format_datetime,
    format_money,
    format_money_compact,
    percent,
    relative_time,
    to_date_input,
)
from stages import (
    PAYMENT_METHODS,
    PROJECT_STATUS_LABELS,
    STAGE_GROUPS,
    STAGES,
    STATUS_LABELS,
    TRANSACTION_CATEGORIES,
    category_label,
    method_label,
    stage_by_key,
    stage_name,
)
from ui import badge, brand, icon, logo_mark, progress_bar, progress_ring, wa_format

NAV_ITEMS = [
    {"key": "dashboard", "href": "/app", "label": "Dashboard", "icon": "dashboard"},
    {"key": "projects", "href": "/app/projects", "label": "Projects", "icon": "building"},
    {"key": "money", "href": "/app/money", "label": "Money", "icon": "wallet"},
    {"key": "documents", "href": "/app/documents", "label": "Documents", "icon": "folder"},
    {"key": "agreements", "href": "/app/agreements", "label": "Agreements", "icon": "pen"},
    {"key": "suppliers", "href": "/app/suppliers", "label": "Suppliers", "icon": "store"},
    {"key": "whatsapp", "href": "/app/whatsapp", "label": "WhatsApp", "icon": "message"},
    {"key": "settings", "href": "/app/settings", "label": "Settings", "icon": "settings"},
]


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    auth.init_app(app)

    from routes_agreements import DEFAULT_TERMS, bp as agreements_bp
    from routes_auth import bp as auth_bp
    from routes_dashboard import bp as dashboard_bp
    from routes_documents import bp as documents_bp
    from routes_money import bp as money_bp
    from routes_projects import bp as projects_bp
    from routes_public import bp as public_bp
    from routes_settings import bp as settings_bp
    from routes_suppliers import bp as suppliers_bp
    from routes_whatsapp import bp as whatsapp_bp

    for blueprint in (
        public_bp,
        auth_bp,
        dashboard_bp,
        projects_bp,
        money_bp,
        documents_bp,
        agreements_bp,
        suppliers_bp,
        whatsapp_bp,
        settings_bp,
    ):
        app.register_blueprint(blueprint)

    app.jinja_env.globals.update(
        csrf_token=auth.csrf_token,
        icon=icon,
        logo_mark=logo_mark,
        brand=brand,
        badge=badge,
        progress_bar=progress_bar,
        progress_ring=progress_ring,
        nav_items=NAV_ITEMS,
        tab_items=[item for item in NAV_ITEMS if item["key"] in {"dashboard", "projects", "money", "documents"}],
        app_name=app.config["APP_NAME"],
        app_tagline=app.config["APP_TAGLINE"],
        current_year=datetime.now().year,
        today_iso=lambda: datetime.now().strftime("%Y-%m-%d"),
        stages_count=len(STAGES),
        DEFAULT_AGREEMENT_TERMS=DEFAULT_TERMS,
        STAGE_GROUPS=STAGE_GROUPS,
        STAGES=STAGES,
        STATUS_LABELS=STATUS_LABELS,
        PROJECT_STATUS_LABELS=PROJECT_STATUS_LABELS,
        TRANSACTION_CATEGORIES=TRANSACTION_CATEGORIES,
        PAYMENT_METHODS=PAYMENT_METHODS,
        category_label=category_label,
        method_label=method_label,
        stage_by_key=stage_by_key,
        stage_name=stage_name,
        whatsapp_configured=bool(
            app.config.get("WHATSAPP_TOKEN") and app.config.get("WHATSAPP_PHONE_NUMBER_ID")
        ),
    )

    app.jinja_env.filters.update(
        money=format_money,
        money_compact=format_money_compact,
        date=format_date,
        datetime=format_datetime,
        date_input=to_date_input,
        money_input=cents_to_input,
        relative=relative_time,
        percent=percent,
        initials=auth.initials,
        wa=wa_format,
    )

    @app.context_processor
    def inject_globals():
        return {"user": getattr(g, "user", None), "current_path": request.path}

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(413)
    @app.errorhandler(500)
    def handle_error(error):
        code = getattr(error, "code", 500)
        messages = {
            400: getattr(error, "description", None) or "That request could not be processed.",
            403: "You do not have access to that page.",
            404: "That page or project could not be found.",
            405: "That action is not allowed here.",
            413: "That file is larger than 8MB. Try a smaller photo or PDF.",
            500: "Something went wrong on our side. Please try again.",
        }
        return (
            render_template(
                "errors/error.html",
                code=code,
                message=messages.get(code, "Something went wrong."),
                title="Error",
            ),
            code,
        )

    with app.app_context():
        seed.ensure_seed()

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n  Vaka running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
