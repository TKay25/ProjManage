"""Small text helpers shared by templates."""

import re

from markupsafe import Markup, escape

_BOLD = re.compile(r"\*([^*\n]+)\*")
_ITALIC = re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")


def wa_format(text) -> Markup:
    """Renders WhatsApp-style *bold* and _italic_ markup, escaping everything else."""
    escaped = str(escape(text or ""))
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)
    return Markup(escaped)

from markupsafe import Markup

ICONS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="2"/><rect x="14" y="3" width="7" height="5" rx="2"/><rect x="14" y="12" width="7" height="9" rx="2"/><rect x="3" y="16" width="7" height="5" rx="2"/>',
    "building": '<path d="M3 21h18"/><path d="M5 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16"/><path d="M15 9h2a2 2 0 0 1 2 2v10"/><path d="M9 7h2M9 11h2M9 15h2"/>',
    "wallet": '<path d="M20 12V8a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h14a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6"/><path d="M16 14h.01"/>',
    "folder": '<path d="M4 20h16a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1h-7l-2-2H4a1 1 0 0 0-1 1v13a1 1 0 0 0 1 1Z"/>',
    "pen": '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    "store": '<path d="M3 9 4.5 4h15L21 9"/><path d="M3 9h18v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/><path d="M9 20v-6h6v6"/>',
    "message": '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-4-.9L3 21l1.9-4.4a8.4 8.4 0 1 1 16.1-5.1Z"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "arrow-left": '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "alert": '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/>',
    "download": '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "map-pin": '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>',
    "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3-8.7A2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    "sparkles": '<path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9Z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9Z"/>',
    "camera": '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z"/><circle cx="12" cy="13" r="3.5"/>',
    "trash": '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/>',
    "eye": '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z"/><circle cx="12" cy="12" r="3"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18"/>',
    "trending-up": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "receipt": '<path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2Z"/><path d="M9 8h6M9 12h6M9 16h3"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M17 5.2a3.5 3.5 0 0 1 0 6.6M18 20a6.6 6.6 0 0 0-2-4.7"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 1 1 8 0v3"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.7 3.8 9S14.5 18.4 12 21c-2.5-2.6-3.8-5.7-3.8-9S9.5 5.6 12 3Z"/>',
    "wifi-off": '<path d="m2 2 20 20"/><path d="M8.5 8.5a11 11 0 0 1 12 1.5"/><path d="M5 12a11 11 0 0 1 3-1.8"/><path d="M8.5 15.5a6 6 0 0 1 7 0"/><path d="M12 19h.01"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 4 13V8a8 8 0 0 1 8-8h8v8a8 8 0 0 1-8 8Z"/><path d="M4 21c2-7 7-11 13-13"/>',
    "play": '<path d="m7 4 13 8-13 8Z"/>',
    "home": '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/>',
}

BADGES = {
    "complete": ("success", "Complete"),
    "in_progress": ("live", "In progress"),
    "blocked": ("danger", "Blocked"),
    "pending": ("muted", "Not started"),
    "planning": ("muted", "Planning"),
    "on_hold": ("danger", "On hold"),
    "completed": ("success", "Completed"),
    "draft": ("muted", "Draft"),
    "awaiting_signature": ("warn", "Awaiting signature"),
    "signed": ("success", "Signed"),
    "void": ("muted", "Void"),
}


def icon(name: str, size: int = 20, css_class: str = "") -> Markup:
    path = ICONS.get(name, ICONS["sparkles"])
    return Markup(
        f'<svg class="icon {css_class}" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{path}</svg>'
    )


def logo_mark(size: int = 40, css_class: str = "") -> Markup:
    return Markup(
        f'<svg class="logo-mark {css_class}" width="{size}" height="{size}" viewBox="0 0 64 64" '
        'role="img" aria-label="Vaka">'
        '<rect width="64" height="64" rx="15" fill="#0F5D46"/>'
        '<path d="M12 32 32 15l20 17" fill="none" stroke="#F7F4EF" stroke-width="4.2" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<rect x="17" y="34" width="5.5" height="15" rx="2.4" fill="#C8963E"/>'
        '<rect x="26.5" y="29" width="5.5" height="20" rx="2.4" fill="#E3B968"/>'
        '<rect x="36" y="24" width="5.5" height="25" rx="2.4" fill="#C8963E"/>'
        "</svg>"
    )


def brand(href: str = "/", tone: str = "dark") -> Markup:
    return Markup(
        f'<a class="brand brand--{tone}" href="{href}">{logo_mark(38)}'
        '<span class="brand-text">'
        '<span class="brand-name">Vaka</span>'
        '<span class="brand-tag">Build from anywhere</span>'
        "</span></a>"
    )


def badge(status: str | None) -> Markup:
    tone, label = BADGES.get(status or "", ("muted", (status or "").replace("_", " ").title()))
    return Markup(f'<span class="badge badge-{tone}">{label}</span>')


def progress_bar(value: int, tone: str = "") -> Markup:
    width = max(0, min(100, int(round(value or 0))))
    extra = f" progress-{tone}" if tone else ""
    return Markup(
        f'<div class="progress{extra}" role="progressbar" aria-valuenow="{width}" '
        f'aria-valuemin="0" aria-valuemax="100"><span style="width:{width}%"></span></div>'
    )


def progress_ring(value: int, size: int = 96) -> Markup:
    percent_value = max(0, min(100, int(round(value or 0))))
    radius = (size - 10) / 2
    circumference = 2 * 3.14159265 * radius
    offset = circumference - (percent_value / 100) * circumference
    centre = size / 2
    return Markup(
        f'<svg class="ring" width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="{percent_value}% complete">'
        f'<circle class="ring-track" cx="{centre}" cy="{centre}" r="{radius}" fill="none" stroke-width="7"/>'
        f'<circle class="ring-value" cx="{centre}" cy="{centre}" r="{radius}" fill="none" stroke-width="7" '
        f'stroke-linecap="round" stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}" '
        f'transform="rotate(-90 {centre} {centre})"/>'
        f'<text class="ring-text" x="50%" y="50%" dominant-baseline="central" text-anchor="middle">{percent_value}%</text>'
        "</svg>"
    )
