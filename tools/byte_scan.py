"""Byte-level scan of served HTML for mojibake and replacement chars.

Written with ASCII-only source on purpose: no non-ASCII literals that could
themselves be corrupted while diagnosing.
"""

import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = tempfile.mkdtemp(prefix="yavaka-bytes-")
os.environ.setdefault("DATABASE_FILE", str(pathlib.Path(tmp) / "b.db"))
os.environ.setdefault("UPLOAD_DIR", str(pathlib.Path(tmp) / "up"))
os.environ.setdefault("SECRET_KEY", "byte-check")
os.environ["SEED_DEMO"] = "true"

from app import create_app  # noqa: E402

APP = create_app()
client = APP.test_client()

page = client.get("/login").get_data(as_text=True)
token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
client.post("/login", data={"email": "client@yavaka.co.zw", "password": "YaVaKa2026!", "csrf_token": token})

MARKERS = {
    "REPLACEMENT(efbfbd)": b"\xef\xbf\xbd",
    "MOJIBAKE_EMDASH(c3a2e282ac)": b"\xc3\xa2\xe2\x82\xac",
    "MOJIBAKE_MIDDOT(c382c2b7)": b"\xc3\x82\xc2\xb7",
    "EMDASH_UTF8(e28094)": b"\xe2\x80\x94",
}

for path in ["/", "/app", "/login"]:
    raw = client.get(path).get_data()
    print(f"\n=== {path} ({len(raw)} bytes) ===")
    for name, marker in MARKERS.items():
        count = raw.count(marker)
        print(f"  {name:34} {count}")
        if count:
            index = raw.find(marker)
            start = max(0, index - 60)
            window = raw[start:index + 60]
            print(f"      first at byte {index}")
            print(f"      {window!r}")
