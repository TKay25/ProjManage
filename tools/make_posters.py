"""Generates the YaVaKa advertising poster set as SVG.

Run from the repository root:

    python tools/make_poster_art.py      # once, or after replacing a photo
    python tools/make_posters.py

Posters land in static/posters/ at 1080x1350 (Instagram / WhatsApp Status
portrait). Every poster carries a dark photographic backdrop: real site,
renovation and finished-home photography, cropped to portrait by
tools/make_poster_art.py and embedded as a data URI so the SVG stays
self-contained. Export a PNG with any headless browser, e.g.:

    chrome --headless --screenshot=out.png --window-size=1080,1350 poster.svg
"""

import base64
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "static" / "posters"
ART_DIR = ROOT / "static" / "poster-art"

W, H = 1080, 1350
M = 72
CONTENT_W = W - (M * 2)

FOREST_DEEP = "#0a0f1c"
FOREST = "#24395f"
FOREST_MID = "#1a2b4a"
CREAM = "#ffffff"
SAND = "#f5f7fa"
SAND_DEEP = "#eceff4"
BRASS = "#a55f36"
BRASS_LIGHT = "#ba7044"
BRASS_DIM = "#8c4f2b"
INK = "#0f1626"
INK_SOFT = "#3e4a60"

SERIF = "Georgia, 'Times New Roman', serif"
SANS = "Arial, Helvetica, sans-serif"

RATIO_SERIF_BOLD = 0.53

# Fixed vertical rhythm shared by every poster, so the set looks like one family.
HEAD_BASELINE = 322
CTA_HEIGHT = 66
FOOTER_BASELINE = 1272

# Photography. Each name is a 4:5 crop written by tools/make_poster_art.py.
PHOTOS_BY_SLUG = {
    "you-cant-be-on-site": "site-finish",
    "tranche-two-went-quiet": "site-house",
    "your-contractor-our-standard": "site-framing",
    "two-ways-to-build": "site-row",
    "we-vet-the-builder": "electrician",
    "watch-it-happen-live": "steel",
    "diaspora-price": "house",
    "the-receipt": "renovation",
    "nineteen-stages": "site-walls",
    "dont-use-family": "site-interior",
    "half-a-house": "site-house",
    "the-last-ten-percent": "bathroom",
    "resolving-differences": "site-interior",
    "the-site-goes-quiet": "site-walls",
    "we-can-build-it": "steel",
    "one-phone-number": "site-finish",
    "progress-in-your-pocket": "kitchen",
    "keys-and-file": "house",
    "verify-quote-record": "site-framing",
    "already-three-months-in": "site-house",
    "no-need-to-sack-anybody": "electrician",
    "cannot-audit-what-nobody-recorded": "site-interior",
    "every-project-one-screen": "site-row",
    "the-paperwork-does-itself": "joinery",
    "win-clients-on-evidence": "site-finish",
    "built-for-the-distance": "site-finish",
    "the-second-opinion": "site-walls",
    "four-payments-ahead": "kitchen",
    "run-more-builds": "site-row",
    "who-we-are": "site-finish",
    "the-first-question": "site-house",
    "nobody-on-site": "site-walls",
    "cash-with-no-paper": "renovation",
    "the-quote-that-grew": "kitchen",
    "three-contractors-one-standard": "site-framing",
    "the-family-argument": "site-interior",
    "the-photo-that-proves-nothing": "electrician",
    "the-stage-nobody-signed": "steel",
    "one-tranche-too-far": "site-house",
    "distance-is-not-permission": "house",
    "whose-gate-is-this": "site-walls",
    "stage-gate-discipline": "site-framing",
    "funding-not-feelings": "steel",
    "first-day-on-site": "site-walls",
    "the-quiet-variation": "bathroom",
    "nobody-chases-for-you": "electrician",
    "what-the-money-bought": "renovation",
    "the-receipt-is-the-argument": "kitchen",
    "the-money-that-vanished": "site-house",
    "why-the-quote-was-low": "kitchen",
    "rental-management": "site-finish",
    "rent-invoices": "joinery",
    "rent-receipts": "site-finish",
    "arrears-ageing": "house",
    "tenant-statements": "joinery",
    "lease-signing": "house",
    "inspections": "site-interior",
    "work-orders": "electrician",
    "property-reports": "site-row",
    "two-doors": "site-finish",
    "project-kinds": "kitchen",
    "kitchen-fitout": "kitchen",
    "renovation-record": "renovation",
    "signed-agreements": "joinery",
    "reports-and-pack": "site-walls",
    "whatsapp-assistant": "electrician",
    "suppliers": "site-walls",
    "account-security": "steel",
    "offline-copy": "site-house",
    "everything": "house",
}


@lru_cache(maxsize=None)
def photo_data_uri(name):
    path = ART_DIR / f"{name}.jpg"
    if not path.exists():
        raise SystemExit(
            f"missing poster art {path.name}; run tools/make_poster_art.py"
        )
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def scene_photo(p):
    photo = p.get("photo") or PHOTOS_BY_SLUG.get(p["slug"])
    if not photo:
        raise SystemExit(f"{p['slug']}: no photo mapped")
    return photo


def esc(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def fit(value, max_w, base, ratio=RATIO_SERIF_BOLD):
    if not value:
        return base
    return min(base, max_w / (len(value) * ratio))


def text(x, y, value, size, fill, weight=700, family=SERIF, anchor="start",
         italic=False, spacing=0, opacity=None):
    attrs = [
        f'x="{x}"', f'y="{y}"', f'fill="{fill}"',
        f'font-family="{family}"', f'font-size="{size}"',
    ]
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if italic:
        attrs.append('font-style="italic"')
    if spacing:
        attrs.append(f'letter-spacing="{spacing}"')
    if anchor != "start":
        attrs.append(f'text-anchor="{anchor}"')
    if opacity is not None:
        attrs.append(f'opacity="{opacity}"')
    return f'<text {" ".join(attrs)}>{esc(value)}</text>'


def rect(x, y, w, h, fill, rx=0, stroke=None, stroke_w=1, opacity=None):
    attrs = [f'x="{x}"', f'y="{y}"', f'width="{w}"', f'height="{h}"']
    if rx:
        attrs.append(f'rx="{rx}"')
    attrs.append(f'fill="{fill}"')
    if stroke:
        attrs.append(f'stroke="{stroke}"')
        attrs.append(f'stroke-width="{stroke_w}"')
    if opacity is not None:
        attrs.append(f'opacity="{opacity}"')
    return f'<rect {" ".join(attrs)}/>'


def pill(x, y, label, size=15, spacing=1.8, height=42):
    width = len(label) * size * (0.63 + spacing / size) + 52 + 18
    return "".join([
        rect(x, y, round(width), height, "#fffdf8", rx=height / 2, opacity=0.1),
        f'<circle cx="{x + 25}" cy="{y + height / 2}" r="5" fill="{BRASS_LIGHT}"/>',
        text(x + 44, y + height / 2 + size * 0.36, label, size, "#f3e6cb",
             weight=700, family=SANS, spacing=spacing),
    ])


def logo(tone="light"):
    """The same mark the web app draws in ui.logo_mark().

    Geometry is copied from that 64-unit viewBox and scaled, so the poster and
    the site cannot drift apart: copper roof pitch, walls in the text colour and
    a copper foundation line. No tile — the mark sits straight on the poster.
    """
    face = CREAM if tone == "light" else INK
    sub = "#d2ded7" if tone == "light" else "#6b7a70"
    x0, y0, size = M, 62, 54
    scale = size / 64.0

    def px(value):
        return round(x0 + value * scale, 2)

    def py(value):
        return round(y0 + value * scale, 2)

    mark = "".join(
        [
            f'<path d="M{px(14)} {py(30)} L{px(32)} {py(14.5)} L{px(50)} {py(30)}" '
            f'fill="none" stroke="#CC8C64" stroke-width="{round(5.2 * scale, 2)}" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
            f'<path d="M{px(15)} {py(31)} V{py(46)} M{px(49)} {py(31)} V{py(46)}" '
            f'fill="none" stroke="{face}" stroke-width="{round(4.4 * scale, 2)}" '
            'stroke-linecap="round"/>',
            f'<rect x="{px(10)}" y="{py(49.6)}" width="{round(44 * scale, 2)}" '
            f'height="{round(4.4 * scale, 2)}" rx="{round(2.2 * scale, 2)}" fill="#BA7044"/>',
        ]
    )

    return "".join(
        [
            mark,
            text(M + 70, y0 + 38, "YaVaKa", 32, face, weight=700, family=SANS, spacing=-0.5),
            text(M + 72, y0 + 62, "BUILD FROM ANYWHERE", 13, sub, weight=700, family=SANS, spacing=2.2),
        ]
    )


def cta(x, y, label, fill=BRASS, color="#142f27", arrow="#142f27", h=72):
    width = round(len(label) * 13.4 + 140)
    return "".join([
        rect(x, y, width, h, fill, rx=18),
        text(x + 30, y + h / 2 + 7, label, 21, color, weight=700, family=SANS, spacing=0.4),
        f'<path d="M{x + width - 62} {y + h / 2}h25m-9-9 9 9-9 9" fill="none" stroke="{arrow}" '
        f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>',
    ])


def footer(strapline, dark=True):
    color = "#d9e2dc" if dark else "#65746a"
    return "".join([
        text(M, FOOTER_BASELINE, "yavaka.onrender.com", 18, color, weight=400, family=SANS),
        text(W - M, FOOTER_BASELINE, strapline, 14, color, weight=400, family=SANS,
             anchor="end", spacing=1.9),
    ])


ICON_PATHS = {
    "check": '<path d="M5 12.6l4.3 4.3L19 7.4"/>',
    "wallet": '<rect x="3" y="6.5" width="18" height="12" rx="3"/><path d="M3 10.5h18"/>'
              '<circle cx="16.8" cy="14.6" r="1.1" fill="{s}" stroke="none"/>',
    "chat": '<path d="M3.2 6.4h17.6v8.8a2 2 0 0 1-2 2h-7l-4.6 3.6v-3.6H5.2a2 2 0 0 1-2-2Z"/>',
    "shield": '<path d="M12 3.2l8 3v5c0 6-8 9.6-8 9.6S4 17.2 4 11.2v-5Z"/>',
    "receipt": '<path d="M5 3.2h14v17.6l-3.5-2-3.5 2-3.5-2L5 20.8Z"/>'
               '<path d="M8.6 8.4h6.8M8.6 12.2h6.8"/>',
    "clock": '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.4v5l3.4 2"/>',
    "lock": '<rect x="4.8" y="10.2" width="14.4" height="10" rx="2.6"/>'
            '<path d="M8 10.2V7.4a4 4 0 0 1 8 0v2.8"/>',
    "globe": '<circle cx="12" cy="12" r="8.4"/>'
             '<path d="M3.8 12h16.4M12 3.8c3 3.6 3 12.8 0 16.4-3-3.6-3-12.8 0-16.4Z"/>',
    "camera": '<rect x="3" y="7" width="18" height="13" rx="3"/><circle cx="12" cy="13.4" r="4"/>'
              '<path d="M8.4 7l1.6-2.6h4L15.6 7"/>',
    "folder": '<path d="M3.2 20V6.2a1.2 1.2 0 0 1 1.2-1.2h5.4l2.2 2.2h7.6a1.2 1.2 0 0 1 1.2 1.2V20Z"/>',
}

BRASS_GLYPHS = {"wallet", "receipt", "clock", "camera"}


def icon(glyph, cx, cy, colour=None):
    """Draws a glyph from the 24x24 set centred on (cx, cy)."""
    stroke = colour or (BRASS_DIM if glyph in BRASS_GLYPHS else FOREST)
    path = ICON_PATHS[glyph].replace("{s}", BRASS_DIM)
    return (f'<g transform="translate({cx - 12} {cy - 12})" fill="none" stroke="{stroke}" '
            f'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">{path}</g>')


def proof_row(points, y):
    """Three compact proof cards in one row, so the promise stays the hero."""
    gap = 12
    card_w = (CONTENT_W - gap * 2) / 3
    card_h = 92
    out = []
    for index, (glyph, label, sub) in enumerate(points[:3]):
        x = M + index * (card_w + gap)
        out.append(rect(x, y, card_w, card_h, "#ffffff", rx=18, opacity=0.08))
        out.append(rect(x, y, card_w, card_h, "none", rx=18, stroke=CREAM,
                        stroke_w=1, opacity=0.16))
        out.append(f'<circle cx="{x + 36}" cy="{y + card_h / 2}" r="18" '
                   f'fill="#ffffff" opacity=".12"/>')
        out.append(icon(glyph, x + 36, y + card_h / 2,
                        colour=BRASS_LIGHT if glyph in BRASS_GLYPHS else CREAM))
        out.append(text(x + 66, y + 39, label, 12.5, "#f3e6cb", weight=700,
                        family=SANS, spacing=1.3))
        out.append(text(x + 66, y + 62, sub, 13.5, "#d5e1da", weight=400,
                        family=SANS))
    return "".join(out)


def photo_layer(name, x=0, y=0, w=W, h=H):
    return (
        f'<image x="{x}" y="{y}" width="{w}" height="{h}" '
        f'preserveAspectRatio="xMidYMid slice" href="{photo_data_uri(name)}"/>'
    )


def photo_full(name):
    """Full-bleed site photograph under the family's dark overlay."""
    return "".join([
        rect(0, 0, W, H, "url(#sky)"),
        photo_layer(name),
        rect(0, 0, W, H, "#0d2b24", opacity=0.34),
        rect(0, 0, W, H, "url(#scene)"),
        rect(0, 0, W, H, "url(#scene-side)"),
    ])


def photo_band(name, height, path=None, clip_id="photo-band"):
    """A photographic header, optionally clipped to the layout's wave."""
    shape = (
        f'<path d="{path}"/>' if path
        else f'<rect x="0" y="0" width="{W}" height="{height}"/>'
    )
    image_h = max(height, 480)
    return "".join([
        f'<clipPath id="{clip_id}">{shape}</clipPath>',
        f'<g clip-path="url(#{clip_id})">',
        photo_layer(name, 0, 0, W, image_h),
        rect(0, 0, W, image_h, "#0d2b24", opacity=0.34),
        rect(0, 0, W, image_h, "url(#scene-band)"),
        rect(0, 0, W, image_h, "url(#scene-side)"),
        "</g>",
    ])


def dark_backdrop(name=None):
    if name:
        base = photo_full(name)
        contours = (
            f'<g fill="none" stroke="#e2bd77" stroke-opacity=".2">'
            f'<path d="M-20 230c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/>'
            f'<path d="M-20 249c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/></g>'
        )
    else:
        base = "".join([
            rect(0, 0, W, H, "url(#sky)"),
            f'<path d="M0 627c172-84 305-89 476-43s347 28 604-71v310H0Z" fill="#0b4035" opacity=".85"/>',
            f'<path d="M0 716c190-84 355-67 526-34s348 13 554-82v192H0Z" fill="{FOREST_DEEP}"/>',
        ])
        contours = (
            f'<g fill="none" stroke="#d8b36d" stroke-opacity=".22">'
            f'<path d="M-20 230c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/>'
            f'<path d="M-20 249c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/></g>'
        )
    return "".join([
        base,
        f'<circle cx="944" cy="102" r="176" fill="{BRASS}" opacity=".1"/>',
        contours,
    ])


def head_block(lines, start=HEAD_BASELINE, base=60):
    size = round(fit(max(lines, key=len), CONTENT_W, base))
    out, y = [], start
    for value, colour in lines:
        out.append(text(M, y, value, size, CREAM if colour == "cream" else BRASS_LIGHT,
                        weight=700, spacing=-size * 0.026))
        y += size * 1.24
    return "".join(out), y


def sub_block(lines, y, fill="#d5e1da", size=21, dy=30):
    out = []
    for line in lines:
        out.append(text(M + 4, y, line, size, fill, weight=400, family=SANS))
        y += dy
    return "".join(out), y


def wrap_lines(value, width):
    words = value.split()
    out, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) <= width or not line:
            line = candidate
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def deck_block(p, y, size=25, max_chars=68, dy=34, fill="#e3eae5", limit=3):
    """The complete explanation under the headline, never more than three lines."""
    lines = wrap_lines(p["desc"], max_chars)[:limit]
    return sub_block(lines, y, fill=fill, size=size, dy=dy)


def accent_rule(y=226, width=64, colour=BRASS):
    return rect(M, y, width, 5, colour, rx=2.5)


def svg_doc(title, desc, body):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" '
        'viewBox="0 0 1080 1350" role="img" aria-labelledby="title desc">\n'
        f'  <title id="title">{esc(title)}</title>\n'
        f'  <desc id="desc">{esc(desc)}</desc>\n'
        "  <defs>\n"
        '    <linearGradient id="sky" x1="0" y1="0" x2="1" y2="1">\n'
        '      <stop offset="0" stop-color="#114f40"/>\n'
        f'      <stop offset="1" stop-color="{FOREST_DEEP}"/>\n'
        "    </linearGradient>\n"
        '    <linearGradient id="paper" x1="0" y1="0" x2="1" y2="1">\n'
        '      <stop offset="0" stop-color="#fbf8f1"/>\n'
        f'      <stop offset="1" stop-color="{SAND_DEEP}"/>\n'
        "    </linearGradient>\n"
        '    <linearGradient id="scene" x1="0" y1="0" x2="0" y2="1">\n'
        '      <stop offset="0" stop-color="#040a12" stop-opacity=".94"/>\n'
        '      <stop offset=".22" stop-color="#040a12" stop-opacity=".76"/>\n'
        '      <stop offset=".48" stop-color="#071420" stop-opacity=".62"/>\n'
        '      <stop offset=".74" stop-color="#040a12" stop-opacity=".8"/>\n'
        '      <stop offset="1" stop-color="#040a12" stop-opacity=".97"/>\n'
        "    </linearGradient>\n"
        '    <linearGradient id="scene-band" x1="0" y1="0" x2="0" y2="1">\n'
        '      <stop offset="0" stop-color="#040a12" stop-opacity=".93"/>\n'
        '      <stop offset=".45" stop-color="#071420" stop-opacity=".8"/>\n'
        '      <stop offset="1" stop-color="#040a12" stop-opacity=".92"/>\n'
        "    </linearGradient>\n"
        '    <linearGradient id="scene-side" x1="0" y1="0" x2="1" y2="0">\n'
        '      <stop offset="0" stop-color="#040a12" stop-opacity=".55"/>\n'
        '      <stop offset=".55" stop-color="#040a12" stop-opacity=".08"/>\n'
        '      <stop offset="1" stop-color="#040a12" stop-opacity="0"/>\n'
        "    </linearGradient>\n"
        '    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">\n'
        '      <feDropShadow dx="0" dy="18" stdDeviation="18" flood-color="#16372d" '
        'flood-opacity=".15"/>\n'
        "    </filter>\n"
        "  </defs>\n"
        f"  {body}\n"
        "</svg>\n"
    )


# ---------------------------------------------------------------- layouts

def layout_statement(p):
    body = [
        dark_backdrop(scene_photo(p)),
        logo("light"),
        pill(M + 2, 157, p["eyebrow"]),
        accent_rule(),
    ]
    # A soft accent glow behind the headline, mirrored so the feed varies.
    mirror = p.get("panel", "right") == "left"
    body.append(
        f'<circle cx="{240 if mirror else 900}" cy="430" r="300" '
        f'fill="{BRASS}" opacity=".07"/>'
    )
    head, y = head_block(p["lines"], start=300, base=78)
    body.append(head)
    deck, _ = deck_block(p, y + 10)
    body.append(deck)
    body.append(proof_row(p["points"], 846))
    body.append(cta(M, 1034, p["cta"], h=72))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_twotone(p):
    split = p.get("split", 660)
    body = [
        rect(0, 0, W, H, SAND),
        photo_band(scene_photo(p), split, clip_id="twotone-band"),
        f'<circle cx="944" cy="96" r="180" fill="{BRASS}" opacity=".09"/>',
        f'<path d="M0 {split - 120}c190-54 352-26 527 6s367-8 553-66v180H0Z" fill="{FOREST_DEEP}"/>',
        f'<g fill="none" stroke="#d8b36d" stroke-opacity=".2">'
        f'<path d="M-20 214c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/></g>',
        logo("light"),
        pill(M + 2, 152, p["eyebrow"]),
    ]
    head, y = head_block(p["lines"], start=300, base=62)
    body.append(head)
    deck, _ = deck_block(p, y + 8, size=23, max_chars=66, dy=31)
    body.append(deck)

    body.append(text(M, split + 46, p["answer_head"], 32, INK, weight=700))
    body.append(accent_rule(split + 64, width=84))

    row = split + 132
    for index, (label, sub_line) in enumerate(p["answer"], start=1):
        body.append(text(M, row, f"{index:02d}", 14, BRASS_DIM, weight=700,
                         family=SANS, spacing=1.4))
        body.append(text(M + 54, row, label, 19, INK, weight=700, family=SANS))
        body.append(text(M + 470, row, sub_line, 15.5, INK_SOFT, weight=400,
                         family=SANS))
        body.append(f'<path d="M{M} {row + 22}h{CONTENT_W}" stroke="#ded4c2" '
                    f'stroke-width="1.5"/>')
        row += 70

    body.append(cta(M, 1040, p["cta"], h=66))
    body.append(footer(p["footer"], dark=False))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_quote(p):
    body = [
        rect(0, 0, W, H, "url(#paper)"),
        photo_band(
            scene_photo(p),
            300,
            path="M0 0h1080v250c-208 74-372 46-556 2S198 196 0 270Z",
            clip_id="quote-band",
        ),
        f'<circle cx="956" cy="129" r="178" fill="{BRASS}" opacity=".12"/>',
        logo("light"),
        text(M + 6, 152, p["eyebrow"], 15, BRASS_LIGHT, weight=700, family=SANS, spacing=3.2),
        text(M - 18, 430, "\u201c", 210, BRASS, weight=700, opacity=0.14),
    ]

    lines = p["quote_lines"]
    size = round(fit(max(lines, key=len), CONTENT_W, 70))
    y = 470
    for index, line in enumerate(lines):
        colour = BRASS_DIM if index == len(lines) - 1 and p.get("last_brass") else INK
        body.append(text(M + 4, y, line, size, colour, weight=700,
                         spacing=-size * 0.03))
        y += size * 1.14

    body.append(accent_rule(y + 18, width=120))
    body.append(text(M + 4, y + 62, p["attribution"], 17, INK_SOFT,
                     weight=400, family=SANS, spacing=1.2))
    deck, _ = deck_block(p, y + 104, size=22, max_chars=72, dy=30, fill=INK_SOFT)
    body.append(deck)

    body.append(cta(M, 1066, p["cta"], fill=FOREST, color=CREAM,
                    arrow=BRASS_LIGHT, h=66))
    body.append(footer(p["footer"], dark=False))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_stat(p):
    body = [
        dark_backdrop(scene_photo(p)),
        f'<circle cx="868" cy="430" r="300" fill="{BRASS}" opacity=".07"/>',
        logo("light"),
        pill(M + 2, 157, p["eyebrow"]),
        accent_rule(),
    ]
    head, y = head_block(p["lines"], start=300, base=68)
    body.append(head)
    deck, _ = deck_block(p, y + 10)
    body.append(deck)

    body.append(text(M - 6, 830, p["stat"], 220, BRASS_LIGHT, weight=700, spacing=-8))
    body.append(text(M + 4, 874, p["stat_label"], 22, CREAM, weight=700,
                     family=SANS, spacing=1.3))
    if p.get("points"):
        body.append(proof_row(p["points"], 916))
    elif p.get("gold"):
        body.append(text(M + 4, 936, p["gold"], 22, BRASS_LIGHT,
                         weight=700, family=SANS))

    body.append(cta(M, 1054, p["cta"], h=72))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


def _gate_rail_vertical(p):
    """The gates down the left margin, the argument beside them.

    Six posters share the gate idea, so the rail cannot always run the same way
    or the set starts to look like one image repeated with new words.
    """
    gates = p["gates"]
    current = p.get("current", 0)
    body = [dark_backdrop(scene_photo(p)), logo("light"), pill(M + 2, 157, p["eyebrow"])]

    rail_x = M + 26
    top, step = 322, 96
    last_y = top + step * (len(gates) - 1)
    body.append(
        f'<path d="M{rail_x} {top}v{last_y - top}" stroke="{CREAM}" '
        f'stroke-opacity=".16" stroke-width="4"/>'
    )
    body.append(
        f'<path d="M{rail_x} {top}v{step * current}" stroke="{BRASS_LIGHT}" stroke-width="4"/>'
    )
    for index, label in enumerate(gates):
        cy = top + step * index
        done = index <= current
        radius = 17 if index == current else 10
        body.append(
            f'<circle cx="{rail_x}" cy="{cy}" r="{radius}" '
            f'fill="{BRASS if index == current else (FOREST_MID if done else "#0e2f28")}" '
            f'stroke="{BRASS_LIGHT if done else CREAM}" '
            f'stroke-opacity="{1 if done else 0.28}" stroke-width="3"/>'
        )
        body.append(
            text(
                rail_x + 30,
                cy + 6,
                label,
                15,
                CREAM if index == current else "#8fa79b",
                weight=700,
                family=SANS,
                spacing=1.2,
            )
        )

    column = rail_x + 190
    size = round(min(52, 620 / (max(len(line) for line, _c in p["lines"]) * 0.53)))
    y = top + 6
    for value, colour in p["lines"]:
        body.append(
            text(column, y, value, size, CREAM if colour == "cream" else BRASS_LIGHT,
                 weight=700, spacing=-size * 0.026)
        )
        y += size * 1.2
    y += 10
    for line in wrap_lines(p["desc"], 62)[:4]:
        body.append(text(column, y, line, 18, "#d5e1da", weight=400, family=SANS))
        y += 27

    card_top = last_y + 74
    body.append(rect(M, card_top, CONTENT_W, 146, "#ffffff", rx=26, opacity=0.06))
    body.append(rect(M, card_top, CONTENT_W, 146, "none", rx=26, stroke=CREAM,
                     stroke_w=1, opacity=0.16))
    body.append(f'<circle cx="{M + 62}" cy="{card_top + 73}" r="24" fill="{BRASS}" opacity=".16"/>')
    body.append(icon("lock", M + 62, card_top + 73, colour=BRASS_LIGHT))
    body.append(text(M + 110, card_top + 60, p["gate_title"], 21, CREAM, weight=700, family=SANS))
    body.append(text(M + 110, card_top + 92, p["gate_body"], 16, "#c3d2c9", weight=400, family=SANS))

    body.append(cta(M, card_top + 206, p["cta"], h=CTA_HEIGHT))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_gate(p):
    """A build read as a sequence of gates, one of them always the one in front.

    Composition is a rail rather than a stacked column, so a reader scrolling a
    status feed sees something other than another block of type. The rail runs
    horizontally or down the margin depending on the poster.
    """
    if p.get("rail") == "v":
        return _gate_rail_vertical(p)

    body = [
        dark_backdrop(scene_photo(p)),
        f'<circle cx="150" cy="330" r="230" fill="{BRASS}" opacity=".06"/>',
        logo("light"),
        pill(M + 2, 157, p["eyebrow"]),
    ]
    head, y = head_block(p["lines"], start=306, base=64)
    body.append(head)
    deck, _ = deck_block(p, y + 10)
    body.append(deck)

    gates = p["gates"]
    current = p.get("current", 0)
    rail_y = 660
    left, right = M + 26, W - M - 26
    step = (right - left) / (len(gates) - 1)
    body.append(f'<path d="M{left} {rail_y}h{right - left}" stroke="{CREAM}" '
                f'stroke-opacity=".16" stroke-width="4"/>')
    body.append(f'<path d="M{left} {rail_y}h{step * current}" stroke="{BRASS_LIGHT}" '
                f'stroke-width="4"/>')
    for index, label in enumerate(gates):
        cx = left + step * index
        done = index <= current
        body.append(
            f'<circle cx="{cx}" cy="{rail_y}" r="{19 if index == current else 13}" '
            f'fill="{BRASS if index == current else (FOREST_MID if done else "#0e2f28")}" '
            f'stroke="{BRASS_LIGHT if done else CREAM}" '
            f'stroke-opacity="{1 if done else 0.28}" stroke-width="3"/>'
        )
        if done and index != current:
            body.append(f'<circle cx="{cx}" cy="{rail_y}" r="5" fill="{BRASS_LIGHT}"/>')
        anchor = "start" if index == 0 else ("end" if index == len(gates) - 1 else "middle")
        body.append(
            text(cx, rail_y + 62, label, 14,
                 CREAM if index == current else "#9fb3a8",
                 weight=700, family=SANS, anchor=anchor, spacing=1.2)
        )

    body.append(rect(M, 800, CONTENT_W, 152, "#ffffff", rx=26, opacity=0.06))
    body.append(rect(M, 800, CONTENT_W, 152, "none", rx=26, stroke=CREAM,
                     stroke_w=1, opacity=0.16))
    body.append(f'<circle cx="{M + 62}" cy="876" r="24" fill="{BRASS}" opacity=".16"/>')
    body.append(icon("lock", M + 62, 876, colour=BRASS_LIGHT))
    body.append(text(M + 110, 862, p["gate_title"], 22, CREAM, weight=700, family=SANS))
    body.append(text(M + 110, 896, p["gate_body"], 17, "#c3d2c9", weight=400, family=SANS))

    body.append(cta(M, 1000, p["cta"], h=72))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_ledger(p):
    """The receipt itself as the hero: money in, money out, proof against each.

    A torn paper slip replaces the usual card panel, because "there is a receipt
    for this" is the whole argument and the object should say it before the copy.
    """
    slip_x, slip_w = M, CONTENT_W
    slip_top = 470
    slip_bottom = 990
    tooth, depth = 22, 20

    teeth = []
    x = slip_x
    while x + tooth <= slip_x + slip_w:
        teeth.append(f"L{x + tooth / 2} {slip_bottom + depth}")
        teeth.append(f"L{x + tooth} {slip_bottom}")
        x += tooth
    torn = (
        f'<path d="M{slip_x} {slip_bottom}{"".join(teeth)}'
        f'L{slip_x + slip_w} {slip_bottom}L{slip_x + slip_w} {slip_bottom - depth}'
        f'L{slip_x} {slip_bottom - depth}Z" fill="{CREAM}"/>'
    )

    body = [
        rect(0, 0, W, H, "url(#paper)"),
        photo_band(
            scene_photo(p),
            432,
            path="M0 0h1080v412c-208 74-372 46-556 2S198 358 0 432Z",
            clip_id="ledger-band",
        ),
        f'<circle cx="908" cy="122" r="164" fill="{BRASS}" opacity=".12"/>',
        logo("light"),
        text(M + 6, 178, p["eyebrow"], 15, BRASS_LIGHT, weight=700,
             family=SANS, spacing=3.2),
        f'<ellipse cx="{W / 2}" cy="{slip_bottom + 52}" rx="286" ry="16" '
        f'fill="{INK}" opacity=".05"/>',
        rect(slip_x, slip_top, slip_w, slip_bottom - slip_top, CREAM, rx=26),
        rect(slip_x, slip_top, slip_w, 96, SAND_DEEP, rx=26),
        rect(slip_x, slip_top + 62, slip_w, 34, SAND_DEEP),
        f'<circle cx="{slip_x + 62}" cy="{slip_top + 48}" r="21" fill="#f2ece0"/>',
        icon("receipt", slip_x + 62, slip_top + 48),
        text(slip_x + 106, slip_top + 44, p["slip_head"], 17, INK,
             weight=700, family=SANS, spacing=1.6),
        text(slip_x + 106, slip_top + 70, p["slip_sub"], 15, INK_SOFT,
             weight=400, family=SANS),
    ]

    head, y = head_block(p["lines"], start=300, base=52)
    body.append(head)

    row_y = slip_top + 150
    for label, value, glyph in p["entries"]:
        body.append(f'<circle cx="{slip_x + 62}" cy="{row_y - 8}" r="19" fill="#f2ece0"/>')
        body.append(icon(glyph, slip_x + 62, row_y - 8))
        body.append(text(slip_x + 104, row_y, label, 18, INK_SOFT,
                         weight=400, family=SANS))
        body.append(text(slip_x + slip_w - 52, row_y, value, 20, INK,
                         weight=700, family=SANS, anchor="end"))
        body.append(f'<path d="M{slip_x + 48} {row_y + 26}h{slip_w - 96}" '
                    f'stroke="#ded4c2" stroke-width="2" stroke-dasharray="7 9"/>')
        row_y += 74

    body.append(f'<path d="M{slip_x + 48} {row_y - 30}h{slip_w - 96}" '
                f'stroke="{INK}" stroke-width="3"/>')
    body.append(text(slip_x + 48, row_y + 6, p["total_label"], 17, INK,
                     weight=700, family=SANS, spacing=1.4))
    body.append(text(slip_x + slip_w - 52, row_y + 8, p["total_value"], 30, FOREST,
                     weight=700, family=SANS, anchor="end"))
    body.append(torn)

    body.append(cta(M, 1050, p["cta"], fill=FOREST, color=CREAM,
                    arrow=BRASS_LIGHT, h=66))
    body.append(footer(p["footer"], dark=False))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_feature(p):
    """A dark site photograph behind a two-column grid of capabilities."""
    body = [
        dark_backdrop(scene_photo(p)),
        f'<circle cx="880" cy="300" r="250" fill="{BRASS}" opacity=".05"/>',
        logo("light"),
        pill(M + 2, 157, p["eyebrow"]),
        accent_rule(),
    ]
    head, y = head_block(p["lines"], start=306, base=64)
    body.append(head)
    deck, y = deck_block(p, y + 10)
    body.append(deck)

    panel_top, row_h, gap = max(690, y + 34), 94, 4
    panel_h = 3 * row_h + 2 * gap + 40
    body.append(text(M + 4, panel_top - 20, "WHAT YOU GET", 13, BRASS_LIGHT,
                     weight=700, family=SANS, spacing=2.6))
    body.append(rect(M, panel_top, CONTENT_W, panel_h, "#ffffff", rx=28, opacity=0.06))
    body.append(rect(M, panel_top, CONTENT_W, panel_h, "none", rx=28, stroke=CREAM,
                     stroke_w=1, opacity=0.16))
    col_w = (CONTENT_W - 36) / 2
    for index, (glyph, label, sub_line) in enumerate(p["items"]):
        row, col = divmod(index, 2)
        x = M + 14 + col * (col_w + 8)
        cy = panel_top + 34 + row * (row_h + gap) + row_h / 2 - 10
        tint = "#f5ebd6" if glyph in BRASS_GLYPHS else "#e7f0eb"
        body.append(f'<circle cx="{x + 26}" cy="{cy}" r="19" fill="{tint}"/>')
        body.append(icon(glyph, x + 26, cy))
        body.append(text(x + 58, cy - 2, label, 15.5, CREAM, weight=700,
                         family=SANS, spacing=1))
        body.append(text(x + 58, cy + 20, sub_line, 14, "#c3d2c9",
                         weight=400, family=SANS))

    body.append(cta(M, max(1050, panel_top + panel_h + 22), p["cta"], h=72))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_checklist(p):
    """A dark site photograph above a cream card of what the service delivers."""
    body = [
        dark_backdrop(scene_photo(p)),
        logo("light"),
        pill(M + 2, 157, p["eyebrow"]),
        accent_rule(),
    ]
    head, y = head_block(p["lines"], start=300, base=66)
    body.append(head)
    deck, _ = deck_block(p, y + 10, size=23, max_chars=66, dy=31)
    body.append(deck)

    card_top, card_h = 660, 390
    body.append(rect(M, card_top, CONTENT_W, card_h, "#fffdf8", rx=28))
    body.append(text(M + 44, card_top + 50, p["check_title"], 14, BRASS_DIM,
                     weight=700, family=SANS, spacing=2.4))
    row_y = card_top + 92
    for label, sub_line in p["checks"]:
        body.append(f'<circle cx="{M + 54}" cy="{row_y}" r="17" fill="#eef4ec"/>')
        body.append(icon("check", M + 54, row_y))
        body.append(text(M + 88, row_y - 2, label, 17.5, INK, weight=700, family=SANS))
        body.append(text(M + 88, row_y + 21, sub_line, 14.5, INK_SOFT,
                         weight=400, family=SANS))
        row_y += 60

    body.append(cta(M, 1080, p["cta"], h=72))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


LAYOUTS = {
    "statement": layout_statement,
    "twotone": layout_twotone,
    "quote": layout_quote,
    "stat": layout_stat,
    "gate": layout_gate,
    "ledger": layout_ledger,
    "feature": layout_feature,
    "checklist": layout_checklist,
}


POSTERS = [
    dict(
        slug="you-cant-be-on-site", layout="statement",
        eyebrow="THE DIASPORA BUILD PROBLEM",
        title="You can't be on site. We can.",
        desc="YaVaKa independently manages a Zimbabwe build for a diaspora client: vetting the contractor, approving every payment and resolving differences on site.",
        lines=[("You cannot be on site.", "cream"), ("So we supervise every", "cream"), ("stage of the build.", "brass")],
        sub=["YaVaKa manages your build while your contractor does the work:",
             "vetting the builder, approving every payment or making it ourselves,",
             "and resolving the differences on site."],
        gold="Everything is logged. You watch it live, from anywhere.",
        points=[("shield", "VETTING", "The contractor, checked first"),
                ("wallet", "PAYMENTS", "Approved by us, or paid"),
                ("globe", "LIVE VIEW", "Anywhere, any hour")],
        quote="You relax. We do the supervision.",
        cta="GET A MANAGER ON SITE",
        footer="WE MANAGE. WE BUILD. YOU RELAX.",
    ),
    dict(
        slug="tranche-two-went-quiet", layout="quote",
        eyebrow="THE MONEY PROBLEM",
        title="Tranche two cleared. Then the site went quiet.",
        desc="The common diaspora build failure: funds released without invoices, receipts or evidence of what the money touched.",
        quote_lines=["“Tranche two cleared.", "Then the site", "went quiet.”"],
        last_brass=True,
        attribution="THE MOST EXPENSIVE SILENCE IN CONSTRUCTION",
        sub=["No invoices. No receipts. No way to know what your money touched.",
             "The next tranche should never leave before the last one is evidenced."],
        callout=("No proof. No payment.", "Approved by us, or paid by us"),
        cta="FOLLOW THE MONEY",
        footer="NO PROOF. NO PAYMENT.",
    ),
    dict(
        slug="your-contractor-our-standard", layout="statement",
        eyebrow="HOW WE WORK WITH CONTRACTORS",
        title="Your contractor, held to a documented standard.",
        desc="YaVaKa supervises contractors professionally on behalf of diaspora clients, reviewing work and payments against an agreed standard.",
        lines=[("Your contractor works", "cream"), ("to a written standard,", "cream"), ("or does not work.", "brass")],
        sub=["You choose the builder. We agree the standard, review the work and",
             "check every payment against it. Disagreements get settled on evidence",
             "and in writing, which is better for everybody."],
        gold="Firm on the standard. Fair to everyone on site.",
        points=[("shield", "SELECTION", "Checked before award"),
                ("check", "SUPERVISION", "Reviewed, not assumed"),
                ("chat", "RESOLUTION", "Settled on evidence")],
        quote="Professional management. No shouting required.",
        cta="SET THE STANDARD",
        footer="DESIGN & BUILD · INDEPENDENT MANAGEMENT",
    ),
    dict(
        slug="two-ways-to-build", layout="statement",
        eyebrow="TWO WAYS TO BUILD",
        title="Build with us, or make your builder answer to us.",
        desc="YaVaKa either builds the home for a diaspora client or independently manages the contractor the client chose.",
        lines=[("Build with us, or put", "cream"), ("your own builder under", "cream"), ("our supervision.", "brass")],
        sub=["YaVaKa builds homes for clients abroad, or supervises the contractor",
             "you already chose. Same standard, same ledger, same phone number."],
        gold="Nothing happens off the record. Not even the excuses.",
        points=[("shield", "TWO ROUTES", "Build with us, or managed"),
                ("wallet", "ONE LEDGER", "Approved, paid, logged"),
                ("globe", "ONE VIEW", "Live, from anywhere")],
        quote="Professional management, either way.",
        cta="CHOOSE YOUR ROUTE",
        footer="DESIGN & BUILD · INDEPENDENT MANAGEMENT",
    ),
    dict(
        slug="we-vet-the-builder", layout="twotone",
        eyebrow="BEFORE YOUR MONEY MOVES",
        title="We check who can actually deliver, before your money moves.",
        desc="YaVaKa vets contractors and prices work against a bill of quantities before a diaspora client commits funds.",
        lines=[("We verify the builder", "cream"), ("before your money", "cream"), ("moves.", "brass")],
        sub=["Most builds abroad pick a contractor first and look for proof later.",
             "We do it the other way round. Less exciting, considerably cheaper."],
        answer_head="What vetting actually means",
        answer=[("Work we can see", "Completed builds, reference sites, people who take our call"),
                ("Price against quantities", "A bill of quantities, not a phone estimate"),
                ("Terms in writing", "Programme, retention, penalties and payment gates")],
        cta="START WITH THE VETTING",
        footer="REFERENCES BEFORE CONTRACTS.",
    ),
    dict(
        slug="watch-it-happen-live", layout="statement",
        eyebrow="REAL TIME · FROM ANYWHERE",
        title="You are not waiting for a report. You are watching it happen.",
        desc="Every payment, receipt and stage update on a YaVaKa-managed build is logged live and visible anywhere in the world.",
        lines=[("You are not waiting", "cream"), ("for a report. You are", "cream"), ("watching the build live.", "brass")],
        sub=["Every approval, payment, receipt and stage update is written to the",
             "ledger the moment it happens. Open it from any time zone, any hour."],
        gold="Logged as it happens, not reconstructed from memory a month later.",
        points=[("check", "PAYMENTS", "Approved by us, or paid"),
                ("receipt", "RECEIPTS", "Attached to the cost"),
                ("clock", "TIMESTAMPS", "Dated, never backfilled")],
        quote="No one has to tell you how the build is going.",
        cta="SEE IT LIVE",
        footer="REAL TIME · ANY TIME ZONE",
    ),
    dict(
        slug="diaspora-price", layout="twotone",
        eyebrow="PRICING, WITHOUT THE PREMIUM",
        title="Overseas clients get overseas prices. Not on our projects.",
        desc="Diaspora clients are often overcharged on Zimbabwe builds. YaVaKa prices work from measured quantities and market rates.",
        lines=[("Living abroad should", "cream"), ("not mean paying", "cream"), ("abroad prices.", "brass")],
        sub=["Cement does not cost more because your postcode is London. We price",
             "measured work at market rates, then hold the award to it."],
        answer_head="How the premium comes out",
        answer=[("Quantities first", "Every line priced from measured work, not a round number"),
                ("Market comparison", "At least two credible quotes before an award"),
                ("Written variations", "No verbal extras once the contract is signed")],
        cta="GET THE REAL PRICE",
        footer="WE PRICE THE WORK, NOT THE POSTCODE.",
    ),
    dict(
        slug="the-receipt", layout="quote",
        eyebrow="THE LINE WE HEAR MOST",
        title="I stopped asking for photos of the receipt. I could see it.",
        desc="YaVaKa keeps every receipt attached to the expense and stage it paid for, so the client can open it directly.",
        quote_lines=["“I stopped asking", "for photos of the", "receipt. I could", "see it.”"],
        last_brass=True,
        attribution="EVERY EXPENSE · ITS RECEIPT · ITS STAGE",
        sub=["Not a screenshot in a chat. The document, filed against the cost it",
             "paid for, in the same record as the balance."],
        callout=("Roofing materials · $1,240", "Receipt attached · Superstructure"),
        cta="OPEN THE LEDGER",
        footer="PROOF, NOT PROMISES.",
    ),
    dict(
        slug="nineteen-stages", layout="stat",
        eyebrow="THE ZIMBABWE BUILD SEQUENCE",
        title="Nineteen stages. One missed approval stops all of them.",
        desc="YaVaKa tracks the 19-stage Zimbabwe build sequence and flags statutory gates before they stall the build.",
        stat="19",
        stat_label="STAGES · STAND TO HANDOVER",
        lines=[("One missed approval", "cream"), ("can stop all nineteen", "cream"), ("stages of your build.", "brass")],
        sub=["Title, cession, council plans, EMA,", "ZINWA, ZESA, inspections. We map the",
             "sequence and call each gate early."],
        gold="“Almost done” is not one of the nineteen stages.",
        cta="SEE THE FULL SEQUENCE",
        footer="APPROVALS, MAPPED IN ORDER.",
    ),
    dict(
        slug="dont-use-family", layout="twotone",
        eyebrow="THE HARDEST CONVERSATION",
        title="Don't make family your site manager.",
        desc="Family supervising a diaspora build carry pressure they are not trained for. YaVaKa takes the technical role so relationships stay intact.",
        lines=[("Family can build a", "cream"), ("house, but a professional", "cream"), ("must manage the money.", "brass")],
        sub=["Your uncle means well. He is also not a quantity surveyor.",
             "Supervision is a profession, and it happens to be ours."],
        answer_head="What we take off your family",
        answer=[("The technical calls", "Specifications, tests and measured work, not opinion"),
                ("The difficult conversation", "Raised by us, on evidence, in writing"),
                ("The relationship", "Your family stays family. We stay the professional")],
        cta="KEEP IT PROFESSIONAL",
        footer="FAMILY IS NOT A SUPERVISION PLAN.",
    ),
    dict(
        slug="half-a-house", layout="statement",
        eyebrow="WHERE THE MONEY WENT",
        title="Half a house and a full invoice.",
        desc="YaVaKa never releases payment for work that is not evidenced on site; each release is tied to measured progress.",
        lines=[("Half a house and a", "cream"), ("full invoice is", "cream"), ("not progress.", "brass")],
        sub=["The worst position in construction is paying for work you cannot see,",
             "verify or measure. We do not release money for intention."],
        gold="No proof, no payment. That is the whole rule.",
        points=[("receipt", "MEASURED", "Released against work done"),
                ("lock", "GATED", "Retention held to the end"),
                ("check", "EVIDENCED", "Photo, invoice, approval")],
        quote="We pay for the wall, not the promise of one.",
        cta="PAY FOR PROGRESS ONLY",
        footer="NO PROOF. NO PAYMENT.",
    ),
    dict(
        slug="the-last-ten-percent", layout="twotone",
        eyebrow="WHERE BUILDS STALL",
        title="The last ten percent is where most builds stall.",
        desc="YaVaKa holds retention and closes a snag list before final payment, so handover is not left to goodwill.",
        lines=[("The last ten percent", "cream"), ("is where most", "cream"), ("builds stall.", "brass")],
        sub=["The roof is on, the money is nearly gone, and suddenly the contractor",
             "has another job. Funny how the last 5% takes 40% of the time."],
        answer_head="How we close a build",
        answer=[("Retention held", "A slice of the contract stays in play until the end"),
                ("Snag list closed", "Every defect listed, fixed and signed off"),
                ("Handover file", "Approvals, warranties and receipts handed over together")],
        cta="FINISH IT PROPERLY",
        footer="THE END MATTERS MOST.",
    ),
    dict(
        slug="resolving-differences", layout="quote",
        eyebrow="DELAYS · VARIATIONS · DEFECTS",
        title="Disagreements get expensive when nobody is in the room.",
        desc="YaVaKa resolves delays, variations and defects on site, on evidence and in writing, so clients are not negotiating across time zones.",
        quote_lines=["“Disagreements get", "expensive when nobody", "qualified is in the room.”"],
        last_brass=True,
        attribution="ON SITE · ON EVIDENCE · IN WRITING",
        sub=["Delays and variations are normal on any build. What is not normal is",
             "resolving them by WhatsApp across eight time zones. We meet, decide,",
             "and write it down — a voice note is not a paper trail."],
        cta="RESOLVE IT ON SITE",
        footer="FIRM ON THE STANDARD. FAIR TO EVERYONE.",
    ),
    dict(
        slug="the-site-goes-quiet", layout="statement",
        eyebrow="THE PATTERN NOBODY WARNS YOU ABOUT",
        title="The site goes quiet the day you fly back.",
        desc="Work can slow once a diaspora client leaves the country. YaVaKa keeps site supervision constant and recorded.",
        lines=[("The site goes quiet the", "cream"), ("day you fly back, unless", "cream"), ("somebody is watching it.", "brass")],
        sub=["Two weeks of visible progress while you are in the country. Then the",
             "photos stop, the labour drops, and the excuses begin."],
        gold="Our presence does not depend on your flight schedule.",
        points=[("globe", "PRESENCE", "On site whether you are"),
                ("camera", "EVIDENCE", "Dated photos per stage"),
                ("clock", "RHYTHM", "The programme checked")],
        quote="Progress should not need a boarding pass.",
        cta="KEEP THE SITE MOVING",
        footer="WE DON'T FLY HOME. WE LIVE HERE.",
    ),
    dict(
        slug="we-can-build-it", layout="statement",
        eyebrow="AND YES — WE BUILD TOO",
        title="We would rather you knew we can build it before you sign with someone else.",
        desc="YaVaKa builds homes for diaspora clients as well as managing builds delivered by other contractors.",
        lines=[("We would rather show", "cream"), ("you we can build it", "cream"), ("before you sign elsewhere.", "brass")],
        sub=["YaVaKa builds homes end to end. But our best work is standing beside",
             "you while somebody else does: reviewing, approving, verifying."],
        gold="Choose the contractor. Or choose us. Either way, choose oversight.",
        points=[("shield", "BUILT BY US", "One team, one contract"),
                ("wallet", "MANAGED FOR YOU", "Your contractor, our standard"),
                ("globe", "EITHER WAY", "Same ledger, same view")],
        quote="Two ways to build. One standard of proof.",
        cta="TALK TO US",
        footer="BUILD WITH US · OR MANAGED AGAINST A CONTRACTOR",
    ),
    dict(
        slug="one-phone-number", layout="quote",
        eyebrow="WHAT YOU ARE ACTUALLY BUYING",
        title="One build. One ledger. One phone number that answers.",
        desc="YaVaKa gives diaspora clients a single accountable team, ledger and contact for the whole build.",
        quote_lines=["“One build, one ledger,", "one phone number", "that answers.”"],
        last_brass=True,
        attribution="NOT A GROUP CHAT · NOT A COUSIN · NOT A RUMOUR",
        sub=["The reason builds abroad go wrong is rarely the cement. It is that",
             "nobody owned the whole thing. We do, and we answer the phone."],
        cta="PUT ONE TEAM ON IT",
        footer="ONE TEAM. ONE RECORD.",
    ),
    dict(
        slug="progress-in-your-pocket", layout="statement",
        eyebrow="UPDATES THAT ARRIVE",
        title="Progress lands in your pocket, not in a rumour.",
        desc="YaVaKa sends stage and balance updates by email and WhatsApp as the build manager records them.",
        lines=[("Progress lands in", "cream"), ("your pocket, not in", "cream"), ("somebody's rumour.", "brass")],
        sub=["When your build manager records a stage, a payment or an expense,",
             "the update reaches you by email and WhatsApp. Automatically."],
        gold="No prompting. No chasing. No “I'll send pictures tomorrow”.",
        points=[("chat", "WHATSAPP", "Balance and status"),
                ("receipt", "EMAIL", "The full record, in writing"),
                ("globe", "INSTANT", "Sent as it happens")],
        quote="You should never have to ask how your own house is going.",
        cta="GET THE UPDATES",
        footer="PROGRESS, DELIVERED.",
    ),
    dict(
        slug="keys-and-file", layout="statement",
        eyebrow="THE HANDOVER",
        title="Keys in your hand, and the whole file behind them.",
        desc="YaVaKa hands over the build with approvals, warranties, snag list and receipts together as one record.",
        lines=[("You get the keys,", "cream"), ("and the whole build", "cream"), ("file behind them.", "brass")],
        sub=["Approvals, warranties, snag list, invoices and receipts, handed over",
             "together so the build still makes sense five years later."],
        gold="Most builds end with a handshake and a missing folder. Not this one.",
        points=[("folder", "APPROVALS", "Statutory records filed"),
                ("check", "SNAG LIST", "Closed before final payment"),
                ("receipt", "RECEIPTS", "Every dollar traceable")],
        quote="A house is a building. A file is what protects it.",
        cta="SEE THE HANDOVER FILE",
        footer="KEYS AND PROOF, TOGETHER.",
    ),
    dict(
        slug="verify-quote-record", layout="twotone",
        eyebrow="THREE HABITS THAT PREVENT DISASTER",
        title="Verify the business. Get the quote in writing. Record it against the stage.",
        desc="YaVaKa verifies suppliers, requires written quotes and records every invoice against the build stage it serves.",
        lines=[("Verify the business,", "cream"), ("get the quote in writing", "cream"), ("and record it per stage.", "brass")],
        sub=["Three unglamorous habits separate a finished build from a six-year",
             "argument. We apply all three. Even when it is boring."],
        answer_head="Applied to every supplier",
        answer=[("Verify the business", "Registered, contactable, and able to show delivered work"),
                ("Get a written quote", "Scope, quantity, price and lead time, in writing"),
                ("Record the invoice", "Filed against the exact stage it was bought for")],
        cta="BUILD ON PAPER FIRST",
        footer="VERIFY. QUOTE. RECORD.",
    ),
    dict(
        slug="already-three-months-in", layout="statement",
        eyebrow="ALREADY BUILDING? GOOD.",
        title="Three months in, with a house half up and no record of what the money did.",
        desc="YaVaKa can take over supervision of a build that is already under way, without restarting it or replacing the contractor.",
        lines=[("Three months in and no", "cream"), ("record of the money?", "cream"), ("We can still fix that.", "brass")],
        sub=["You do not have to demolish anything or start again. We take over the",
             "programme, photograph what exists, price what is missing and supervise",
             "from where the site actually stands today."],
        gold="A build that is already running can still be brought under control.",
        points=[("camera", "SNAPSHOT", "Recorded as it stands"),
                ("check", "GAP CHECK", "What is done, what is not"),
                ("shield", "CONTROL", "From that point forward")],
        quote="Late is not the same as lost.",
        cta="BRING IN OVERSIGHT",
        footer="START FROM WHERE YOU ARE.",
    ),
    dict(
        slug="no-need-to-sack-anybody", layout="statement",
        eyebrow="MID-BUILD RECOVERY",
        title="Take control of the site without sacking a single worker.",
        desc="YaVaKa supervises the contractor already on site rather than demanding a change of builder, so relationships and progress survive.",
        lines=[("Take control of the site", "cream"), ("without sacking a", "cream"), ("single worker.", "brass")],
        sub=["Changing contractors mid-build costs time, money and the goodwill of",
             "everyone on site. Supervising the one you already have costs a",
             "conversation - and it is usually the cheaper repair."],
        gold="We manage the builder you hired. We do not ask you to start over.",
        points=[("chat", "SAME CREW", "No wholesale change"),
                ("clock", "NO RESTART", "The programme continues"),
                ("wallet", "NEW RULES", "Evidence before payment")],
        quote="You do not need a new contractor. You need a standard.",
        cta="SUPERVISE WHAT EXISTS",
        footer="KEEP THE CREW. CHANGE THE RULES.",
    ),
    dict(
        slug="cannot-audit-what-nobody-recorded", layout="quote",
        eyebrow="FOR BUILDS ALREADY RUNNING",
        title="You cannot audit what nobody recorded.",
        desc="Most mid-build disputes fail for want of a record: no dated photos, no invoices against stages, no approvals in writing.",
        quote_lines=["“You cannot audit", "what nobody recorded.”"],
        last_brass=True,
        attribution="WHY MID-BUILD ARGUMENTS CANNOT BE WON",
        sub=["If the last eight months exist only as phone calls and partial photos,",
             "there is nothing to measure. From today, everything is dated,",
             "attached to a stage and kept."],
        callout=("Start the record today", "Yesterday is gone. Today is evidence"),
        cta="START THE RECORD",
        footer="EVIDENCE FROM HERE FORWARD.",
    ),
    dict(
        slug="every-project-one-screen", layout="statement",
        eyebrow="FOR BUILD MANAGERS",
        title="Every project you run, on one screen, held to one standard.",
        desc="YaVaKa gives a build manager a portfolio view: stages, budgets, receipts, approvals and client updates across every project at once.",
        lines=[("Every project you run", "cream"), ("sits on one screen,", "cream"), ("held to one standard.", "brass")],
        sub=["No spreadsheets by night. No WhatsApp archaeology. Stage status,",
             "balances, missing receipts and approvals for the whole portfolio,",
             "in one place and already written up."],
        gold="Run ten builds with the discipline you give your best one.",
        points=[("folder", "PORTFOLIO", "All projects, one view"),
                ("receipt", "RECEIPTS", "Missing proof, flagged"),
                ("chat", "UPDATES", "Clients informed for you")],
        quote="Management is easier when the record keeps itself.",
        cta="RUN YOUR PORTFOLIO",
        footer="MANAGE MORE. CHASE LESS.",
    ),
    dict(
        slug="the-paperwork-does-itself", layout="twotone",
        eyebrow="WHAT MANAGERS STOP DOING",
        title="The paperwork does itself. You do the building.",
        desc="YaVaKa removes the administrative weight of build management: stage tracking, receipts, client updates and reporting are generated from the work you record.",
        lines=[("The paperwork does", "cream"), ("itself, so you can get", "cream"), ("on with the building.", "brass")],
        sub=["Three things managers lose hours to every week. All three are produced",
             "by the system the moment the stage or the payment is recorded."],
        answer_head="Automated for you",
        answer=[("Client updates", "Stage and balance changes sent by email and WhatsApp"),
                ("Progress reports", "Portfolio and project packs, ready to hand over"),
                ("Receipt trails", "Every payment tied to the document that proves it")],
        cta="SEE THE MANAGER VIEW",
        footer="LESS ADMIN. MORE SITE.",
    ),
    dict(
        slug="win-clients-on-evidence", layout="statement",
        eyebrow="FOR BUILD MANAGERS",
        title="Win the next client on evidence, not on promises.",
        desc="A YaVaKa record gives a build manager something most contractors cannot show: dated progress, approved payments and a complete handover file.",
        lines=[("Win the next client", "cream"), ("with evidence, not", "cream"), ("with promises.", "brass")],
        sub=["Every completed project leaves behind a record: stages signed off,",
             "receipts filed, updates sent, handover documented. That record is",
             "what wins the next diaspora client."],
        gold="Your best reference is a file, not a photograph.",
        points=[("folder", "A REAL RECORD", "Proof per project"),
                ("shield", "CREDIBILITY", "Independent standard"),
                ("globe", "REMOTE CLIENTS", "Confidence from abroad")],
        quote="Show the file. Win the work.",
        cta="BUILD YOUR TRACK RECORD",
        footer="EVIDENCE WINS WORK.",
    ),
    dict(
        slug="built-for-the-distance", layout="statement",
        eyebrow="WHY YAVAKA EXISTS",
        title="Zimbabwe is full of good builders and unfinished houses. The gap is oversight.",
        desc="YaVaKa is an independent build management company for Zimbabweans abroad, created to make distance irrelevant to the quality of a build.",
        lines=[("Zimbabwe has good builders", "cream"), ("and unfinished houses.", "cream"), ("The gap is oversight.", "brass")],
        sub=["Almost every diaspora build stalls the same way: the money is real,",
             "the intentions are good, and nobody with authority is standing on",
             "the site. YaVaKa exists to be that person, in writing."],
        gold="Our distance, for once, is the advantage: we answer to you, not the site.",
        points=[("globe", "DIASPORA FIRST", "Designed around distance"),
                ("shield", "INDEPENDENT", "No contractor loyalty"),
                ("lock", "ACCOUNTABLE", "Named, recorded, answerable")],
        quote="A trust problem needs a record, not a promise.",
        cta="START YOUR BUILD FILE",
        footer="BUILD FROM ANYWHERE.",
    ),
    dict(
        slug="the-second-opinion", layout="statement",
        eyebrow="FOR A BUILD ALREADY UNDER WAY",
        title="A second opinion costs far less than a second slab.",
        desc="YaVaKa reviews a build in progress and reports what is sound, what is missing and what should not be paid for next.",
        lines=[("A second opinion costs", "cream"), ("far less than a", "cream"), ("second slab.", "brass")],
        sub=["Bring us in for a review of the work so far. We check what stands,",
             "what was specified, what was paid and what the next payment should",
             "actually release. Then you decide."],
        gold="You do not have to hand over the whole build to get the truth about it.",
        points=[("check", "REVIEW", "Work checked as found"),
                ("receipt", "PAPERWORK", "Paid against what"),
                ("shield", "ADVICE", "What to release next")],
        quote="Ask before the next tranche, not after.",
        cta="BOOK A REVIEW",
        footer="A SECOND OPINION, IN WRITING.",
    ),
    dict(
        slug="four-payments-ahead", layout="quote",
        eyebrow="THE MID-BUILD TRAP",
        title="You are four payments ahead of the paperwork.",
        desc="On a build already running, money often moves faster than evidence. The gap is where disputes live.",
        quote_lines=["“You are four payments", "ahead of the paperwork,", "and that is how", "builds get lost.”"],
        last_brass=True,
        attribution="HOW A RUNNING BUILD STARTS TO SLIP",
        sub=["It rarely starts with a fraud. It starts with trust, speed and a",
             "receipt promised for next week. Six weeks later nobody can",
             "reconstruct what was paid for what."],
        callout=("Stop the drift", "Evidence before the next release"),
        cta="CLOSE THE GAP",
        footer="EVIDENCE BEFORE THE NEXT RELEASE.",
    ),
    dict(
        slug="run-more-builds", layout="statement",
        eyebrow="FOR BUILD MANAGERS",
        title="Run more builds without giving up your evenings.",
        desc="YaVaKa removes the evening admin of build management: stage records, receipt trails, client updates and reports are produced from the work you already do.",
        lines=[("Run more builds without", "cream"), ("giving up your", "cream"), ("evenings.", "brass")],
        sub=["The reason a manager caps out at a handful of projects is rarely the",
             "building. It is the reporting, the chasing and the explaining. That",
             "part can be carried by the system."],
        gold="Your time should go to the site, not to the spreadsheet.",
        points=[("folder", "ONE VIEW", "Whole portfolio, not tabs"),
                ("chat", "CLIENTS TOLD", "Updates sent automatically"),
                ("clock", "HOURS BACK", "Admin done as you record")],
        quote="Manage more. Chase less.",
        cta="SEE THE MANAGER VIEW",
        footer="MORE PROJECTS. LESS ADMIN.",
    ),
    dict(
        slug="who-we-are", layout="twotone",
        eyebrow="THE COMPANY",
        title="A Zimbabwean company built for Zimbabweans abroad.",
        desc="YaVaKa is an independent build management and delivery company: we supervise, we record, and where the client prefers, we build.",
        lines=[("We are a Zimbabwean", "cream"), ("company built for", "cream"), ("Zimbabweans abroad.", "brass")],
        sub=["We are not an app pretending to be a builder, and not a builder",
             "pretending to be independent. The record and the site are the",
             "same business, which is why the record can be trusted."],
        answer_head="What we stand on",
        answer=[("Independence", "Paid by the client, never by the contractor"),
                ("Evidence", "Every stage and payment carries proof"),
                ("Presence", "People on the ground, all year")],
        cta="WORK WITH US",
        footer="INDEPENDENT BUILD MANAGEMENT.",
    ),

    dict(slug="the-first-question", layout="statement", panel="right",
         eyebrow="BEFORE YOU PAY ANYONE",
         title="Ask what happens when the money is finished and the work is not.",
         desc="YaVaKa defines the finish line before the first payment, so a build cannot quietly outrun its budget.",
         lines=[("Ask what happens when", "cream"), ("the money is finished", "cream"), ("and the work is not.", "brass")],
         sub=["Every build abroad starts hopeful. The ones that finish ask, in writing,",
              "what the final number buys, and what happens if it does not."],
         gold="A finish line agreed in advance is the cheapest insurance there is.",
         points=[("check", "SCOPE", "Written before money"),
                 ("wallet", "CAP", "The number agreed"),
                 ("shield", "RECOURSE", "If it is missed")],
         quote="Agree the finish line before the first brick.",
         cta="AGREE THE SCOPE", footer="SCOPE FIRST. MONEY SECOND."),
    dict(slug="nobody-on-site", layout="quote",
         eyebrow="THE QUIET FAILURE",
         title="Nobody is on site. Everybody is on the group chat.",
         desc="A build without someone accountable on the ground becomes a conversation rather than a project.",
         quote_lines=["“Nobody is on site,", "but everybody is", "on the group chat.”"],
         last_brass=True, attribution="HOW A BUILD BECOMES A DISCUSSION",
         sub=["Opinions travel faster than work. Without a person who checks,",
              "decides and records, the group chat becomes the site office."],
         callout=("Put one person on it", "Accountable, named, on the ground"),
         cta="PUT SOMEONE ON SITE", footer="A WITNESS BEATS A WITNESS CHAT."),
    dict(slug="cash-with-no-paper", layout="statement", panel="left",
         eyebrow="THE RECEIPT RULE",
         title="If it left your account and left no paper, it did not happen.",
         desc="YaVaKa treats a payment without a receipt or approved stage as an open question, not a settled cost.",
         lines=[("If it left your account", "cream"), ("and left no paper, it", "cream"), ("did not happen.", "brass")],
         sub=["Receipts are not bureaucracy. They are the only reason a build can be",
              "reconstructed years later, by people who were not there."],
         gold="Every dollar should point at something it bought.",
         points=[("receipt", "PROOF", "Receipt or approved stage"),
                 ("wallet", "RELEASE", "Held until evidenced"),
                 ("folder", "RECORD", "Kept for handover")],
         quote="No proof, no payment. No exceptions.",
         cta="SET THE RULE", footer="NO PROOF. NO PAYMENT."),
    dict(slug="the-quote-that-grew", layout="quote",
         eyebrow="HOW BUDGETS DIE",
         title="The quote was fair. The variations were not the quote.",
         desc="Most budget overruns arrive as small, reasonable variations rather than one large increase.",
         quote_lines=["“The quote was fair.", "The variations were", "never in the quote.”"],
         last_brass=True, attribution="THE SLOWEST WAY TO LOSE A BUDGET",
         sub=["Each change looks sensible on its own. Together they can add a third",
              "to the cost, and nobody agreed to a third."],
         callout=("Every variation in writing", "Priced, approved, recorded"),
         cta="CONTROL VARIATIONS", footer="CHANGE ORDERS, OR NOTHING."),
    dict(slug="three-contractors-one-standard", layout="statement", panel="left",
         eyebrow="MULTIPLE TRADES",
         title="Five trades, five standards, one site. Somebody has to hold the line.",
         desc="YaVaKa coordinates separate trades against one specification so quality does not depend on who arrived first.",
         lines=[("Five trades, five", "cream"), ("standards, one site:", "cream"), ("somebody holds the line.", "brass")],
         sub=["Plumbers, electricians and builders each work to their own habits.",
              "The standard has to belong to the client, not to the loudest trade."],
         gold="Someone has to hold the line while you are nine thousand kilometres away.",
         points=[("shield", "SPEC", "One written standard"),
                 ("check", "REVIEW", "Each trade checked"),
                 ("chat", "ESCALATION", "Disputes settled on evidence")],
         quote="Standards do not hold themselves.",
         cta="HOLD THE STANDARD", footer="ONE SITE. ONE STANDARD."),
    dict(slug="the-family-argument", layout="quote",
         eyebrow="THE HARDEST PART",
         title="The build is fine. It is the family argument about it that is expensive.",
         desc="Shared ownership and unclear records turn construction into a family dispute. A single written record prevents most of it.",
         quote_lines=["“The build is fine.", "It is the argument", "about it that costs you.”"],
         last_brass=True, attribution="WHY RECORDS MATTER MORE THAN OPINIONS",
         sub=["When several people fund a build, memory becomes evidence. A record",
              "everyone can read ends the argument before it starts."],
         callout=("One record, many readers", "Owners, family and contractor"),
         cta="SHARE THE RECORD", footer="ONE RECORD. FEWER ARGUMENTS."),
    dict(slug="the-photo-that-proves-nothing", layout="statement", panel="right",
         eyebrow="EVIDENCE, NOT IMPRESSIONS",
         title="A photo proves a wall exists. It does not prove the wall is right.",
         desc="Progress photos are useful, but they do not show specification, quantity, approval or cost.",
         lines=[("A photo proves a wall", "cream"), ("exists, not that the wall", "cream"), ("was built correctly.", "brass")],
         sub=["Pictures are the easiest thing to send and the weakest thing to rely on.",
              "Stage approval, measurement and receipts are what actually settle questions."],
         gold="Pictures reassure. Records decide.",
         points=[("camera", "PHOTOS", "Dated, per stage"),
                 ("check", "APPROVAL", "Signed stage gates"),
                 ("receipt", "COST", "Receipt per payment")],
         quote="Reassurance is not evidence.",
         cta="ASK FOR RECORDS", footer="RECORDS DECIDE."),
    dict(slug="the-stage-nobody-signed", layout="statement", panel="left",
         eyebrow="STAGE GATES",
         title="The stage nobody signed off is the stage everybody argues about.",
         desc="YaVaKa requires an explicit approval per stage before the next one is funded.",
         lines=[("The stage nobody signed", "cream"), ("off is the one everybody", "cream"), ("argues about.", "brass")],
         sub=["Nineteen stages, each with an authority, a budget and a decision.",
              "Funding a stage that was never approved is how budgets unravel."],
         gold="Approval is a gate, not a courtesy.",
         points=[("check", "GATE", "Approved to proceed"),
                 ("wallet", "FUND", "Released per stage"),
                 ("clock", "ORDER", "One at a time")],
         quote="Gates only work when they are closed.",
         cta="SEE THE STAGES", footer="NINETEEN STAGES. NINETEEN GATES."),
    dict(slug="one-tranche-too-far", layout="quote",
         eyebrow="THE LAST TRANCHE",
         title="The last tranche is always the one with no leverage left.",
         desc="Cash sent before completion removes the client's only remaining incentive. Staged release protects both sides.",
         quote_lines=["“The last tranche is", "the one where you have", "no leverage left.”"],
         last_brass=True, attribution="WHY RELEASE SCHEDULES MATTER",
         sub=["Pay the whole balance and the finishing touches become a favour.",
              "Hold a defined retention and they remain an obligation."],
         callout=("Retention, agreed up front", "Protects the snag list"),
         cta="AGREE RETENTION", footer="KEEP THE LAST GATE CLOSED."),
    dict(slug="distance-is-not-permission", layout="statement", panel="left",
         eyebrow="FOR THOSE ABROAD",
         title="Distance is not permission for anyone to spend your money quietly.",
         desc="Being far away should never mean being uninformed. YaVaKa keeps the record visible from anywhere.",
         lines=[("Distance is not permission", "cream"), ("for anyone to spend your", "cream"), ("money quietly.", "brass")],
         sub=["You are allowed to ask for the invoice. You are allowed to ask what a",
              "payment bought. A good build team expects the question."],
         gold="You should never feel rude for asking where the money went.",
         points=[("globe", "REMOTE", "Full visibility"),
                 ("receipt", "TRACE", "Payment to proof"),
                 ("chat", "REACH", "Updates that arrive")],
         quote="Being far away is not the same as being uninformed.",
         cta="SEE EVERYTHING", footer="DISTANCE IS NOT PERMISSION."),
    dict(slug="whose-gate-is-this", layout="gate", rail="v",
         eyebrow="COUNCIL & STATUTORY GATES",
         title="Nobody can name the gate their build is waiting on.",
         desc="YaVaKa maps the 19-stage Zimbabwe build sequence and names each statutory gate, its authority and what it blocks.",
         lines=[("Nobody can name the gate", "cream"), ("their build is waiting on,", "cream"), ("so nobody chases it.", "brass")],
         sub=["Council plans, cession, EMA, ZINWA, ZESA, inspections.",
              "Each one has an authority, a document and a stage it holds up."],
         gates=["Title", "Council", "Footings", "Walling", "Roof", "Handover"],
         current=2, quote="If nobody can name it, nobody can chase it.",
         gate_title="COUNCIL PLANS",
         gate_body="Blocks superstructure. Chased, not waited on.",
         cta="NAME EVERY GATE", footer="GATES MAPPED IN ORDER."),
    dict(slug="stage-gate-discipline", layout="gate", rail="h",
         eyebrow="FOR THE MANAGER ON THE GROUND",
         title="A stage is not finished because it looks finished.",
         desc="Each stage closes only when its check, its certificate and its cost are all recorded against it.",
         lines=[("A stage is not finished", "cream"), ("because it looks", "cream"), ("finished.", "brass")],
         sub=["Looking done and being signed off are two different events.",
              "Close one stage at a time and the snag list stops growing."],
         gates=["Set out", "Found", "Slab", "Walls", "Ring beam", "Roof"],
         current=3, quote="The site stops arguing once the stages are closed.",
         gate_title="WALLING APPROVED",
         gate_body="Measured, checked and costed before ring beam.",
         cta="CLOSE THE STAGE", footer="ONE STAGE. ONE SIGNATURE."),
    dict(slug="funding-not-feelings", layout="gate", rail="v",
         eyebrow="MONEY AGAINST STAGES",
         title="Money should follow a gate, not a feeling.",
         desc="YaVaKa ties each release of funds to a stage that has actually been approved on site.",
         lines=[("Money should follow", "cream"), ("a stage gate, not", "cream"), ("a feeling.", "brass")],
         sub=["\"Almost there\" is not a milestone. A signed stage is.",
              "Each deposit lands against the stage it is paying for."],
         gates=["Deposit", "Substructure", "Superstructure", "Roof", "Finishes", "Snag"],
         current=2, quote="Funded stages finish. Unfunded intentions drift.",
         gate_title="SUPERSTRUCTURE FUNDED",
         gate_body="Balance moves only when the gate opens.",
         cta="FUND THE STAGE", footer="MONEY FOLLOWS PROGRESS."),
    dict(slug="first-day-on-site", layout="gate", rail="h",
         eyebrow="STARTING TOMORROW",
         title="Most builds go wrong before the first brick is laid.",
         desc="Budget, programme, approvals and a signed scope are all set before work starts on a YaVaKa-managed build.",
         lines=[("Most builds go wrong", "cream"), ("before the first brick", "cream"), ("is laid.", "brass")],
         sub=["Scope, price, programme and approvals all exist up front.",
              "Changing them afterwards is where the money disappears."],
         gates=["Scope", "Price", "Approvals", "Mobilise", "Found", "Build"],
         current=1, quote="Set it up properly once and the rest is just sequencing.",
         gate_title="PRICE AGAINST QUANTITIES",
         gate_body="Measured work, market rates, nothing rounded.",
         cta="SET IT UP RIGHT", footer="DECIDED BEFORE DAY ONE."),
    dict(slug="the-quiet-variation", layout="gate", rail="v",
         eyebrow="VARIATIONS",
         title="The expensive change is the one nobody wrote down.",
         desc="Every variation on a YaVaKa build is written, priced and approved before the work happens.",
         lines=[("The expensive change", "cream"), ("is the one nobody", "cream"), ("wrote down.", "brass")],
         sub=["A variation on a phone call is a favour, and favours have no cap.",
              "Written and priced first, then built, then paid."],
         gates=["Request", "Measure", "Price", "Approve", "Build", "Settle"],
         current=3, quote="A change you did not price is a price you did not choose.",
         gate_title="WRITTEN AND APPROVED",
         gate_body="Priced before it is built, not after.",
         cta="PRICE EVERY CHANGE", footer="NOTHING CHANGES FOR FREE."),
    dict(slug="nobody-chases-for-you", layout="gate", rail="h",
         eyebrow="CHASING, DONE FOR YOU",
         title="Chasing is the job. You should not be the one doing it.",
         desc="YaVaKa tracks each gate, chases the responsible party and records the outcome on the project.",
         lines=[("Chasing is the job,", "cream"), ("and you should not be", "cream"), ("the one doing it.", "brass")],
         sub=["A stalled gate is a full-time job: calls, letters, offices, queues.",
              "That is what a build manager on the ground is for."],
         gates=["Identify", "Submit", "Chase", "Inspect", "Approve", "Next"],
         current=2, quote="Distance makes chasing impossible. That is the point of us.",
         gate_title="SUBMITTED, THEN FOLLOWED UP",
         gate_body="Every submission has an owner and a date.",
         cta="HAND OVER THE CHASING", footer="CHASING IS THE JOB."),

    dict(slug="what-the-money-bought", layout="ledger",
         eyebrow="THE LEDGER, IN ONE SLIP",
         title="A balance tells you nothing. The lines tell you everything.",
         desc="YaVaKa shows every deposit, every payment, and the receipt that sits against each one.",
         lines=[("A balance tells you nothing.", "cream"), ("The lines tell you everything.", "brass")],
         slip_head="BUILD LEDGER",
         slip_sub="Greendale Family Home · YVK-0001",
         entries=[("Deposits received", "$18,400", "wallet"),
                  ("Superstructure paid", "$7,120", "check"),
                  ("Roofing materials", "$1,240", "receipt"),
                  ("Retention held", "$900", "lock")],
         total_label="AVAILABLE BALANCE", total_value="$9,140",
         cta="OPEN THE LEDGER", footer="LINES, NOT A BALANCE."),
    dict(slug="the-receipt-is-the-argument", layout="ledger",
         eyebrow="PROOF FILED, NOT PROMISED",
         title="You should not have to ask for a photograph of a receipt.",
         desc="Every expense can carry its receipt, filed against the stage and the cost it paid for.",
         lines=[("You should never have to ask", "cream"), ("for a photograph of a receipt.", "brass")],
         slip_head="EXPENSE · ROOFING STAGE",
         slip_sub="Filed against the build, not the camera roll",
         entries=[("IBR sheets", "$640", "receipt"),
                  ("Purloins", "$310", "receipt"),
                  ("Labour, 4 days", "$220", "clock"),
                  ("Transport", "$70", "wallet")],
         total_label="RECEIPTED TOTAL", total_value="$1,240",
         cta="SEE THE RECEIPTS", footer="PROOF IS ATTACHED."),
    dict(slug="the-money-that-vanished", layout="ledger",
         eyebrow="WHERE THE BALANCE GOES",
         title="\"The money is finished\" is not an explanation.",
         desc="A running ledger shows exactly which stages consumed which funds, and what remains for the next gate.",
         lines=[("“The money is finished” is not", "cream"), ("an explanation of where it went.", "brass")],
         slip_head="FUNDING vs SPEND",
         slip_sub="Sent from the UK · three tranches",
         entries=[("Tranche 1 · deposit", "$9,000", "wallet"),
                  ("Tranche 2 · structure", "$6,000", "wallet"),
                  ("Tranche 3 · roofing", "$4,000", "wallet"),
                  ("Spent to date", "$15,910", "receipt")],
         total_label="LEFT FOR FINISHES", total_value="$3,090",
         cta="TRACE EVERY DOLLAR", footer="MONEY THAT CAN BE TRACED."),
    dict(slug="why-the-quote-was-low", layout="ledger",
         eyebrow="THE QUOTE, LINE BY LINE",
         title="The low quote was never low. It was incomplete.",
         desc="Pricing against a bill of quantities shows what a quote left out before the work begins.",
         lines=[("The low quote was never low.", "cream"), ("It was incomplete.", "brass")],
         slip_head="BILL OF QUANTITIES",
         slip_sub="Priced from measured work",
         entries=[("Excavation", "included", "check"),
                  ("Concrete, footings", "included", "check"),
                  ("Council fees", "not included", "clock"),
                  ("Sewer connection", "not included", "clock")],
         total_label="REAL COST vs THE QUOTE", total_value="+18%",
         cta="SEE THE FULL BILL", footer="PRICE THE WORK, NOT A NUMBER."),

    # ------------------------------------------------ rental management
    dict(slug="rental-management", layout="feature",
         eyebrow="PROPERTY MANAGEMENT",
         title="The build is finished. The building still has to earn.",
         desc="Rental management inside the property door: rent invoices, numbered receipts, arrears, tenant statements, leases, deposits and portfolio reports.",
         lines=[("When the build ends,", "cream"), ("rental management", "cream"), ("begins.", "brass")],
         sub=["Rental management is built into the property door:",
              "the lease, the invoice, the receipt and the report in one place."],
         items=[("wallet", "RENT INVOICES", "Monthly, per signed lease"),
                ("receipt", "RENT RECEIPTS", "Numbered and filed"),
                ("clock", "ARREARS", "Who owes, and how long"),
                ("folder", "STATEMENTS", "Billed, paid, balanced"),
                ("shield", "DEPOSITS", "In, held, refunded"),
                ("globe", "REPORTS", "Rent roll and yield")],
         quote="A building is not passive income if nobody keeps the record.",
         cta="OPEN THE PROPERTY DOOR", footer="BUILD IT. THEN LET IT EARN."),
    dict(slug="rent-invoices", layout="statement",
         eyebrow="RENT, WITHOUT THE NOTEBOOK",
         title="Every signed lease. Every month. One invoice run.",
         desc="Raise rent invoices for one lease or the whole portfolio, with water, levy and recharge invoices beside them and no double-billing.",
         lines=[("Every signed lease gets", "cream"), ("an invoice every month,", "cream"), ("in one run.", "brass")],
         sub=["Raise this month's rent across the portfolio, or for one lease.",
              "Water, levy and recharge invoices sit beside it.",
              "The same month cannot be billed twice."],
         gold="A lease that is not signed cannot be invoiced.",
         points=[("wallet", "ONE RUN", "Portfolio-wide rent"),
                 ("receipt", "NUMBERED", "INV-YYYY-NNNN"),
                 ("clock", "ON TIME", "Raised, not remembered")],
         quote="The rent run should not depend on somebody remembering the first.",
         cta="SEE RENT INVOICING", footer="ONE LEASE. ONE INVOICE. ONE MONTH."),
    dict(slug="rent-receipts", layout="ledger",
         eyebrow="PROPERTY MANAGEMENT",
         title="Every rent payment gets a numbered receipt.",
         desc="Rent receipts settle or part-pay an invoice, are numbered per year, and can be reversed if they were recorded in error.",
         lines=[("Every rent payment gets a", "cream"), ("numbered receipt on the spot.", "brass")],
         slip_head="RENT RECEIPT", slip_sub="RCPT-YYYY-NNNN",
         entries=[("Rent, March", "paid", "check"),
                  ("Water recharge", "paid", "check"),
                  ("Levy", "part paid", "clock"),
                  ("Deposit", "held", "lock")],
         total_label="RECEIVED TO DATE", total_value="US$1,240",
         quote="A tenant and an owner should never disagree about what was paid.",
         cta="RECEIPT RENT PROPERLY", footer="EVERY PAYMENT. A NUMBER."),
    dict(slug="arrears-ageing", layout="stat",
         eyebrow="PROPERTY MANAGEMENT",
         title="Know who owes, how much, and for how long.",
         desc="Arrears ageing by tenant and by invoice, so the owner sees the balance and the age of every unpaid rent before it becomes a crisis.",
         stat="30", stat_label="DAYS LATE \u00b7 SEEN AT A GLANCE",
         lines=[("See who owes, how much,", "cream"), ("and exactly how long", "cream"), ("it is overdue.", "brass")],
         sub=["Arrears are aged by tenant and invoice, not hidden in a",
              "reconstructed spreadsheet. Remind one tenant, or every",
              "overdue invoice at once."],
         gold="The rent roll and the arrears live on the same screen.",
         cta="SEE THE ARREARS", footer="WHO. HOW MUCH. HOW LONG."),
    dict(slug="tenant-statements", layout="quote",
         eyebrow="PROPERTY MANAGEMENT",
         title="A statement that settles the argument.",
         desc="Hand a tenant the full history of invoices, payments and balance, generated from the same ledger the owner can read.",
         quote_lines=["“Everything the tenant", "was billed, everything", "they paid, and one", "clear balance.”"],
         attribution="TENANT STATEMENTS, FROM THE LEDGER",
         sub=["No reconstructed spreadsheet, no argument about memory.",
              "The statement is attached to the tenant and visible to the owner."],
         callout=("Billed and paid in one view", "Available on every tenant"),
         last_brass=True,
         cta="SEE A TENANT STATEMENT", footer="BILLED. PAID. BALANCED."),
    dict(slug="lease-signing", layout="statement",
         eyebrow="LEASES & DEPOSITS",
         title="A lease produced, signed on screen, and kept.",
         desc="Produce a lease from the property and tenant records, sign it on screen, renew it at term and track the deposit through to refund.",
         lines=[("Sign the lease on your", "cream"), ("phone; the signed terms", "cream"), ("stay in the property file.", "brass")],
         sub=["The lease is built from the property and tenant records.",
              "Sign it on screen, renew it at term, track the deposit.",
              "The terms are frozen at the moment of signature."],
         gold="A lease nobody can find is a lease nobody can enforce.",
         points=[("check", "SIGNED", "On screen, in minutes"),
                 ("folder", "STORED", "The signed terms, kept"),
                 ("shield", "DEPOSIT", "In, held, refunded")],
         quote="The terms should not change after the ink is dry.",
         cta="LEASE A PROPERTY", footer="SIGNED. STORED. ENFORCEABLE."),
    dict(slug="inspections", layout="checklist",
         eyebrow="PROPERTY INSPECTIONS",
         title="Somebody walks the property. You get the proof.",
         desc="Periodic property checks with written findings, photos and video, kept on the property and delivered to the owner on the system, by email and over WhatsApp.",
         lines=[("We attend the property,", "cream"), ("photograph every defect", "cream"), ("and send you the report.", "brass")],
         sub=["Periodic checks with findings, photos and video -",
              "kept on the property and sent to the owner."],
         check_title="WHAT A CHECK DELIVERS",
         checks=[("Findings, written down", "Condition, defects and what needs doing"),
                 ("Photos and video", "Filed against the property, not a chat"),
                 ("Delivered to the owner", "On the system, by email and WhatsApp"),
                 ("The next check scheduled", "Cadence set by the check type"),
                 ("YaVaKa can attend", "Booked on site when you cannot be")],
         quote="You cannot inspect a building from another country.",
         cta="BOOK A PROPERTY CHECK", footer="ATTEND. RECORD. SEND."),
    dict(slug="work-orders", layout="feature",
         eyebrow="REPAIRS & WORK ORDERS",
         title="Log the repair. Book the contractor. Close it into the cost.",
         desc="A work order carries a repair from the report to the receipt; closing it with a cost writes the matching expense once.",
         lines=[("Log the repair, book the", "cream"), ("contractor and close it", "cream"), ("into the cost.", "brass")],
         sub=["A repair should have a work order, a contractor and a cost.",
              "Closing the order writes the expense - not a second version of it."],
         items=[("chat", "LOGGED", "The repair, in writing"),
                ("shield", "BOOKED", "A contractor on the job"),
                ("check", "CLOSED", "The work signed off"),
                ("receipt", "COSTED", "The expense, once"),
                ("clock", "TRACKED", "Open items in view"),
                ("folder", "FILED", "Against the property")],
         quote="A repair with no work order is a rumour with a price.",
         cta="SEE WORK ORDERS", footer="REPAIR. RECORD. RECEIPT."),
    dict(slug="property-reports", layout="stat",
         eyebrow="PROPERTY REPORTS",
         title="Arrears, rent roll, net income and yield. One report.",
         desc="A portfolio report with collected rent, outstanding arrears, costs, net income and yield, exportable as CSV for the accountant.",
         stat="1", stat_label="REPORT FOR THE WHOLE PORTFOLIO",
         lines=[("See the rent roll, arrears,", "cream"), ("costs and yield behind", "cream"), ("every building.", "brass")],
         sub=["Collected against outstanding, costs against net income,",
              "with a CSV export for the accountant and the owner."],
         gold="You cannot price a building on a feeling.",
         cta="SEE PORTFOLIO REPORTS", footer="READ THE PORTFOLIO."),
    dict(slug="two-doors", layout="statement",
         eyebrow="PROJECT + PROPERTY",
         title="One company. Two doors. The build, then the building.",
         desc="Project Management manages the work; Property Management manages the asset afterwards. The same record keeps going after handover.",
         lines=[("We manage the build, then", "cream"), ("we manage the building", "cream"), ("when it starts earning.", "brass")],
         sub=["Project Management runs the work; Property Management runs",
              "the asset afterwards. One company, one record, one standard",
              "from the first stage to next month's rent."],
         gold="The handover should not be the end of the record.",
         points=[("shield", "BUILD", "Stages, money, proof"),
                 ("wallet", "RENT", "Invoices, receipts, arrears"),
                 ("camera", "CHECKS", "Photos, video, findings")],
         quote="The building does not stop needing management at handover.",
         cta="OPEN THE RIGHT DOOR", footer="TWO DOORS. ONE RECORD."),

    # ------------------------------------------------ the rest of the system
    dict(slug="project-kinds", layout="feature",
         eyebrow="WHAT WE MANAGE",
         title="Not every project is a house from scratch.",
         desc="Full builds, renovations, extensions, kitchens, bathrooms, roofing, solar, boreholes and walls - each with its own stage plan.",
         lines=[("From a new roof to a", "cream"), ("borehole, every project", "cream"), ("has its own stage plan.", "brass")],
         sub=["Pick the kind and the stage plan changes with it -",
              "a kitchen fit-out no longer starts with land due diligence."],
         items=[("folder", "FULL BUILDS", "Land to handover"),
                ("check", "RENOVATIONS", "Old building, new record"),
                ("wallet", "KITCHENS", "Cabinets and fit-out"),
                ("shield", "BATHROOMS", "Tiling to fixtures"),
                ("globe", "SOLAR & WATER", "Boreholes, backup power"),
                ("camera", "WALLS & GATES", "Landscaping, finishes")],
         quote="The plan should match the job, not the other way round.",
         cta="START WITH THE KIND", footer="EVERY KIND. ONE STANDARD."),
    dict(slug="kitchen-fitout", layout="quote",
         eyebrow="KITCHENS & FIT-OUTS",
         title="A kitchen is a project, not a shopping trip.",
         desc="Kitchen and cabinet projects managed end to end: measured, ordered, fitted and paid against stages, with every variation recorded.",
         quote_lines=["“The kitchen is measured,", "ordered and fitted;", "you pay when each", "stage is done.”"],
         attribution="KITCHEN AND CABINET PROJECTS, MANAGED",
         sub=["The same ledger, stages and receipts as a full build.",
              "A variation is recorded before the money moves."],
         callout=("Photo evidence at every stage", "Filed against the project"),
         last_brass=True,
         cta="QUOTE A KITCHEN FIT-OUT", footer="MEASURE. FIT. PROVE."),
    dict(slug="renovation-record", layout="twotone",
         eyebrow="RENOVATIONS & EXTENSIONS",
         title="A renovation with a paper trail.",
         desc="Renovations and extensions manage the surprises with a written record: condition, variations, finishes and handover, stage by stage.",
         lines=[("A renovation needs a written", "cream"), ("record before the first", "cream"), ("wall comes down.", "brass")],
         sub=["An old building hides surprises. The record is how",
              "you stop them becoming arguments."],
         answer_head="What the renovation file holds",
         answer=[("The condition, recorded first", "Photos and findings before work starts"),
                 ("Every variation in writing", "The change order, before the cash"),
                 ("A handover pack at the end", "Certificates, receipts and photos")],
         cta="MANAGE MY RENOVATION", footer="OLD BUILDING. NEW RECORD."),
    dict(slug="signed-agreements", layout="statement",
         eyebrow="AGREEMENTS",
         title="Scope, terms and a payment schedule. Signed.",
         desc="An agreement states the scope, the terms and the milestone payments, captures a signature on screen and stays in the project file.",
         lines=[("Scope, terms and milestones", "cream"), ("are agreed, signed on", "cream"), ("screen and stored.", "brass")],
         sub=["Scope, terms and a milestone payment schedule in one document.",
              "Sign on screen; the signed record stays with the project.",
              "Void it if it was wrong, and keep the history."],
         gold="A handshake is a start, not a scope.",
         points=[("folder", "SCOPE", "What the money buys"),
                 ("wallet", "MILESTONES", "Payments by stage"),
                 ("check", "SIGNATURE", "On screen, on record")],
         quote="The agreement should be as visible as the work.",
         cta="DRAFT AN AGREEMENT", footer="SCOPE. SIGN. STORE."),
    dict(slug="reports-and-pack", layout="statement",
         eyebrow="REPORTS",
         title="A project pack you can hand to anyone.",
         desc="Committed, funded and spent per build, stage variance with overruns first, a 90-day burn rate with runway, printed as one project pack.",
         lines=[("The facts, the stages and", "cream"), ("the money, printed as", "cream"), ("one project pack.", "brass")],
         sub=["Committed, funded and spent; stage variance with overruns first;",
              "a 90-day burn rate and a runway estimate. Print the whole pack",
              "to PDF for the bank, the family or the next meeting."],
         gold="A report should end the meeting, not start another one.",
         points=[("wallet", "BUDGET", "Committed vs spent"),
                 ("clock", "RUNWAY", "90-day burn"),
                 ("folder", "PACK", "Print to PDF")],
         quote="The numbers should be ready before the question is asked.",
         cta="SEE THE REPORTS", footer="FACTS. STAGES. MONEY."),
    dict(slug="whatsapp-assistant", layout="feature",
         eyebrow="WHATSAPP",
         title="Ask YaVaKa on WhatsApp. The answer comes from the ledger.",
         desc="Balance, status, projects, payments and receipts over WhatsApp, with a human able to take over the conversation.",
         lines=[("Ask YaVaKa on WhatsApp", "cream"), ("and get the balance from", "cream"), ("the real ledger.", "brass")],
         sub=["The people on site may never open a dashboard.",
              "The assistant answers from the same record the portal uses."],
         items=[("chat", "BALANCE", "What is left, right now"),
                ("receipt", "PAY 500", "Record a payment"),
                ("folder", "RECEIPT", "Get the receipt back"),
                ("check", "STATUS", "Where the build stands"),
                ("globe", "PROJECTS", "Every build you can open"),
                ("shield", "HUMAN", "Take over from the assistant")],
         quote="A build should not need an app store to stay accountable.",
         cta="MESSAGE YAVAKA", footer="ASK. RECORD. RECEIVE."),
    dict(slug="suppliers", layout="statement",
         eyebrow="SUPPLIER DIRECTORY",
         title="Zimbabwean suppliers, one directory.",
         desc="A directory of Zimbabwean material suppliers with links out to their own catalogues and price lists.",
         lines=[("Find Zimbabwean material", "cream"), ("suppliers and their", "cream"), ("catalogues in one place.", "brass")],
         sub=["Bricks, cement, roofing and finishes, with a link out",
              "to each supplier's own catalogue and price list."],
         gold="Buying blind is how a budget grows legs.",
         points=[("globe", "LOCAL", "Zimbabwean suppliers"),
                 ("check", "CHECKED", "Names and contacts"),
                 ("folder", "CATALOGUES", "Straight to the source")],
         quote="The cheapest quote is not the cheapest material.",
         cta="BROWSE SUPPLIERS", footer="BUY LOCAL. BUY INFORMED."),
    dict(slug="account-security", layout="feature",
         eyebrow="ACCOUNT SECURITY",
         title="Your build file is private. Prove it.",
         desc="Optional two-step verification, recovery codes, session control, a full audit trail and consistent staff backups.",
         lines=[("Your build file is locked", "cream"), ("down with two-step", "cream"), ("verification and a", "cream"), ("full audit trail.", "brass")],
         sub=["Optional two-step verification, single-use recovery codes",
              "and an audit trail of sign-ins, changes and exports."],
         items=[("lock", "2FA", "TOTP, optional, yours"),
                ("shield", "SESSIONS", "Sign out everywhere"),
                ("receipt", "AUDIT", "Sign-ins and changes"),
                ("globe", "RESET", "One-hour reset links"),
                ("check", "ROLES", "Client, manager, staff"),
                ("folder", "BACKUP", "Consistent snapshots")],
         quote="Access is a permission, not a promise.",
         cta="SECURE MY ACCOUNT", footer="PRIVATE BY DEFAULT."),
    dict(slug="offline-copy", layout="quote",
         eyebrow="OFFLINE & PWA",
         title="The file works when the signal does not.",
         desc="Install YaVaKa on a phone and save an explicit read-only project snapshot before travelling; it survives a signal drop.",
         quote_lines=["“Save the project before", "you travel; the file", "stays readable", "without signal.”"],
         attribution="AN EXPLICIT READ-ONLY OFFLINE COPY",
         sub=["Install YaVaKa on your phone and save the project you are",
              "travelling with. The record survives the dead zone."],
         callout=("Install from the browser", "No app store needed"),
         last_brass=True,
         cta="INSTALL YAVAKA", footer="WORKS OFFLINE. STAYS YOURS."),
    dict(slug="everything", layout="feature",
         eyebrow="THE YAVAKA SYSTEM",
         title="Everything the build needs. Everything the building needs.",
         desc="YaVaKa covers money, stages, documents, agreements, property checks, rental management, WhatsApp and reports in one account.",
         lines=[("One account holds the build,", "cream"), ("the building and every", "cream"), ("record between them.", "brass")],
         sub=["From funding a first stage to receipting next month's rent.",
              "The same file carries the build and the building."],
         items=[("wallet", "MONEY", "Funding, expenses, receipts"),
                ("check", "STAGES", "19 Zimbabwe stages"),
                ("folder", "DOCUMENTS", "Plans, proof, agreements"),
                ("camera", "CHECKS", "Findings, photos, video"),
                ("wallet", "RENTAL", "Invoices, arrears, reports"),
                ("globe", "ANYWHERE", "Web, WhatsApp, offline")],
         quote="Build from anywhere. Manage from anywhere.",
         cta="GET STARTED", footer="BUILD. PROVE. MANAGE."),
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("yavaka-*.svg"):
        stale.unlink()
    for stale in OUT_DIR.glob("yavaka-*.png"):
        stale.unlink()
    for index, poster in enumerate(POSTERS, start=1):
        svg = LAYOUTS[poster["layout"]](poster)
        name = f"yavaka-{index:02d}-{poster['slug']}.svg"
        (OUT_DIR / name).write_text(svg, encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
