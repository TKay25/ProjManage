"""Render real pages and scan them, plus the database, for mojibake."""

import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = tempfile.mkdtemp(prefix="yavaka-enc-")
os.environ.setdefault("DATABASE_FILE", str(pathlib.Path(tmp) / "enc.db"))
os.environ.setdefault("UPLOAD_DIR", str(pathlib.Path(tmp) / "uploads"))
os.environ.setdefault("SECRET_KEY", "encoding-check")
os.environ["SEED_DEMO"] = "true"

from app import create_app  # noqa: E402

SIGNATURES = ("â€", "Â·", "Â ", "\ufffd")

app = create_app()
client = app.test_client()

page = client.get("/login").get_data(as_text=True)
token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
client.post(
    "/login",
    data={"email": "client@yavaka.co.zw", "password": "YaVaKa2026!", "csrf_token": token},
)

targets = ["/", "/app", "/app/projects", "/app/money", "/app/documents", "/app/agreements",
           "/app/suppliers", "/app/whatsapp", "/app/settings", "/app/search?q=roof", "/login"]

print("--- served pages ---")
for path in targets:
    response = client.get(path)
    html = response.get_data(as_text=True)
    content_type = response.headers.get("Content-Type", "")
    charset = "charset" in content_type.lower()
    meta = bool(re.search(r'<meta\s+charset=', html, re.I))
    hits = {sig: html.count(sig) for sig in SIGNATURES if html.count(sig)}
    flag = "BAD " if hits else "ok  "
    print(f"{flag}{path:22} ct={content_type:34} charset={charset} meta={meta} {hits}")

print("\n--- database text ---")
with app.app_context():
    from db import query

    for table, column in [
        ("projects", "name"),
        ("projects", "description"),
        ("transactions", "description"),
        ("agreements", "title"),
        ("stages", "name"),
        ("users", "name"),
        ("suppliers", "name"),
    ]:
        rows = query(f"SELECT {column} AS value FROM {table}")
        bad = [r["value"] for r in rows if r["value"] and any(s in r["value"] for s in SIGNATURES)]
        print(f"{table}.{column:12} rows={len(rows):3} suspect={len(bad)}")
        for value in bad[:3]:
            print("     ", value[:80])
