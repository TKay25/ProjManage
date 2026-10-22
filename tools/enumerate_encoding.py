"""Enumerate every non-ASCII codepoint in the templates and static assets.

The first scan used the latin-1 signature for a mojibake euro sign; the real
one is U+00E2 U+20AC, so this lists codepoints directly instead of guessing.
"""

import collections
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUFFIXES = {".html", ".css", ".js", ".py", ".svg", ".json", ".webmanifest", ".md"}

# Mojibake always starts with one of these lead characters.
LEADS = {"\u00c2", "\u00c3", "\u00e2", "\u00f0", "\ufffd"}


def files():
    for base in ("templates", "static", "tools", "tests"):
        for path in (ROOT / base).rglob("*"):
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                if "static/posters" in str(path).replace("\\", "/"):
                    continue
                yield path
    for path in ROOT.glob("*.py"):
        yield path
    for name in ("README.md",):
        candidate = ROOT / name
        if candidate.exists():
            yield candidate


for path in files():
    text = path.read_text(encoding="utf-8")
    suspects = collections.Counter(ch for ch in text if ch in LEADS)
    if not suspects:
        continue
    print(f"\n=== {path.relative_to(ROOT)} ===")
    for char, count in suspects.most_common():
        print(f"  U+{ord(char):04X}  x{count}")
    # Show each distinct corrupted cluster so the intended text is obvious.
    clusters = collections.Counter()
    index = 0
    while index < len(text):
        if text[index] in LEADS:
            end = index
            while end < len(text) and ord(text[end]) >= 0x80:
                end += 1
            clusters[text[index:end]] += 1
            index = end
        else:
            index += 1
    for cluster, count in clusters.most_common():
        codes = " ".join(f"U+{ord(c):04X}" for c in cluster)
        print(f"    x{count:<3} {cluster!r:14} {codes}")
