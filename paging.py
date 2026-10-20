"""Server-side paging shared by the list screens.

Offset paging over SQLite: cheap to reason about, and every list in this app is
small enough that a COUNT(*) beside the page query costs nothing. Page numbers
are clamped so a stale or hand-edited ?page= cannot land on a blank screen.
"""

from math import ceil

from flask import request


def page_number(param: str = "page") -> int:
    """The requested page, floored at 1 and safe against junk input."""
    raw = request.args.get(param, "1")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def page_window(page: int, total: int, size: int) -> tuple[int, int]:
    """Clamp the page to the real range and report how many pages exist."""
    pages = max(1, ceil(total / size)) if size > 0 else 1
    return min(max(1, page), pages), pages


def offset(page: int, size: int) -> int:
    return max(0, page - 1) * size
