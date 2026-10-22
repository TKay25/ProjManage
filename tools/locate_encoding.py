"""Locate replacement characters and their byte context in the templates."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent / "templates"

for path in sorted(ROOT.rglob("*.html")):
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if "\ufffd" not in text:
        continue
    print(f"\n=== {path.relative_to(ROOT.parent)}  ({len(text)} chars, {len(raw)} bytes) ===")
    for index, char in enumerate(text):
        if char != "\ufffd":
            continue
        start = max(0, index - 45)
        end = min(len(text), index + 45)
        snippet = text[start:end].replace("\n", " ")
        # Byte offset of this character in the utf-8 encoding of the text.
        byte_offset = len(text[:index].encode("utf-8"))
        window = raw[max(0, byte_offset - 6): byte_offset + 8]
        print(f"  @{index:6}  ...{snippet}...")
        print(f"            bytes: {window.hex(' ')}")
