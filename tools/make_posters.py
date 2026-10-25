"""Generates the YaVaKa advertising poster set as SVG.

Run from the repository root:

    python tools/make_posters.py

Posters land in static/posters/ at 1080x1350 (Instagram / WhatsApp Status
portrait). Export a PNG with any headless browser, e.g.:

    chrome --headless --screenshot=out.png --window-size=1080,1350 poster.svg
"""

from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "static" / "posters"

W, H = 1080, 1350
M = 72
CONTENT_W = W - (M * 2)

FOREST_DEEP = "#07231f"
FOREST = "#0f5d46"
FOREST_MID = "#0c3b31"
CREAM = "#fffdf8"
SAND = "#f7f4ef"
SAND_DEEP = "#ece6da"
BRASS = "#c8963e"
BRASS_LIGHT = "#e2b967"
BRASS_DIM = "#a97926"
INK = "#183e32"
INK_SOFT = "#526359"

SERIF = "Georgia, 'Times New Roman', serif"
SANS = "Arial, Helvetica, sans-serif"

RATIO_SERIF_BOLD = 0.53

# Fixed vertical rhythm shared by every poster, so the set looks like one family.
HEAD_BASELINE = 322
PANEL_TOP = 690
QUOTE_BASELINE = 1062
CTA_TOP = 1094
CTA_HEIGHT = 66
BAND_TOP = 1178
BAND_HEIGHT = 78
FOOTER_BASELINE = 1272


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
    the site cannot drift apart: forest tile, cream roof line, three brass bars
    of rising height.
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
            f'<rect x="{x0}" y="{y0}" width="{size}" height="{size}" '
            f'rx="{round(15 * scale, 2)}" fill="#0F5D46"/>',
            f'<path d="M{px(12)} {py(32)} L{px(32)} {py(15)} L{px(52)} {py(32)}" '
            f'fill="none" stroke="#F7F4EF" stroke-width="{round(4.2 * scale, 2)}" '
            'stroke-linecap="round" stroke-linejoin="round"/>',
            f'<rect x="{px(17)}" y="{py(34)}" width="{round(5.5 * scale, 2)}" '
            f'height="{round(15 * scale, 2)}" rx="{round(2.4 * scale, 2)}" fill="#C8963E"/>',
            f'<rect x="{px(26.5)}" y="{py(29)}" width="{round(5.5 * scale, 2)}" '
            f'height="{round(20 * scale, 2)}" rx="{round(2.4 * scale, 2)}" fill="#E3B968"/>',
            f'<rect x="{px(36)}" y="{py(24)}" width="{round(5.5 * scale, 2)}" '
            f'height="{round(25 * scale, 2)}" rx="{round(2.4 * scale, 2)}" fill="#C8963E"/>',
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
    width = round(len(label) * 13.0 + 112)
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


HOUSE_SHAPE = (
    '<path d="M622 192 779 89l156 103" fill="none" stroke="{c}" stroke-width="9" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M666 182v107h225V182M741 289v-69h75v69" fill="{c}" fill-opacity=".1" '
    'stroke="{c}" stroke-width="6" stroke-linejoin="round"/>'
    '<path d="M688 211h26v29h-26zM850 211h25v29h-25z" fill="{b}" opacity=".86"/>'
    '<path d="M580 290h365" stroke="{b}" stroke-width="6" stroke-linecap="round"/>'
    '<path d="M602 313h321" stroke="{c}" stroke-opacity=".45" stroke-width="4" stroke-linecap="round"/>'
)


def house(y_offset=0):
    return (
        f'<g transform="translate(0 {y_offset})">'
        f'<circle cx="773" cy="82" r="41" fill="{BRASS}" opacity=".18"/>'
        f'<circle cx="773" cy="82" r="25" fill="{BRASS_LIGHT}" opacity=".75"/>'
        f'{HOUSE_SHAPE.format(c=CREAM, b=BRASS_LIGHT)}</g>'
    )


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


def points_panel(y, points):
    """Glass panel with three proof points beside the house motif."""
    card_w, card_h, gap = 364, 68, 10
    panel_h = len(points) * card_h + (len(points) - 1) * gap + 68
    out = [
        rect(66, y, 948, panel_h, "#ffffff", rx=30, opacity=0.07),
        rect(66, y, 948, panel_h, "none", rx=30, stroke=CREAM, stroke_w=1, opacity=0.16),
        f'<path d="M66 {y + panel_h - 56}h948" stroke="{CREAM}" stroke-opacity=".13"/>',
        f'<path d="M66 {y + panel_h - 26}c161-61 287-31 427-20 152 13 294-27 521-81v103H66Z" '
        f'fill="{FOREST_DEEP}" opacity=".82"/>',
    ]
    for index, (glyph, label, sub) in enumerate(points):
        cy = y + 22 + index * (card_h + gap)
        tint = "#f5ebd6" if glyph in BRASS_GLYPHS else "#e7f0eb"
        out.append(rect(102, cy, card_w, card_h, CREAM, rx=16))
        out.append(f'<circle cx="141" cy="{cy + card_h / 2}" r="19" fill="{tint}"/>')
        out.append(icon(glyph, 141, cy + card_h / 2))
        out.append(text(176, cy + 30, label, 15, "#193c31", weight=700, family=SANS, spacing=1))
        out.append(text(176, cy + 52, sub, 15.5, "#58685e", weight=400, family=SANS))
    return "".join(out), panel_h


def dark_backdrop():
    return "".join([
        rect(0, 0, W, H, "url(#sky)"),
        f'<circle cx="944" cy="102" r="176" fill="{BRASS}" opacity=".09"/>',
        f'<path d="M0 627c172-84 305-89 476-43s347 28 604-71v310H0Z" fill="#0b4035" opacity=".85"/>',
        f'<path d="M0 716c190-84 355-67 526-34s348 13 554-82v192H0Z" fill="{FOREST_DEEP}"/>',
        f'<g fill="none" stroke="#d8b36d" stroke-opacity=".22">'
        f'<path d="M-20 230c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/>'
        f'<path d="M-20 249c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/></g>',
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


def accountability_card(x0, y0, height=292):
    """Right-bleeding cream card with a rounded brass left edge.

    Placed in the visual middle-right of every poster so the promise reads as
    a headline, not as fine print.
    """
    r = 30
    x1 = W
    headlines = ["ALL ACCOUNTABLE.", "ALL TRACEABLE.", "ALL SECURE."]
    lines = [
        "Automated WhatsApp and email notifications.",
        "Every receipt, invoice and document — at every",
        "stage — in your YaVaKa portal. Private to your",
        "build team and encrypted in transit.",
    ]

    # Centre the block vertically so the card works at any height.
    content_h = 70 + 42 + (len(lines) - 1) * 26
    top = y0 + max(30, (height - content_h) / 2)

    path = (
        f"M{x1} {y0} H{x0 + r} Q{x0} {y0} {x0} {y0 + r} "
        f"V{y0 + height - r} Q{x0} {y0 + height} {x0 + r} {y0 + height} H{x1} Z"
    )
    out = [
        f'<path d="{path}" fill="{CREAM}" stroke="{BRASS}" stroke-width="3.5"/>',
        f'<circle cx="{x0 + 56}" cy="{top + 42}" r="23" fill="#f2e6cd"/>',
        icon("lock", x0 + 56, top + 42),
    ]
    for index, headline in enumerate(headlines):
        out.append(
            text(x0 + 92, top + 26 + index * 22, headline, 16.5, INK,
                 weight=700, family=SANS, spacing=0.8)
        )

    y = top + 112
    for line in lines:
        out.append(text(x0 + 42, y, line, 15.5, INK_SOFT, weight=400, family=SANS))
        y += 26
    return "".join(out)


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
    body = [dark_backdrop(), logo("light"), pill(M + 2, 157, p["eyebrow"])]
    head, y = head_block(p["lines"])
    body.append(head)
    sub, y = sub_block(p["sub"], y + 16)
    body.append(sub)
    if p.get("gold"):
        y += 10
        body.append(text(M + 4, y, p["gold"], 20, BRASS_LIGHT, weight=700, family=SANS))

    panel, panel_h = points_panel(PANEL_TOP, p["points"])
    body.append(panel)
    body.append(accountability_card(640, PANEL_TOP, panel_h))

    body.append(text(M, QUOTE_BASELINE, f"\u201c{p['quote']}\u201d", 27, CREAM,
                     weight=700, italic=True))
    body.append(cta(M, CTA_TOP, p["cta"], h=CTA_HEIGHT))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_twotone(p):
    split = p.get("split", 742)
    body = [
        rect(0, 0, W, H, SAND),
        rect(0, 0, W, split, FOREST_MID),
        f'<circle cx="944" cy="96" r="180" fill="{BRASS}" opacity=".09"/>',
        f'<path d="M0 {split - 120}c190-54 352-26 527 6s367-8 553-66v180H0Z" fill="{FOREST_DEEP}"/>',
        f'<g fill="none" stroke="#d8b36d" stroke-opacity=".2">'
        f'<path d="M-20 214c145-91 289-94 424-3s284 87 435 4 253-82 387-15"/></g>',
        logo("light"),
        pill(M + 2, 152, p["eyebrow"]),
        f'<g opacity=".5" transform="translate(96 426) scale(.82)">'
        f'{HOUSE_SHAPE.format(c=CREAM, b=BRASS_LIGHT)}</g>',
    ]
    head, y = head_block(p["lines"], start=300, base=58)
    body.append(head)
    sub, _ = sub_block(p["sub"], y + 8)
    body.append(sub)

    body.append(f'<path d="M{M} {split + 66}h560" stroke="{BRASS}" stroke-width="3" '
                f'stroke-linecap="round"/>')
    body.append(text(M, split + 34, p["answer_head"], 30, INK, weight=700))

    row = split + 112
    for index, (label, sub_line) in enumerate(p["answer"], start=1):
        body.append(text(M, row, f"{index:02d}", 15, BRASS_DIM, weight=700, family=SANS, spacing=1.4))
        body.append(text(M + 48, row, label, 19, INK, weight=700, family=SANS))
        body.append(text(M + 48, row + 26, sub_line, 16, INK_SOFT, weight=400, family=SANS))
        row += 74

    body.append(accountability_card(660, split + 12, 292))
    body.append(cta(M, CTA_TOP, p["cta"], h=CTA_HEIGHT))
    body.append(footer(p["footer"], dark=False))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_quote(p):
    body = [
        rect(0, 0, W, H, "url(#paper)"),
        f'<path d="M0 0h1080v196c-214 65-370 50-551 5S195 158 0 232Z" fill="{FOREST}"/>',
        f'<circle cx="956" cy="129" r="178" fill="{BRASS}" opacity=".12"/>',
        logo("light"),
        text(M + 6, 152, p["eyebrow"], 15, BRASS_LIGHT, weight=700, family=SANS, spacing=3.2),
        text(M - 14, 432, "\u201c", 190, BRASS, weight=700, opacity=0.16),
    ]

    lines = p["quote_lines"]
    size = round(fit(max(lines, key=len), 470, 54))
    y = 466
    for index, line in enumerate(lines):
        colour = BRASS_DIM if index == len(lines) - 1 and p.get("last_brass") else INK
        body.append(text(M + 4, y, line, size, colour, weight=700, spacing=-size * 0.026))
        y += size * 1.2

    body.append(accountability_card(560, 452, 292))

    y = 830
    body.append(f'<path d="M{M + 4} {y - 40}h120" stroke="{BRASS}" stroke-width="3" '
                f'stroke-linecap="round"/>')
    body.append(text(M + 4, y, p["attribution"], 17, INK_SOFT, weight=400, family=SANS, spacing=1.2))

    sub, y = sub_block(p["sub"], y + 40, fill=INK_SOFT, size=20, dy=28)
    body.append(sub)

    if p.get("callout"):
        y += 18
        body.append(rect(M, y - 24, CONTENT_W, 88, "#fffdf8", rx=20, stroke="#e2d9ca"))
        body.append(f'<circle cx="{M + 44}" cy="{y + 18}" r="20" fill="#f5ebd6"/>')
        body.append(icon("receipt", M + 44, y + 18))
        body.append(text(M + 82, y, p["callout"][0], 18, INK, weight=700, family=SANS))
        body.append(text(M + 82, y + 26, p["callout"][1], 16, INK_SOFT, weight=400, family=SANS))

    body.append(cta(M, CTA_TOP, p["cta"], fill=FOREST, color=CREAM, arrow=BRASS_LIGHT, h=CTA_HEIGHT))
    body.append(footer(p["footer"], dark=False))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_stat(p):
    body = [
        dark_backdrop(),
        f'<circle cx="868" cy="520" r="300" fill="{BRASS}" opacity=".07"/>',
        logo("light"),
        pill(M + 2, 157, p["eyebrow"]),
        text(M - 6, 500, p["stat"], 236, BRASS_LIGHT, weight=700, spacing=-8),
        text(M + 4, 578, p["stat_label"], 24, CREAM, weight=700, family=SANS, spacing=1.4),
        accountability_card(636, 330, 292),
    ]
    head, y = head_block(p["lines"], start=730, base=54)
    body.append(head)
    sub, y = sub_block(p["sub"], y + 4)
    body.append(sub)
    if p.get("gold"):
        y += 10
        body.append(text(M + 4, y, p["gold"], 20, BRASS_LIGHT, weight=700, family=SANS))

    body.append(cta(M, CTA_TOP, p["cta"], h=CTA_HEIGHT))
    body.append(footer(p["footer"]))
    return svg_doc(p["title"], p["desc"], "".join(body))


def layout_gate(p):
    """A build read as a sequence of gates, one of them always the one in front.

    Composition is a horizontal rail rather than a stacked column, so a reader
    scrolling a status feed sees something other than another block of type.
    """
    body = [
        dark_backdrop(),
        f'<circle cx="150" cy="330" r="230" fill="{BRASS}" opacity=".06"/>',
        logo("light"),
        pill(M + 2, 157, p["eyebrow"]),
    ]
    head, y = head_block(p["lines"], start=306, base=56)
    body.append(head)
    sub, y = sub_block(p["sub"], y + 10)
    body.append(sub)

    gates = p["gates"]
    current = p.get("current", 0)
    rail_y = 646
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

    body.append(rect(M, 790, CONTENT_W, 152, "#ffffff", rx=26, opacity=0.06))
    body.append(rect(M, 790, CONTENT_W, 152, "none", rx=26, stroke=CREAM,
                     stroke_w=1, opacity=0.16))
    body.append(f'<circle cx="{M + 62}" cy="866" r="24" fill="{BRASS}" opacity=".16"/>')
    body.append(icon("lock", M + 62, 866, colour=BRASS_LIGHT))
    body.append(text(M + 110, 852, p["gate_title"], 22, CREAM, weight=700, family=SANS))
    body.append(text(M + 110, 886, p["gate_body"], 17, "#c3d2c9", weight=400, family=SANS))

    body.append(text(M + 4, 1040, f"\u201c{p['quote']}\u201d", 25, BRASS_LIGHT,
                     weight=700, italic=True))
    body.append(cta(M, 1090, p["cta"], h=CTA_HEIGHT))
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
        f'<path d="M0 0h1080v412c-208 74-372 46-556 2S198 358 0 432Z" fill="{FOREST_MID}"/>',
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

    head, y = head_block(p["lines"], start=316, base=46)
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


LAYOUTS = {
    "statement": layout_statement,
    "twotone": layout_twotone,
    "quote": layout_quote,
    "stat": layout_stat,
    "gate": layout_gate,
    "ledger": layout_ledger,
}


POSTERS = [
    dict(
        slug="you-cant-be-on-site", layout="statement",
        eyebrow="THE DIASPORA BUILD PROBLEM",
        title="You can't be on site. We can.",
        desc="YaVaKa independently manages a Zimbabwe build for a diaspora client: vetting the contractor, approving every payment and resolving differences on site.",
        lines=[("You can't be", "cream"), ("on site.", "cream"), ("We can.", "brass")],
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
        quote_lines=["\u201cTranche two cleared.", "Then the site", "went quiet.\u201d"],
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
        lines=[("Your contractor.", "cream"), ("Our standard.", "brass")],
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
        lines=[("Build with us.", "cream"), ("Or have us manage", "cream"), ("whoever does.", "brass")],
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
        lines=[("Vet the builder.", "cream"), ("Then send a dollar.", "brass")],
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
        lines=[("You're not waiting", "cream"), ("for a report.", "cream"), ("You're watching.", "brass")],
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
        lines=[("Overseas clients", "cream"), ("get overseas prices.", "brass")],
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
        quote_lines=["\u201cI stopped asking", "for photos of the", "receipt. I could", "see it.\u201d"],
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
        lines=[("One missed gate", "cream"), ("stops the whole build.", "brass")],
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
        lines=[("Don't make family", "cream"), ("your site manager.", "brass")],
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
        lines=[("Half a house.", "cream"), ("A full invoice.", "brass")],
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
        lines=[("The last 10%", "cream"), ("is where builds stall.", "brass")],
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
        quote_lines=["\u201cDisagreements", "get expensive when", "nobody is in", "the room.\u201d"],
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
        lines=[("The site goes quiet", "cream"), ("the day you", "cream"), ("fly back.", "brass")],
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
        lines=[("We can build it.", "cream"), ("We would rather", "cream"), ("manage it.", "brass")],
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
        quote_lines=["\u201cOne build.", "One ledger.", "One number", "that answers.\u201d"],
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
        lines=[("Progress in", "cream"), ("your pocket.", "cream"), ("Not a rumour.", "brass")],
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
        lines=[("Keys in your hand.", "cream"), ("The whole file", "cream"), ("behind them.", "brass")],
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
        lines=[("Verify. Quote.", "cream"), ("Record. Repeat.", "brass")],
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
        lines=[("Already three", "cream"), ("months in?", "cream"), ("We can still take the wheel.", "brass")],
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
        lines=[("Take control.", "cream"), ("Keep the site.", "cream"), ("Keep the crew.", "brass")],
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
        quote_lines=["\u201cYou cannot audit", "what nobody", "recorded.\u201d"],
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
        lines=[("Every project.", "cream"), ("One screen.", "cream"), ("One standard.", "brass")],
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
        lines=[("The paperwork", "cream"), ("does itself.", "brass")],
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
        lines=[("Win on evidence.", "cream"), ("Not on promises.", "brass")],
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
        lines=[("Built for", "cream"), ("the distance.", "brass")],
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
        lines=[("A second opinion", "cream"), ("costs less than", "cream"), ("a second slab.", "brass")],
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
        quote_lines=["\u201cYou are four", "payments ahead", "of the paperwork.\u201d"],
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
        lines=[("Run more builds.", "cream"), ("Keep your evenings.", "brass")],
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
        lines=[("Zimbabwean built.", "cream"), ("For those abroad.", "brass")],
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

    dict(slug="the-first-question", layout="statement",
         eyebrow="BEFORE YOU PAY ANYONE",
         title="Ask what happens when the money is finished and the work is not.",
         desc="YaVaKa defines the finish line before the first payment, so a build cannot quietly outrun its budget.",
         lines=[("Ask the question", "cream"), ("before the", "cream"), ("first payment.", "brass")],
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
         quote_lines=["\u201cNobody is on site.", "Everybody is", "on the group chat.\u201d"],
         last_brass=True, attribution="HOW A BUILD BECOMES A DISCUSSION",
         sub=["Opinions travel faster than work. Without a person who checks,",
              "decides and records, the group chat becomes the site office."],
         callout=("Put one person on it", "Accountable, named, on the ground"),
         cta="PUT SOMEONE ON SITE", footer="A WITNESS BEATS A WITNESS CHAT."),
    dict(slug="cash-with-no-paper", layout="statement",
         eyebrow="THE RECEIPT RULE",
         title="If it left your account and left no paper, it did not happen.",
         desc="YaVaKa treats a payment without a receipt or approved stage as an open question, not a settled cost.",
         lines=[("No paper.", "cream"), ("No payment.", "brass")],
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
         quote_lines=["\u201cThe quote was fair.", "The variations", "were not.\u201d"],
         last_brass=True, attribution="THE SLOWEST WAY TO LOSE A BUDGET",
         sub=["Each change looks sensible on its own. Together they can add a third",
              "to the cost, and nobody agreed to a third."],
         callout=("Every variation in writing", "Priced, approved, recorded"),
         cta="CONTROL VARIATIONS", footer="CHANGE ORDERS, OR NOTHING."),
    dict(slug="three-contractors-one-standard", layout="statement",
         eyebrow="MULTIPLE TRADES",
         title="Five trades, five standards, one site. Somebody has to hold the line.",
         desc="YaVaKa coordinates separate trades against one specification so quality does not depend on who arrived first.",
         lines=[("Many trades.", "cream"), ("One standard.", "brass")],
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
         quote_lines=["\u201cThe build is fine.", "The argument", "about it is not.\u201d"],
         last_brass=True, attribution="WHY RECORDS MATTER MORE THAN OPINIONS",
         sub=["When several people fund a build, memory becomes evidence. A record",
              "everyone can read ends the argument before it starts."],
         callout=("One record, many readers", "Owners, family and contractor"),
         cta="SHARE THE RECORD", footer="ONE RECORD. FEWER ARGUMENTS."),
    dict(slug="the-photo-that-proves-nothing", layout="statement",
         eyebrow="EVIDENCE, NOT IMPRESSIONS",
         title="A photo proves a wall exists. It does not prove the wall is right.",
         desc="Progress photos are useful, but they do not show specification, quantity, approval or cost.",
         lines=[("A photo proves", "cream"), ("a wall exists.", "cream"), ("Not that it is right.", "brass")],
         sub=["Pictures are the easiest thing to send and the weakest thing to rely on.",
              "Stage approval, measurement and receipts are what actually settle questions."],
         gold="Pictures reassure. Records decide.",
         points=[("camera", "PHOTOS", "Dated, per stage"),
                 ("check", "APPROVAL", "Signed stage gates"),
                 ("receipt", "COST", "Receipt per payment")],
         quote="Reassurance is not evidence.",
         cta="ASK FOR RECORDS", footer="RECORDS DECIDE."),
    dict(slug="the-stage-nobody-signed", layout="statement",
         eyebrow="STAGE GATES",
         title="The stage nobody signed off is the stage everybody argues about.",
         desc="YaVaKa requires an explicit approval per stage before the next one is funded.",
         lines=[("No signature.", "cream"), ("No next stage.", "brass")],
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
         quote_lines=["\u201cThe last tranche", "is the one where", "you have no leverage.\u201d"],
         last_brass=True, attribution="WHY RELEASE SCHEDULES MATTER",
         sub=["Pay the whole balance and the finishing touches become a favour.",
              "Hold a defined retention and they remain an obligation."],
         callout=("Retention, agreed up front", "Protects the snag list"),
         cta="AGREE RETENTION", footer="KEEP THE LAST GATE CLOSED."),
    dict(slug="distance-is-not-permission", layout="statement",
         eyebrow="FOR THOSE ABROAD",
         title="Distance is not permission for anyone to spend your money quietly.",
         desc="Being far away should never mean being uninformed. YaVaKa keeps the record visible from anywhere.",
         lines=[("Distance is not", "cream"), ("permission.", "brass")],
         sub=["You are allowed to ask for the invoice. You are allowed to ask what a",
              "payment bought. A good build team expects the question."],
         gold="You should never feel rude for asking where the money went.",
         points=[("globe", "REMOTE", "Full visibility"),
                 ("receipt", "TRACE", "Payment to proof"),
                 ("chat", "REACH", "Updates that arrive")],
         quote="Being far away is not the same as being uninformed.",
         cta="SEE EVERYTHING", footer="DISTANCE IS NOT PERMISSION."),
    dict(slug="whose-gate-is-this", layout="gate",
         eyebrow="COUNCIL & STATUTORY GATES",
         title="Nobody can name the gate their build is waiting on.",
         desc="YaVaKa maps the 19-stage Zimbabwe build sequence and names each statutory gate, its authority and what it blocks.",
         lines=[("Every build waits", "cream"), ("on a gate.", "brass")],
         sub=["Council plans, cession, EMA, ZINWA, ZESA, inspections.",
              "Each one has an authority, a document and a stage it holds up."],
         gates=["Title", "Council", "Footings", "Walling", "Roof", "Handover"],
         current=2, quote="If nobody can name it, nobody can chase it.",
         gate_title="COUNCIL PLANS",
         gate_body="Blocks superstructure. Chased, not waited on.",
         cta="NAME EVERY GATE", footer="GATES MAPPED IN ORDER."),
    dict(slug="stage-gate-discipline", layout="gate",
         eyebrow="FOR THE MANAGER ON THE GROUND",
         title="A stage is not finished because it looks finished.",
         desc="Each stage closes only when its check, its certificate and its cost are all recorded against it.",
         lines=[("Finished", "cream"), ("is a signature.", "brass")],
         sub=["Looking done and being signed off are two different events.",
              "Close one stage at a time and the snag list stops growing."],
         gates=["Set out", "Found", "Slab", "Walls", "Ring beam", "Roof"],
         current=3, quote="The site stops arguing once the stages are closed.",
         gate_title="WALLING APPROVED",
         gate_body="Measured, checked and costed before ring beam.",
         cta="CLOSE THE STAGE", footer="ONE STAGE. ONE SIGNATURE."),
    dict(slug="funding-not-feelings", layout="gate",
         eyebrow="MONEY AGAINST STAGES",
         title="Money should follow a gate, not a feeling.",
         desc="YaVaKa ties each release of funds to a stage that has actually been approved on site.",
         lines=[("Release on a gate.", "cream"), ("Never on a mood.", "brass")],
         sub=["\"Almost there\" is not a milestone. A signed stage is.",
              "Each deposit lands against the stage it is paying for."],
         gates=["Deposit", "Substructure", "Superstructure", "Roof", "Finishes", "Snag"],
         current=2, quote="Funded stages finish. Unfunded intentions drift.",
         gate_title="SUPERSTRUCTURE FUNDED",
         gate_body="Balance moves only when the gate opens.",
         cta="FUND THE STAGE", footer="MONEY FOLLOWS PROGRESS."),
    dict(slug="first-day-on-site", layout="gate",
         eyebrow="STARTING TOMORROW",
         title="Most builds go wrong before the first brick is laid.",
         desc="Budget, programme, approvals and a signed scope are all set before work starts on a YaVaKa-managed build.",
         lines=[("The build is decided", "cream"), ("before it starts.", "brass")],
         sub=["Scope, price, programme and approvals all exist up front.",
              "Changing them afterwards is where the money disappears."],
         gates=["Scope", "Price", "Approvals", "Mobilise", "Found", "Build"],
         current=1, quote="Set it up properly once and the rest is just sequencing.",
         gate_title="PRICE AGAINST QUANTITIES",
         gate_body="Measured work, market rates, nothing rounded.",
         cta="SET IT UP RIGHT", footer="DECIDED BEFORE DAY ONE."),
    dict(slug="the-quiet-variation", layout="gate",
         eyebrow="VARIATIONS",
         title="The expensive change is the one nobody wrote down.",
         desc="Every variation on a YaVaKa build is written, priced and approved before the work happens.",
         lines=[("No verbal extras.", "cream"), ("No surprise invoice.", "brass")],
         sub=["A variation on a phone call is a favour, and favours have no cap.",
              "Written and priced first, then built, then paid."],
         gates=["Request", "Measure", "Price", "Approve", "Build", "Settle"],
         current=3, quote="A change you did not price is a price you did not choose.",
         gate_title="WRITTEN AND APPROVED",
         gate_body="Priced before it is built, not after.",
         cta="PRICE EVERY CHANGE", footer="NOTHING CHANGES FOR FREE."),
    dict(slug="nobody-chases-for-you", layout="gate",
         eyebrow="CHASING, DONE FOR YOU",
         title="Chasing is the job. You should not be the one doing it.",
         desc="YaVaKa tracks each gate, chases the responsible party and records the outcome on the project.",
         lines=[("Somebody should be", "cream"), ("chasing this.", "brass")],
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
         lines=[("A balance tells you", "cream"), ("nothing.", "brass")],
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
         lines=[("Not a photo", "cream"), ("in a chat.", "brass")],
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
         lines=[("Where did the", "cream"), ("balance go?", "brass")],
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
         lines=[("The cheap quote", "cream"), ("left things out.", "brass")],
         slip_head="BILL OF QUANTITIES",
         slip_sub="Priced from measured work",
         entries=[("Excavation", "included", "check"),
                  ("Concrete, footings", "included", "check"),
                  ("Council fees", "not included", "clock"),
                  ("Sewer connection", "not included", "clock")],
         total_label="REAL COST vs THE QUOTE", total_value="+18%",
         cta="SEE THE FULL BILL", footer="PRICE THE WORK, NOT A NUMBER."),
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
