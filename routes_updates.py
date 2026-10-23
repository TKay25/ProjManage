"""The update inbox: what changed across the builds you own or manage."""

from datetime import date, datetime

from flask import Blueprint, g, jsonify, render_template, request

from auth import accessible_projects, login_required
from paging import offset, page_number, page_size, page_window
import updates

bp = Blueprint("updates", __name__)


def _day_label(stamp: str) -> str:
    """Group rows by calendar day without shipping a time library to the client."""
    try:
        moment = datetime.fromisoformat(stamp).date()
    except (TypeError, ValueError):
        return "Earlier"
    today = date.today()
    if moment == today:
        return "Today"
    if (today - moment).days == 1:
        return "Yesterday"
    # %-d is not portable (Windows), so drop the leading zero by hand.
    return f"{moment.strftime('%A')} {moment.day} {moment.strftime('%B')}"


def _grouped(items):
    """Rows in date order, each with the day heading it belongs under."""
    groups = []
    for item in items:
        label = _day_label(item["created_at"])
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "rows": []})
        groups[-1]["rows"].append(item)
    return groups


@bp.get("/app/updates")
@login_required
def index():
    kind = request.args.get("kind", "all")
    if kind not in updates.KINDS:
        kind = "all"

    # Highlight what was new on this visit, then clear the badge: opening the
    # inbox is the acknowledgement, the same way an email client behaves.
    new_ids = updates.unread_ids(g.user["id"])

    total_rows = updates.count(g.user["id"], kind)
    size = page_size(default=25)
    page, page_count = page_window(page_number(), total_rows, size)
    items = updates.feed(
        g.user["id"], kind=kind, limit=size, offset_rows=offset(page, size)
    )
    unread = len(new_ids)
    updates.mark_all_read(g.user["id"])

    return render_template(
        "app/updates.html",
        title="Updates",
        active="updates",
        projects=accessible_projects(g.user),
        kinds=[
            {"key": key, "label": label, "count": updates.count(g.user["id"], key)}
            for key, (label, _prefixes) in updates.KINDS.items()
        ],
        kind=kind,
        groups=_grouped(items),
        new_ids=new_ids,
        unread=unread,
        total_rows=total_rows,
        page=page,
        page_count=page_count,
        pager_endpoint="updates.index",
        pager_args={"kind": kind},
    )


@bp.get("/app/api/updates/unread")
@login_required
def unread():
    """Polled by the workspace so a client sees a manager's change as it lands."""
    count = updates.unread_count(g.user["id"])
    latest = updates.latest_unread(g.user["id"])
    return jsonify(
        {
            "ok": True,
            "count": count,
            "latest": (
                {
                    "title": latest["title"],
                    "project": latest["project_name"],
                    "href": latest["href"] or "/app/updates",
                }
                if latest
                else None
            ),
        }
    )
