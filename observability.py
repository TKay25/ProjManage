"""Request tracing, structured logs and a single place errors are reported.

Every request gets an id (honouring an inbound ``X-Request-ID`` so a proxy's
trace survives), that id is echoed back in the response and shown on the error
page. One line is logged per request with the timing and query count, in JSON
when ``LOG_JSON=1`` so a log drain can index it.

Set ``ERROR_WEBHOOK_URL`` to have unhandled exceptions POSTed as JSON to an
external collector; nothing is sent when the setting is empty.
"""

import json
import logging
import time
import urllib.request
import uuid
from threading import Thread

from flask import current_app, g, request

logger = logging.getLogger("yavaka.request")
error_logger = logging.getLogger("yavaka.error")

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def _clean_id(value: str) -> str:
    candidate = (value or "").strip()[:64]
    if candidate and set(candidate) <= _SAFE_ID:
        return candidate
    return uuid.uuid4().hex[:16]


def _emit(target, level: int, event: str, **fields):
    if current_app.config.get("LOG_JSON"):
        record = {"event": event, "ts": round(time.time(), 3), **fields}
        target.log(level, json.dumps(record, default=str))
        return

    detail = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value not in (None, "", 0)
    )
    target.log(level, f"{event} {detail}".strip())


def init_app(app):
    app.before_request(_start)
    app.after_request(_finish)

    app.extensions["error_webhook_url"] = app.config.get("ERROR_WEBHOOK_URL") or ""

    if not app.logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        app.logger.addHandler(handler)
    app.logger.setLevel(app.config.get("LOG_LEVEL", "INFO"))


def _start():
    g.request_id = _clean_id(request.headers.get(REQUEST_ID_HEADER, ""))
    g.request_started = time.perf_counter()


def _finish(response):
    started = getattr(g, "request_started", None)
    if started is None:
        return response

    request_id = getattr(g, "request_id", "")
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id

    duration_ms = (time.perf_counter() - started) * 1000
    db_ms = round(getattr(g, "query_ms", 0.0), 1)
    queries = getattr(g, "query_count", 0)

    if not request.path.startswith("/static"):
        response.headers["Server-Timing"] = (
            f'app;dur={duration_ms:.1f}, db;desc="{queries} queries";dur={db_ms}'
        )

        user = getattr(g, "user", None)
        _emit(
            logger,
            logging.INFO,
            "request",
            request_id=request_id,
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 1),
            db_ms=db_ms,
            queries=queries,
            user_id=user["id"] if user else None,
            ip=request.headers.get("X-Forwarded-For", request.remote_addr or "")
            .split(",")[0]
            .strip(),
        )

    return response


def report(error: Exception, *, context: str = "") -> str:
    """Logs an unhandled error with its request id and returns that id.

    The id is what the person on the other end can quote, so a support request
    can be traced to a single log line instead of a timestamp guess.
    """
    request_id = getattr(g, "request_id", "") or uuid.uuid4().hex[:16]
    payload = {
        "request_id": request_id,
        "path": request.path,
        "method": request.method,
        "context": context,
        "error": f"{type(error).__name__}: {error}",
    }

    error_logger.error(
        json.dumps(payload)
        if current_app.config.get("LOG_JSON")
        else " ".join(f"{key}={value}" for key, value in payload.items() if value),
        exc_info=error,
    )

    url = current_app.extensions.get("error_webhook_url")
    if url:
        Thread(
            target=_post_webhook,
            args=(url, payload),
            name="yavaka-error-report",
            daemon=True,
        ).start()

    return request_id


def _post_webhook(url: str, payload: dict):
    """Best-effort delivery: an error report must never raise or block."""
    try:
        body = json.dumps(payload).encode("utf-8")
        request_obj = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request_obj, timeout=4):
            pass
    except Exception:  # noqa: BLE001 - reporting is best effort
        error_logger.debug("error webhook delivery failed", exc_info=True)
