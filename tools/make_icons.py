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


if __name__ == "__main__":
    main()
