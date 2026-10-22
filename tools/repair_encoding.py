"""Repair UTF-8 text that was decoded as Windows-1252 and saved back.

Root cause: `Get-Content -Raw` in PowerShell 5.1 decodes a BOM-less file with
the system ANSI codepage, so every multi-byte UTF-8 character came back as
mojibake. `Set-Content -Encoding UTF8` then persisted that mojibake.

The source below is deliberately ASCII-only: every pattern is built from
explicit code points so this script cannot itself be corrupted.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "templates" / "landing.html"

# (corrupted cluster, intended character, name)
REPAIRS = [
    # 6-code-point cluster first: U+2705 U+201D (check mark + right quote)
    (
        "".join(map(chr, (0x00E2, 0x0153, 0x2026, 0x00E2, 0x20AC, 0x009D))),
        "".join(map(chr, (0x2705, 0x201D))),
        "check mark + right double quote",
    ),
    (
        "".join(map(chr, (0x00E2, 0x20AC, 0x201D))),
        chr(0x2014),
        "em dash",
    ),
    (
        "".join(map(chr, (0x00E2, 0x02C6, 0x2019))),
        chr(0x2212),
        "minus sign",
    ),
    (
        "".join(map(chr, (0x00E2, 0x20AC, 0x0153))),
        chr(0x201C),
        "left double quote",
    ),
    (
        "".join(map(chr, (0x00E2, 0x20AC, 0x00A6))),
        chr(0x2026),
        "ellipsis",
    ),
    (
        "".join(map(chr, (0x00C2, 0x00B7))),
        chr(0x00B7),
        "middle dot",
    ),
]


def main() -> int:
    if not TARGET.exists():
        print(f"missing {TARGET}")
        return 1

    text = TARGET.read_text(encoding="utf-8")
    total = 0
    for corrupted, intended, name in REPAIRS:
        count = text.count(corrupted)
        if count:
            text = text.replace(corrupted, intended)
            total += count
            print(f"  {count:3} x {name:34} -> U+{ord(intended[0]):04X}")

    if not total:
        print("nothing to repair")
        return 0

    TARGET.write_text(text, encoding="utf-8", newline="\n")

    # Verify the file no longer carries any mojibake lead characters.
    repaired = TARGET.read_text(encoding="utf-8")
    leads = [chr(0x00C2), chr(0x00C3), chr(0x00E2)]
    remaining = sum(repaired.count(lead) for lead in leads)
    print(f"\nrepaired {total} clusters; remaining mojibake leads: {remaining}")
    return 0 if remaining == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
