"""Money helpers. Amounts are stored as integer US cents everywhere."""

from datetime import datetime, timezone

CURRENCY = "USD"


def format_money(cents: int | None) -> str:
    value = (cents or 0) / 100
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def format_money_compact(cents: int | None) -> str:
    value = (cents or 0) / 100
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"{sign}${value / 1_000:.1f}k"
    return f"{sign}${value:,.0f}"


def parse_money_to_cents(raw) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(round(float(raw) * 100))
    cleaned = "".join(char for char in str(raw) if char in "0123456789.-")
    if not cleaned:
        return 0
    try:
        return int(round(float(cleaned) * 100))
    except ValueError:
        return 0


def cents_to_input(cents: int | None) -> str:
    return f"{(cents or 0) / 100:.2f}"


def format_date(value) -> str:
    date = _to_datetime(value)
    return f"{date.day} {date:%b %Y}" if date else "—"


def format_datetime(value) -> str:
    date = _to_datetime(value)
    return f"{date.day} {date:%b %Y}, {date:%H:%M}" if date else "—"


def to_date_input(value) -> str:
    date = _to_datetime(value)
    return date.strftime("%Y-%m-%d") if date else ""


def relative_time(value) -> str:
    date = _to_datetime(value)
    if not date:
        return ""
    seconds = (datetime.now(timezone.utc) - date).total_seconds()
    units = [
        ("year", 31_536_000),
        ("month", 2_592_000),
        ("week", 604_800),
        ("day", 86_400),
        ("hour", 3_600),
        ("minute", 60),
    ]
    for unit, size in units:
        if abs(seconds) >= size:
            amount = int(round(seconds / size))
            return f"{amount} {unit}{'s' if amount != 1 else ''} ago"
    return "just now"


def percent(part: int, whole: int) -> int:
    if not whole:
        return 0
    return max(0, min(100, round((part / whole) * 100)))


def _to_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    normalised = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None

    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
