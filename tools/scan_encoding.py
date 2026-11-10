"""Find mojibake (UTF-8 read as Windows-1252) in text assets."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Byte pairs that only appear when UTF-8 was decoded as cp1252/latin-1.
SIGNATURES = ("\u00e2\u0080", "\u00c3\u00a2", "\u00c2\u00a0", "\ufffd")
SUFFIXES = {".html", ".css", ".js", ".py", ".svg", ".json", ".webmanifest", ".md", ".txt"}


def iter_files():
    for base in ("templates", "static", "tools", "tests", "."):
        root = ROOT / base if base != "." else ROOT
        for path in root.glob("*.py") if base == "." else root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            normalised = str(path).replace("\\", "/")
            if "static/posters" in normalised or "node_modules" in normalised:
                continue
            yield path


def main():
    seen = set()
    total = 0
    for path in iter_files():
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            print(f"NOT-UTF8  {path.relative_to(ROOT)}  ({error})")
            continue
        hits = sum(text.count(sig) for sig in SIGNATURES)
        if hits:
            total += hits
            print(f"{hits:5}  {path.relative_to(ROOT)}")

    print(f"\ntotal suspect characters: {total}")


if __name__ == "__main__":
    sys.exit(main())
