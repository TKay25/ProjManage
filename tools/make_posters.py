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
    face = CREAM if tone == "light" else INK
    sub = "#d2ded7" if tone == "light" else "#6b7a70"
    y = 62
    out = [
        rect(M, y, 54, 54, CREAM if tone != "light" else FOREST, rx=14,
             opacity=0.14 if tone != "light" else None),
        f'<path d="m{M + 11} {y + 28} 16-14 16 14" fill="none" stroke="{CREAM}" stroke-width="3.5" '
        f'stroke-linecap="round" stroke-linejoin="round"/>',
        f'<path d="M{M + 16} {y + 30}v13h22V{y + 30}M{M + 22} {y + 43}V{y + 32}h9v11" fill="none" '
        f'stroke="{BRASS}" stroke-width="3" stroke-linejoin="round"/>',
        text(M + 70, y + 38, "YaVaKa", 32, face, weight=700, family=SANS, spacing=-0.5),
        text(M + 72, y + 62, "BUILD FROM ANYWHERE", 13, sub, weight=700, family=SANS, spacing=2.2),
    ]
    return "".join(out)


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


def icon(glyph, cx, cy):
    """Draws a glyph from the 24x24 set centred on (cx, cy)."""
    colour = BRASS_DIM if glyph in BRASS_GLYPHS else FOREST
    path = ICON_PATHS[glyph].replace("{s}", BRASS_DIM)
    return (f'<g transform="translate({cx - 12} {cy - 12})" fill="none" stroke="{colour}" '
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
    top = y0 + 42
    path = (
        f"M{x1} {y0} H{x0 + r} Q{x0} {y0} {x0} {y0 + r} "
        f"V{y0 + height - r} Q{x0} {y0 + height} {x0 + r} {y0 + height} H{x1} Z"
    )
    out = [
        f'<path d="{path}" fill="{CREAM}" stroke="{BRASS}" stroke-width="3.5"/>',
        f'<circle cx="{x0 + 58}" cy="{top + 26}" r="23" fill="#f2e6cd"/>',
        icon("lock", x0 + 58, top + 26),
        text(x0 + 96, top + 20, "ALL ACCOUNTABLE.", 17.5, INK, weight=700, family=SANS, spacing=0.8),
        text(x0 + 96, top + 44, "ALL TRACEABLE.", 17.5, INK, weight=700, family=SANS, spacing=0.8),
    ]
    lines = [
        "You get automated WhatsApp",
        "and email notifications — and",
        "you can see every receipt,",
        "invoice and document, at every",
        "stage, in your YaVaKa portal.",
    ]
    y = top + 104
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


LAYOUTS = {
    "statement": layout_statement,
    "twotone": layout_twotone,
    "quote": layout_quote,
    "stat": layout_stat,
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
        slug="you-dont-need-to-be-there", layout="quote",
        eyebrow="THE WHOLE IDEA",
        title="You don't need to be in Zimbabwe to build in Zimbabwe.",
        desc="YaVaKa lets Zimbabweans abroad build or manage a build back home with independent oversight, logged payments and receipts.",
        quote_lines=["\u201cYou don't need", "to be in Zimbabwe", "to build", "in Zimbabwe.\u201d"],
        last_brass=True,
        attribution="YAVAKA · INDEPENDENT BUILD MANAGEMENT",
        sub=["Someone accountable stands on the site, approves the payments, resolves",
             "the differences and logs it all. You keep living your life."],
        callout=("Start your build record", "Free to set up · add your manager later"),
        cta="START YOUR BUILD",
        footer="BUILD FROM ANYWHERE.",
    ),
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
