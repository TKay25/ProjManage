"""Lightweight asynchronous email and WhatsApp project-update delivery."""

import json
import logging
import re
import smtplib
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from flask import current_app

from db import execute, get_db, is_postgres, log_event, new_id, now_iso, query
from money import format_money
from queries import money_totals, stage_rows
from stages import project_progress
from whatsapp import normalize_phone, send_whatsapp_project_update

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="yavaka-notifications")
logger = logging.getLogger("yavaka.notifications")

# HTTPS email APIs, in detection order. Render's Free plan (and many corporate
# networks) block outbound SMTP on ports 25/465/587, so a key here is the only
# way to send mail from those environments.
API_PROVIDERS = {
    "resend": ("RESEND_API_KEY", "https://api.resend.com/emails"),
    "brevo": ("BREVO_API_KEY", "https://api.brevo.com/v3/smtp/email"),
    "sendgrid": ("SENDGRID_API_KEY", "https://api.sendgrid.com/v3/mail/send"),
}


def api_provider() -> str:
    """Which HTTPS provider is configured, or "" for none/SMTP."""
    configured = {
        name: current_app.config.get(key)
        for name, (key, _) in API_PROVIDERS.items()
    }
    explicit = (current_app.config.get("EMAIL_API_PROVIDER") or "").strip().lower()
    if explicit in API_PROVIDERS:
        return explicit if configured[explicit] else ""
    for name in API_PROVIDERS:
        if configured[name]:
            return name
    return ""


def email_configured() -> bool:
    if api_provider():
        return bool(current_app.config.get("SMTP_FROM_EMAIL"))
    return bool(current_app.config.get("SMTP_HOST") and current_app.config.get("SMTP_FROM_EMAIL"))


def _from_parts() -> tuple[str, str]:
    """Split `Name <addr@host>` into a display name and a bare address."""
    raw = (current_app.config.get("SMTP_FROM_EMAIL") or "").strip()
    match = re.match(r"^(.*?)\s*<([^>]+)>\s*$", raw)
    if match:
        return match.group(1).strip().strip('"'), match.group(2).strip()
    return "", raw


def _api_request(provider: str, recipient: str, subject: str, body: str):
    """Build the URL and payload for a provider. Separated out so it is testable."""
    key_setting, url = API_PROVIDERS[provider]
    name, address = _from_parts()
    key = current_app.config.get(key_setting)

    if provider == "resend":
        headers = {"Authorization": f"Bearer {key}"}
        payload = {
            "from": f"{name} <{address}>" if name else address,
            "to": [recipient],
            "subject": subject,
            "text": body,
        }
    elif provider == "brevo":
        # Brevo puts the key in a header and needs sender split into parts.
        headers = {"api-key": key}
        sender = {"email": address}
        if name:
            sender["name"] = name
        payload = {
            "sender": sender,
            "to": [{"email": recipient}],
            "subject": subject,
            "textContent": body,
        }
    else:  # sendgrid
        headers = {"Authorization": f"Bearer {key}"}
        sender = {"email": address}
        if name:
            sender["name"] = name
        payload = {
            "personalizations": [{"to": [{"email": recipient}]}],
            "from": sender,
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        }

    return url, headers, payload


def _send_via_api(provider: str, recipient: str, subject: str, body: str) -> dict:
    url, headers, payload = _api_request(provider, recipient, subject, body)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # Resend sits behind Cloudflare, which rejects urllib's default
            # "Python-urllib/3.x" agent with a 403 (error code 1010).
            "User-Agent": "YaVaKa/1.0 (+https://yavaka.onrender.com)",
            "Accept": "application/json",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            response.read()
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", "replace")[:400]
        except OSError:
            pass
        finally:
            error.close()
        # The numeric code is what the operator can act on, so keep it first.
        return {"status": "failed", "error": f"{error.code} {detail}".strip()}
    except (urllib.error.URLError, OSError) as error:
        return {"status": "failed", "error": str(error)}
    return {"status": "sent"}


def _send_email(recipient: str, subject: str, body: str) -> dict:
    provider = api_provider()
    if provider:
        return _send_via_api(provider, recipient, subject, body)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = current_app.config["SMTP_FROM_EMAIL"]
    message["To"] = recipient
    message.set_content(body)

    host = current_app.config["SMTP_HOST"]
    port = current_app.config["SMTP_PORT"]
    timeout = 8
    context = ssl.create_default_context()

    try:
        if current_app.config.get("SMTP_USE_SSL"):
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                _smtp_authenticate(server)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if current_app.config.get("SMTP_USE_TLS", True):
                    server.starttls(context=context)
                    server.ehlo()
                _smtp_authenticate(server)
                server.send_message(message)
    except (OSError, smtplib.SMTPException, ssl.SSLError) as error:
        return {"status": "failed", "error": str(error)}

    return {"status": "sent"}


def _smtp_authenticate(server):
    username = current_app.config.get("SMTP_USERNAME")
    password = current_app.config.get("SMTP_PASSWORD")
    if username:
        server.login(username, password or "")


def _claim_next_delivery():
    connection = get_db()
    if is_postgres():
        # One statement claims the row, so concurrent workers cannot pick the
        # same delivery even without an explicit transaction.
        row = connection.execute(
            """WITH next AS (
                   SELECT id FROM notification_outbox
                   WHERE status = 'pending'
                   ORDER BY created_at, id
                   LIMIT 1
                   FOR UPDATE SKIP LOCKED
               )
               UPDATE notification_outbox o
               SET status = 'sending', attempts = o.attempts + 1, claimed_at = %s
               FROM next
               WHERE o.id = next.id AND o.status = 'pending'
               RETURNING o.*""",
            (now_iso(),),
        ).fetchone()
        return dict(row) if row else None

    connection.execute("BEGIN IMMEDIATE")
    try:
        stale_before = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        connection.execute(
            """UPDATE notification_outbox
               SET status = 'pending', claimed_at = NULL
               WHERE status = 'sending'
                 AND (claimed_at IS NULL OR claimed_at < ?)""",
            (stale_before,),
        )
        row = connection.execute(
            """SELECT * FROM notification_outbox
               WHERE status = 'pending'
               ORDER BY created_at, id
               LIMIT 1"""
        ).fetchone()
        if row is None:
            connection.commit()
            return None

        connection.execute(
            """UPDATE notification_outbox
               SET status = 'sending', attempts = attempts + 1, claimed_at = ?
               WHERE id = ? AND status = 'pending'""",
            (now_iso(), row["id"]),
        )
        connection.commit()
        delivery = dict(row)
        delivery["attempts"] += 1
        return delivery
    except Exception:
        connection.rollback()
        raise


def _deliver(delivery) -> dict:
    if delivery["channel"] == "email":
        return _send_email(delivery["recipient"], delivery["subject"], delivery["body"])
    if delivery["channel"] == "whatsapp":
        return send_whatsapp_project_update(delivery["recipient"], delivery["body"])
    return {"status": "failed", "error": "Unsupported notification channel."}


def dispatch_pending(app, limit=30) -> int:
    """Drain a small outbox batch. Network delivery never blocks the user flow."""
    delivered = 0
    with app.app_context():
        for _ in range(limit):
            delivery = _claim_next_delivery()
            if not delivery:
                break

            result = {"status": "failed", "error": "Delivery failed."}
            for attempt in range(3):
                if attempt:
                    execute(
                        "UPDATE notification_outbox SET attempts = attempts + 1 WHERE id = ?",
                        (delivery["id"],),
                    )
                    delivery["attempts"] += 1
                try:
                    result = _deliver(delivery)
                except Exception as error:
                    logger.exception(
                        "Unexpected %s notification delivery error for project %s",
                        delivery["channel"],
                        delivery["project_id"],
                    )
                    result = {"status": "failed", "error": str(error)}
                if result.get("status") == "sent":
                    break
                if attempt < 2:
                    time.sleep(1 + attempt)

            sent = result.get("status") == "sent"
            status = "sent" if sent else "failed"
            error = (result.get("error") or "Provider did not confirm delivery.")[:500]
            execute(
                """UPDATE notification_outbox
                   SET status = ?, last_error = ?, sent_at = ?, claimed_at = NULL
                   WHERE id = ?""",
                (
                    status,
                    None if sent else error,
                    now_iso() if sent else None,
                    delivery["id"],
                ),
            )

            if sent:
                delivered += 1
                log_event(
                    None,
                    delivery["project_id"],
                    "notification.sent",
                    f"{delivery['channel']} update sent to project owner",
                )
            else:
                logger.error(
                    "Could not deliver %s update for project %s: %s",
                    delivery["channel"],
                    delivery["project_id"],
                    error,
                )
                log_event(
                    None,
                    delivery["project_id"],
                    "notification.failed",
                    f"{delivery['channel']} update failed after {delivery['attempts']} attempts: {error}",
                )

    return delivered


def schedule_dispatch(app) -> None:
    future = _executor.submit(dispatch_pending, app)

    def report_worker_failure(completed):
        error = completed.exception()
        if error:
            app.logger.error(
                "Notification outbox worker stopped unexpectedly",
                exc_info=(type(error), error, error.__traceback__),
            )

    future.add_done_callback(report_worker_failure)


def send_email_async(recipient: str, subject: str, body: str) -> bool:
    """Fire-and-forget email for things that are not project updates (invites).

    Returns False when SMTP is not configured, so the caller can fall back to
    showing the message in the app instead.
    """
    if not recipient or not email_configured():
        return False

    app = current_app._get_current_object()

    def worker():
        with app.app_context():
            result = _send_email(recipient, subject, body)
            if result.get("status") != "sent":
                logger.warning("Could not email %s: %s", recipient, result.get("error"))

    _executor.submit(worker)
    return True


def queue_manager_update(project_id, manager_id, manager_name, headline, detail) -> int:
    """Queue an update only when it was posted by this project's assigned manager."""
    project = query(
        """SELECT p.id, p.name, p.code, p.manager_id,
                  COALESCE(NULLIF(p.client_email, ''), owner.email) AS client_email,
                  COALESCE(NULLIF(p.client_whatsapp, ''), owner.phone) AS client_phone
           FROM projects p
           JOIN users owner ON owner.id = p.owner_id
           WHERE p.id = ?""",
        (project_id,),
        one=True,
    )
    if not project or project["manager_id"] != manager_id:
        return 0

    email_ready = email_configured()
    whatsapp_ready = bool(
        current_app.config.get("WHATSAPP_TOKEN")
        and current_app.config.get("WHATSAPP_PHONE_NUMBER_ID")
        and current_app.config.get("WHATSAPP_UPDATE_TEMPLATE")
    )
    phone = normalize_phone(project["client_phone"] or "")
    channels = []

    if email_ready and project["client_email"]:
        channels.append(("email", project["client_email"]))
    elif not email_ready:
        current_app.logger.warning(
            "Manager update email notification skipped: no email provider is configured "
            "(set an API key such as BREVO_API_KEY, or SMTP_HOST + EMAIL_FROM)."
        )

    if whatsapp_ready and phone:
        channels.append(("whatsapp", phone))
    elif not whatsapp_ready:
        current_app.logger.warning(
            "Manager update WhatsApp notification skipped: Meta credentials and an approved update template are required."
        )

    if not channels:
        return 0

    stages = stage_rows(project_id)
    progress = project_progress(stages)
    balance = money_totals(project_id)["balance"]
    project_label = f"{project['name']} ({project['code']})"
    safe_detail = str(detail or "").strip()[:400]
    body = (
        f"{manager_name} posted an update to {project_label}.\n\n"
        f"{headline}\n{safe_detail}\n\n"
        f"Build progress: {progress}%\n"
        f"Available balance: {format_money(balance)}"
    )
    subject = f"YaVaKa update: {project['name']}"
    event_key = new_id()
    timestamp = now_iso()

    for channel, recipient in channels:
        execute(
            """INSERT INTO notification_outbox
                 (id, event_key, project_id, channel, recipient, subject, body, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                new_id(),
                event_key,
                project_id,
                channel,
                recipient,
                subject if channel == "email" else None,
                body,
                timestamp,
            ),
        )

    schedule_dispatch(current_app._get_current_object())
    return len(channels)
