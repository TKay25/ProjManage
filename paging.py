"""Server-side paging shared by the list screens.

Offset paging over SQLite: cheap to reason about, and every list in this app is
small enough that a COUNT(*) beside the page query costs nothing. Page numbers
are clamped so a stale or hand-edited ?page= cannot land on a blank screen.
"""

from math import ceil

from flask import g, request

PAGE_SIZES = (25, 50, 100)


def page_number(param: str = "page") -> int:
    """The requested page, floored at 1 and safe against junk input."""
    raw = request.args.get(param, "1")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def page_size(default: int = 25) -> int:
    """Rows per page, from the signed-in user's saved preference."""
    user = getattr(g, "user", None)
    value = user.get("page_size") if user else None
    return value if value in PAGE_SIZES else default


def page_window(page: int, total: int, size: int) -> tuple[int, int]:
    """Clamp the page to the real range and report how many pages exist."""
    pages = max(1, ceil(total / size)) if size > 0 else 1
    return min(max(1, page), pages), pages


def page_list(page: int, pages: int, window: int = 1):
    """Page numbers for the pager, with None standing in for an ellipsis.

    Small sets render in full. Larger ones keep the first and last page plus a
    window around the current one, and the window widens near either end so the
    pager never shows a lone "1 … 2".
    """
    if pages <= 7:
        return list(range(1, pages + 1))

    start = min(max(2, page - window), pages - 2 * window - 2)
    end = max(min(pages - 1, page + window), 2 * window + 3)

    numbers: list = [1]
    if start > 2:
        numbers.append(None)
    numbers.extend(range(start, end + 1))
    if end < pages - 1:
        numbers.append(None)
    numbers.append(pages)
    return numbers


def offset(page: int, size: int) -> int:
    return max(0, page - 1) * size
