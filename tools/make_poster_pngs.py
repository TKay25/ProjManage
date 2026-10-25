"""Renders the poster SVGs to PNG with headless Chrome.

Run from the repository root:

    python tools/make_poster_pngs.py            # 1080x1350, exact
    python tools/make_poster_pngs.py --scale 2  # 2160x2700, retina

Chrome is used rather than a Python SVG library because the posters depend on
CSS font stacks (Georgia) and SVG filters, and a browser is the only renderer
that draws them the way the site does. Each SVG is wrapped in a tiny HTML page
sized exactly to the canvas, so no margin or scrollbar creeps into the output.

Also writes static/posters/yavaka-posters.zip so the whole set is one download.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "static" / "posters"
W, H = 1080, 1350

WINDOWS_BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

POSIX_BROWSERS = (
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def find_browser() -> str:
    for candidate in (*WINDOWS_BROWSERS, *POSIX_BROWSERS):
        if Path(candidate).exists():
            return candidate
    for name in ("chrome", "chromium", "google-chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit(
        "No Chrome, Chromium or Edge found. Install one, or open each SVG in a "
        "browser and export it by hand."
    )


PAGE = """<!doctype html>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: #fff; overflow: hidden; }}
  img {{ display: block; width: {w}px; height: {h}px; }}
</style>
<img src="{src}" width="{w}" height="{h}" alt="">
"""


def render(browser: str, svg: Path, target: Path, scale: int) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        page = Path(scratch) / "page.html"
        page.write_text(
            PAGE.format(w=W, h=H, src=svg.resolve().as_uri()), encoding="utf-8"
        )
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--allow-file-access-from-files",
            f"--force-device-scale-factor={scale}",
            f"--window-size={W},{H}",
            "--virtual-time-budget=3000",
            f"--screenshot={target.resolve()}",
            page.resolve().as_uri(),
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=120
        )
        if not target.exists() or target.stat().st_size == 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            tail = " / ".join(detail[-3:]) if detail else "no output"
            raise SystemExit(f"{svg.name}: Chrome produced no PNG ({tail})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scale",
        type=int,
        default=1,
        help="pixel multiplier: 1 gives 1080x1350, 2 gives 2160x2700 (default 1)",
    )
    parser.add_argument(
        "--drop-svg",
        action="store_true",
        help="delete the source SVGs once the PNGs are written",
    )
    args = parser.parse_args()
    if args.scale < 1:
        raise SystemExit("--scale must be 1 or more")

    svgs = sorted(OUT_DIR.glob("yavaka-*.svg"))
    if not svgs:
        raise SystemExit(
            "No poster SVGs found. Run tools/make_posters.py first."
        )

    browser = find_browser()
    print(f"rendering {len(svgs)} posters at {W * args.scale}x{H * args.scale}")

    for stale in OUT_DIR.glob("yavaka-*.png"):
        stale.unlink()

    for index, svg in enumerate(svgs, start=1):
        target = svg.with_suffix(".png")
        render(browser, svg, target, args.scale)
        print(f"  [{index:02d}/{len(svgs)}] {target.name} ({target.stat().st_size // 1024} KB)")

    if args.drop_svg:
        for svg in svgs:
            svg.unlink()

    bundle = OUT_DIR / "yavaka-posters.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for png in sorted(OUT_DIR.glob("yavaka-*.png")):
            archive.write(png, png.name)
    total = sum(p.stat().st_size for p in OUT_DIR.glob("yavaka-*.png"))
    print(f"{bundle.name}: {bundle.stat().st_size // 1024} KB zip, {total // 1024} KB of PNGs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
