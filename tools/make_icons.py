"""Render the YaVaKa app icons from the same geometry as ui.logo_mark().

The mark is a copper roof pitch over pale walls on a copper foundation, so the
icons are drawn from the 64-unit viewBox rather than hand-traced: change the
mark in ui.logo_mark() and re-run this file to keep the PWA icons in step.

    python tools/make_icons.py

Needs Pillow: pip install Pillow
"""

from pathlib import Path

from PIL import Image, ImageDraw

ICONS = Path(__file__).resolve().parent.parent / "static" / "icons"

TILE = "#24395F"
ROOF = "#CC8C64"
WALL = "#F5F7FA"
BASE = "#BA7044"

# Geometry copied from ui.logo_mark()'s 0 0 64 64 viewBox.
TILE_RADIUS = 16.0
ROOF_PATH = [(14.0, 30.0), (32.0, 14.5), (50.0, 30.0)]
WALL_PATHS = [[(15.0, 31.0), (15.0, 46.0)], [(49.0, 31.0), (49.0, 46.0)]]
BASE_BOX = (10.0, 49.6, 54.0, 54.0)

ROOF_WIDTH = 5.2
WALL_WIDTH = 4.4
BASE_RADIUS = 2.2

SUPERSAMPLE = 4


def _stroke(draw, points, colour, width, scale, offset):
    """A round-capped polyline, which is what the SVG stroke-linecap draws."""
    pixels = width * scale
    scaled = [(x * scale + offset, y * scale + offset) for x, y in points]
    draw.line(scaled, fill=colour, width=round(pixels), joint="curve")
    radius = pixels / 2
    for x, y in (scaled[0], scaled[-1]):
        draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=colour)


def render(size, *, maskable=False):
    """One icon. Maskable icons bleed to the edge, so the mark is inset."""
    work = size * SUPERSAMPLE
    image = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if maskable:
        draw.rectangle([0, 0, work - 1, work - 1], fill=TILE)
        scale = work / 64 * 0.66
        offset = (work - 64 * scale) / 2
    else:
        draw.rounded_rectangle(
            [0, 0, work - 1, work - 1], radius=TILE_RADIUS / 64 * work, fill=TILE
        )
        scale = work / 64
        offset = 0.0

    _stroke(draw, ROOF_PATH, ROOF, ROOF_WIDTH, scale, offset)
    for path in WALL_PATHS:
        _stroke(draw, path, WALL, WALL_WIDTH, scale, offset)

    left, top, right, bottom = BASE_BOX
    draw.rounded_rectangle(
        [left * scale + offset, top * scale + offset,
         right * scale + offset, bottom * scale + offset],
        radius=BASE_RADIUS * scale,
        fill=BASE,
    )

    return image.resize((size, size), Image.LANCZOS)


def main():
    targets = [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("apple-touch-icon.png", 180, False),
        ("favicon-32.png", 32, False),
        ("maskable-512.png", 512, True),
    ]
    for name, size, maskable in targets:
        path = ICONS / name
        render(size, maskable=maskable).save(path)
        print(f"wrote {path.relative_to(ICONS.parent.parent)} ({size}px)")

    render_og_card()
    print("wrote static/img/og-card.png (1200x630)")


OG_SIZE = (1200, 630)
OG_PHOTO = ICONS.parent / "img" / "hero" / "structure.jpg"
OG_CARD = ICONS.parent / "img" / "og-card.png"


def _font(size, bold=True):
    """Segoe UI where it exists, then Arial, then Pillow's own default."""
    from PIL import ImageFont

    names = ("segoeuib.ttf", "segoeuisl.ttf") if bold else ("segoeui.ttf",)
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    for name in ("arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_og_card():
    """The 1200x630 share card: the hero photograph under the same flat scrim."""
    card = Image.new("RGB", OG_SIZE, TILE)

    if OG_PHOTO.exists():
        photo = Image.open(OG_PHOTO).convert("RGB")
        scale = max(OG_SIZE[0] / photo.width, OG_SIZE[1] / photo.height)
        photo = photo.resize(
            (round(photo.width * scale), round(photo.height * scale)), Image.LANCZOS
        )
        left = (photo.width - OG_SIZE[0]) // 2
        top = (photo.height - OG_SIZE[1]) // 2
        card.paste(photo.crop((left, top, left + OG_SIZE[0], top + OG_SIZE[1])), (0, 0))

    scrim = Image.new("RGB", OG_SIZE, (9, 14, 26))
    card = Image.blend(card, scrim, 0.82)

    draw = ImageDraw.Draw(card)
    mark_size = 88
    _draw_mark(draw, 84, 84, mark_size, "#F5F7FA")

    draw.text((84 + mark_size + 22, 92), "YaVaKa", font=_font(44), fill="#ffffff")
    draw.text(
        (84 + mark_size + 24, 150),
        "B U I L D   F R O M   A N Y W H E R E",
        font=_font(14, bold=False),
        fill="#9fb0cc",
    )

    headline = _font(64)
    draw.text((84, 300), "You can't be on site.", font=headline, fill="#ffffff")
    draw.text((84, 378), "We can.", font=headline, fill=ROOF)

    draw.text(
        (84, 512),
        "Independent build management · Vetted contractors · Payments against proof",
        font=_font(22, bold=False),
        fill="#c8d2e4",
    )
    draw.rounded_rectangle([84, 566, 284, 572], radius=3, fill=BASE)

    OG_CARD.parent.mkdir(parents=True, exist_ok=True)
    card.save(OG_CARD)


def _draw_mark(draw, x, y, size, wall):
    """The bare mark, drawn from the same 64-unit geometry as ui.logo_mark()."""
    scale = size / 64

    def absolute(points):
        return [(x + px * scale, y + py * scale) for px, py in points]

    def capped(points, colour, width):
        pixels = width * scale
        draw.line(points, fill=colour, width=round(pixels), joint="curve")
        for cx, cy in (points[0], points[-1]):
            draw.ellipse(
                [cx - pixels / 2, cy - pixels / 2, cx + pixels / 2, cy + pixels / 2],
                fill=colour,
            )

    capped(absolute(ROOF_PATH), ROOF, ROOF_WIDTH)
    for path in WALL_PATHS:
        capped(absolute(path), wall, WALL_WIDTH)

    left, top, right, bottom = BASE_BOX
    draw.rounded_rectangle(
        [x + left * scale, y + top * scale, x + right * scale, y + bottom * scale],
        radius=BASE_RADIUS * scale,
        fill=BASE,
    )


if __name__ == "__main__":
    main()
