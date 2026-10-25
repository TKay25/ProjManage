"""YaVaKa — construction project management for Zimbabwe's diaspora.

Flask application factory. Run locally with:
    python app.py
In production use a WSGI server:
    gunicorn --bind 0.0.0.0:8000 'app:create_app()'
"""

import os
from datetime import datetime
from pathlib import Path

from flask import Flask, g, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import auth
import assistant
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
from paging import page_list
from queries import attention_counts
import observability
import project_kinds
import updates
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
from workspaces import workspaces_for

NAV_ITEMS = [
    {"key": "dashboard", "href": "/app", "label": "Dashboard", "icon": "dashboard"},
    {"key": "updates", "href": "/app/updates", "label": "Updates", "icon": "activity"},
    {"key": "attention", "href": "/app/attention", "label": "Attention", "icon": "bell"},
    {"key": "projects", "href": "/app/projects", "label": "Projects", "icon": "building"},
    {"key": "money", "href": "/app/money", "label": "Money", "icon": "wallet"},
    {"key": "documents", "href": "/app/documents", "label": "Documents", "icon": "folder"},
    {"key": "reports", "href": "/app/reports", "label": "Reports", "icon": "trending-up"},
    {"key": "agreements", "href": "/app/agreements", "label": "Agreements", "icon": "pen"},
    {"key": "search", "href": "/app/search", "label": "Search", "icon": "search"},
    {"key": "suppliers", "href": "/app/suppliers", "label": "Suppliers", "icon": "store"},
    {"key": "whatsapp", "href": "/app/whatsapp", "label": "WhatsApp", "icon": "message"},
    {"key": "settings", "href": "/app/settings", "label": "Settings", "icon": "settings"},
]


# Platforms whose filesystem is discarded on deploy. Render additionally drops
# outbound SMTP on its Free plan.
HOSTED_PLATFORMS = {
    "RENDER": "Render",
    "DYNO": "Heroku",
    "FLY_APP_NAME": "Fly.io",
    "RAILWAY_ENVIRONMENT": "Railway",
}
EMAIL_API_KEYS = (
    "RESEND_API_KEY",
    "BREVO_API_KEY",
    "SENDGRID_API_KEY",
    "MAILJET_API_KEY",
)

# provider key -> (expected prefix, minimum plausible length)
SECRET_SHAPES = {
    "BREVO_API_KEY": ("xkeysib-", 40),
    "RESEND_API_KEY": ("re_", 20),
    "SENDGRID_API_KEY": ("SG.", 60),
    "MAILJET_API_KEY": (None, 20),
}
PLACEHOLDER_MARKERS = ("...", "your", "xxxx", "changeme", "placeholder")


def _warn_if_ephemeral_database(app) -> None:
    """Shout when accounts are about to live on a disk that gets wiped.

    SQLite on Render/Fly/Heroku sits on an ephemeral filesystem, so every
    deploy and idle spin-down deletes the database. The symptom is people
    reporting "it says my email and password do not match" the next day, which
    looks like a login bug and is really data loss.
    """
    platform = next((label for key, label in HOSTED_PLATFORMS.items() if os.environ.get(key)), None)
    if not platform or app.config.get("DATABASE_URL"):
        return

    app.logger.warning(
        "DATA LOSS RISK: running on %s with SQLite (%s). The filesystem is "
        "discarded on every deploy, restart and idle spin-down, which deletes "
        "all accounts and projects. Set DATABASE_URL to a Postgres instance to "
        "keep data. /health reports \"durable\": false until you do.",
        platform,
        app.config.get("DATABASE"),
    )


def _warn_if_smtp_will_be_blocked(app) -> None:
    """Render's Free plan drops outbound SMTP, so a relay fails at send time.

    The failure is a bare "Connection unexpectedly closed", which reads like a
    credentials problem. Say plainly that the port is closed and that an HTTPS
    API key is the way through.
    """
    if not app.config.get("SMTP_HOST"):
        return
    if any(app.config.get(key) for key in EMAIL_API_KEYS):
        return  # an API key takes precedence, so SMTP is never dialled
    if not os.environ.get("RENDER"):
        return

    app.logger.warning(
        "EMAIL WILL FAIL: SMTP_HOST is set to %s:%s, but Render blocks outbound "
        "traffic on ports 25, 465 and 587 for Free web services. Sends will end "
        "with 'Connection unexpectedly closed'. Set BREVO_API_KEY (or another "
        "provider key) instead - HTTPS on 443 is not blocked.",
        app.config.get("SMTP_HOST"),
        app.config.get("SMTP_PORT"),
    )


def _warn_if_placeholder_secrets(app) -> None:
    """Catch pasted template text, which otherwise fails as a silent 401.

    Copying `xkeysib-...` from a README into a hosting dashboard is easy, and
    the only feedback is "email is configured" followed by a rejected send.
    """
    sender = app.config.get("SMTP_FROM_EMAIL") or ""
    if sender and "@" not in sender:
        app.logger.warning(
            "EMAIL CREDENTIALS LOOK WRONG: EMAIL_FROM is %r, which contains no "
            "email address. Save a real address you verified with the provider, "
            "either bare (builds@example.co.zw) or as 'YaVaKa <builds@example.co.zw>'.",
            sender,
        )
    elif sender and ("example." in sender or "verified-address" in sender):
        app.logger.warning(
            "EMAIL CREDENTIALS LOOK WRONG: EMAIL_FROM is %r, which is placeholder "
            "text. Replace it with an address you verified with the provider.",
            sender,
        )

    for key, (prefix, min_length) in SECRET_SHAPES.items():
        value = app.config.get(key) or ""
        if not value:
            continue
        lowered = value.lower()
        if (
            any(marker in lowered for marker in PLACEHOLDER_MARKERS)
            or len(value) < min_length
            or (prefix and not value.startswith(prefix))
        ):
            app.logger.warning(
                "EMAIL CREDENTIALS LOOK WRONG: %s is %d characters and starts "
                "with %r, but a real key starts with %r and is longer. Paste "
                "the value from the provider dashboard, not its example.",
                key,
                len(value),
                value[:12],
                prefix,
            )


def _warn_if_whatsapp_incomplete(app) -> None:
    """A half-configured WhatsApp channel looks live and quietly does nothing.

    Without both a token and a phone number id, outbound replies are stored as
    "simulated" and never leave the server, while the inbox still fills up.
    """
    token = app.config.get("WHATSAPP_TOKEN")
    phone_id = app.config.get("WHATSAPP_PHONE_NUMBER_ID")
    verify_token = app.config.get("WHATSAPP_VERIFY_TOKEN")

    if not any((token, phone_id, verify_token)):
        return  # WhatsApp simply not in use

    if bool(token) != bool(phone_id):
        missing = "WHATSAPP_PHONE_NUMBER_ID" if token else "WHATSAPP_TOKEN"
        app.logger.warning(
            "WHATSAPP IS IN SIMULATOR MODE: %s is missing, so replies are stored "
            "and never sent. Both WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID are "
            "required; /health reports \"whatsapp\": \"partial\" until then.",
            missing,
        )

    if not verify_token:
        app.logger.warning(
            "WHATSAPP WEBHOOK VERIFICATION WILL FAIL: WHATSAPP_VERIFY_TOKEN is "
            "empty, so Meta's 'Verify and save' is refused. Set it to a random "
            "string, then paste the same value into the Meta webhook dialog."
        )


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    if app.config.get("TRUST_PROXY"):
        # Render/Fly/Heroku terminate TLS and forward X-Forwarded-* headers.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    _warn_if_ephemeral_database(app)
    _warn_if_smtp_will_be_blocked(app)
    _warn_if_placeholder_secrets(app)
    _warn_if_whatsapp_incomplete(app)
    # Tracing starts first, so even a rejected CSRF token or an auth failure is
    # logged with a request id.
    observability.init_app(app)
    auth.init_app(app)

    from routes_agreements import DEFAULT_TERMS, bp as agreements_bp
    from routes_admin import bp as admin_bp
    from routes_assistant import bp as assistant_bp
    from routes_attention import bp as attention_bp
    from routes_auth import bp as auth_bp
    from routes_dashboard import bp as dashboard_bp
    from routes_digest import bp as digest_bp
    from routes_documents import bp as documents_bp
    from routes_money import bp as money_bp
    from routes_notifications import bp as notifications_bp
    from routes_projects import bp as projects_bp
    from routes_public import bp as public_bp
    from routes_reports import bp as reports_bp
    from routes_search import bp as search_bp
    from routes_settings import bp as settings_bp
    from routes_suppliers import bp as suppliers_bp
    from routes_team import bp as team_bp
    from routes_updates import bp as updates_bp
    from routes_whatsapp import bp as whatsapp_bp

    for blueprint in (
        public_bp,
        auth_bp,
        dashboard_bp,
        attention_bp,
        projects_bp,
        money_bp,
        notifications_bp,
        updates_bp,
        documents_bp,
        agreements_bp,
        suppliers_bp,
        whatsapp_bp,
        reports_bp,
        settings_bp,
        team_bp,
        search_bp,
        digest_bp,
        admin_bp,
        assistant_bp,
    ):
        app.register_blueprint(blueprint)

    def _asset_version() -> str:
        """Cache-buster from the newest static file, so updated JS/CSS always lands."""
        newest = 0.0
        for path in (app.static_folder and Path(app.static_folder).rglob("*") or []):
            if path.is_file():
                newest = max(newest, path.stat().st_mtime)
        return format(int(newest), "x")

    asset_version = _asset_version()

    def asset_url(filename: str) -> str:
        return f"{url_for('static', filename=filename)}?v={asset_version}"

    app.jinja_env.globals.update(
        csrf_token=auth.csrf_token,
        icon=icon,
        logo_mark=logo_mark,
        brand=brand,
        badge=badge,
        progress_bar=progress_bar,
        progress_ring=progress_ring,
        nav_items=NAV_ITEMS,
        project_kinds=project_kinds.PROJECT_KINDS,
        kind_label=project_kinds.kind_label,
        kind_noun=project_kinds.kind_noun,
        kind_this=project_kinds.kind_this,
        kind_icon=project_kinds.kind_icon,
        tab_items=[item for item in NAV_ITEMS if item["key"] in {"dashboard", "updates", "money", "documents"}],
        asset_url=asset_url,
        page_list=page_list,
        app_name=app.config["APP_NAME"],
        app_tagline=app.config["APP_TAGLINE"],
        current_year=datetime.now().year,
        today_iso=lambda: datetime.now().strftime("%Y-%m-%d"),
        stages_count=len(STAGES),
    stage_catalog=[
        {
            "name": group,
            "stages": [stage for stage in STAGES if stage["group"] == group],
        }
        for group in STAGE_GROUPS
    ],
    stage_total=len(STAGES),
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
        user = getattr(g, "user", None)
        attention = (
            attention_counts([project["id"] for project in auth.accessible_projects(user)])
            if user
            else {"total": 0, "blocked": 0, "approvals": 0, "receipts": 0, "agreements": 0}
        )
        unread_updates = updates.unread_count(user["id"]) if user else 0
        # The bell opens a panel of what changed, so the newest few rows are
        # rendered server-side and each one carries its own destination. Tapping
        # a row goes to that record; the inbox itself is still a real page.
        recent_updates = updates.feed(user["id"], limit=6) if user else []
        return {            "user": user,
            "current_path": request.path,
            # Copy addresses whoever is signed in: a client with a manager reads
            # about what they receive, everyone else about what they record.
            "runs_build": auth.runs_build(user),
            "demo_mode": app.config.get("DEMO_MODE", False),
            # The sidebar owns its own list, so a view that does not pass
            # `projects` can never make it claim there are none.
            "sidebar_projects": auth.accessible_projects(user) if user else [],
            "sidebar_workspaces": workspaces_for(user),
            "attention": attention,
            "unread_updates": unread_updates,
            "recent_updates": recent_updates,
            # Chips under the assistant composer, phrased for the role.
            "aide_suggestions": assistant.suggestions_for(user) if user else (),
            # Also used by the standalone print documents, which cannot read
            # localStorage, so the server must know the choice.
            "palette": (
                (user["palette"] if "palette" in user.keys() and user["palette"] else "forest")
                if user
                else "forest"
            ),
        }

    # ------------------------------------------------------------------
    # Security headers
    # ------------------------------------------------------------------

    CSP = "; ".join(
        [
            "default-src 'self'",
            # Signature images are submitted and replayed as data URLs.
            "img-src 'self' data: blob:",
            # The print sheet and a few layout-critical rules are inline.
            "style-src 'self' 'unsafe-inline'",
            "script-src 'self'",
            "connect-src 'self'",
            "font-src 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "object-src 'none'",
        ]
    )

    @app.after_request
    def harden_response(response):
        headers = response.headers
        headers.setdefault("Content-Security-Policy", CSP)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")

        if request.is_secure:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        # Client money and documents must never sit in a proxy or shared cache.
        if request.path.startswith(("/app", "/admin")) or getattr(g, "user", None):
            headers["Cache-Control"] = "no-store, private, must-revalidate"
            headers["Pragma"] = "no-cache"

        return response

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
        reference = ""
        if code >= 500:
            # One log line with the traceback, keyed by an id the person on the
            # other end can quote.
            reference = observability.report(error, context=f"http {code}")

        return (
            render_template(
                "errors/error.html",
                code=code,
                message=messages.get(code, "Something went wrong."),
                reference=reference,
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
    # The desktop shell pins this to loopback; deployments use a WSGI server.
    host = os.environ.get("HOST", "0.0.0.0")
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n  YaVaKa running at http://localhost:{port}\n")
    app.run(host=host, port=port, debug=debug)
