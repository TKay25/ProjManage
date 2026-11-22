"""Prepares the site photography used behind the poster copy.

Run from the repository root after changing a source photo:

    python tools/make_poster_art.py

Each source is centre-cropped to the poster's 4:5 portrait shape, resized to
900x1125 and written as a progressive JPEG in static/poster-art/. The poster
generator embeds those files as data URIs, so every SVG is self-contained and
renders the same in a browser, a phone and a headless screenshot.

Needs Pillow, which is already used by tools/make_icons.py.
"""

from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "static" / "img"
OUT_DIR = ROOT / "static" / "poster-art"

SIZE = (800, 1000)  # 4:5, the Instagram / WhatsApp Status portrait
QUALITY = 72

# name: (source, horizontal focus, vertical focus). Focus 0 keeps the left or
# top edge, 1 keeps the right or bottom, 0.5 centres the crop. The electrician
# stands at the left of his frame, so that crop pulls left.
SOURCES = {
    "kitchen": ("hero/kitchen.jpg", 0.25, 0.5),
    "joinery": ("hero/joinery.jpg", 0.5, 0.5),
    "bathroom": ("hero/bathroom.jpg", 0.5, 0.5),
    "renovation": ("hero/interior.jpg", 0.45, 0.5),
    "electrician": ("hero/firstfix.jpg", 0.0, 0.5),
    "steel": ("hero/structure.jpg", 0.55, 0.5),
    "house": ("hero/house.jpg", 0.5, 0.5),
    "site-house": ("band/site-house.jpg", 0.5, 0.5),
    "site-walls": ("band/site-walls.jpg", 0.5, 0.5),
    "site-finish": ("band/site-finish.jpg", 0.5, 0.5),
    "site-framing": ("band/site-framing.jpg", 0.5, 0.5),
    "site-row": ("band/site-row.jpg", 0.5, 0.5),
    "site-interior": ("band/site-interior.jpg", 0.55, 0.5),
}


def cover(image, focus_x, focus_y):
    width, height = image.size
    target_ratio = SIZE[0] / SIZE[1]
    if width / height > target_ratio:
        crop_w, crop_h = round(height * target_ratio), height
    else:
        crop_w, crop_h = width, round(width / target_ratio)
    left = round((width - crop_w) * focus_x)
    top = round((height - crop_h) * focus_y)
    return image.crop((left, top, left + crop_w, top + crop_h)).resize(
        SIZE, Image.LANCZOS
    )


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (relative, focus_x, focus_y) in SOURCES.items():
        source = IMG_DIR / relative
        target = OUT_DIR / f"{name}.jpg"
        if not source.exists():
            if target.exists():
                print(f"kept {target.relative_to(ROOT)} (source photo is absent)")
                continue
            raise SystemExit(f"missing source photo: {source}")
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            crop = cover(image, focus_x, focus_y)
        crop.save(target, "JPEG", quality=QUALITY, optimize=True, progressive=True)
        print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
