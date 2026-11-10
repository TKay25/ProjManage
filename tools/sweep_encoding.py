"""Byte-level mojibake sweep across every tracked asset, posters included.

Byte patterns are used rather than decoded strings so the check cannot be
fooled by how this script itself was saved.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "instance", "uploads", ".pytest_cache"}
SUFFIXES = {
    ".html", ".css", ".js", ".py", ".svg", ".json", ".webmanifest", ".md",
    ".txt", ".png", ".webmanifest", ".xml", ".yml", ".yaml",
}

# Mojibake signatures as raw bytes.
PATTERNS = {
    "emdash  (a-hat + euro + quote)": b"\xc3\xa2\xe2\x82\xac",
    "middot  (A-hat + middle dot)": b"\xc3\x82\xc2\xb7",
    "check   (a-hat + oe + ellipsis)": b"\xc3\xa2\xc5\x93",
    "double  (A-hat + a-hat)": b"\xc3\x83\xc2\xa2",
    "replace (U+FFFD)": b"\xef\xbf\xbd",
}


def sweep():
    problems = 0
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() not in SUFFIXES:
            continue
        scanned += 1
        data = path.read_bytes()
        for name, pattern in PATTERNS.items():
            count = data.count(pattern)
            if count:
                problems += 1
                print(f"{count:5} x {name:34} {path.relative_to(ROOT)}")
    print(f"\nscanned {scanned} files, {problems} problem file/pattern pairs")
    return problems


if __name__ == "__main__":
    raise SystemExit(1 if sweep() else 0)
