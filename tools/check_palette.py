"""Ad-hoc smoke check for the command palette wiring. Not part of the suite."""

import re
import sys
import tempfile
from pathlib import Path

import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

tmp = tempfile.mkdtemp(prefix="yavaka-palette-")
os.environ["DATABASE_FILE"] = str(Path(tmp) / "check.db")
os.environ["UPLOAD_DIR"] = str(Path(tmp) / "uploads")
os.environ["SECRET_KEY"] = "palette-check"
os.environ["SEED_DEMO"] = "true"

from app import create_app

app = create_app()
client = app.test_client()

page = client.get("/login").get_data(as_text=True)
token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
login = client.post(
    "/login",
    data={"email": "client@yavaka.co.zw", "password": "YaVaKa2026!", "csrf_token": token},
)
print("login", login.status_code)

html = client.get("/app").get_data(as_text=True)
for needle in [
    "data-palette-open",
    "modal-palette",
    "palette-input",
    "palette.js",
    "palette.css",
    "Search or jump to",
]:
    print(f"  {needle:22} {'yes' if needle in html else 'MISSING'}")

result = client.get("/app/api/quick-find?q=gree")
print("quick-find gree", result.status_code, result.get_json())

empty = client.get("/app/api/quick-find?q=")
print("quick-find empty", empty.status_code, empty.get_json())

other = client.get("/app/api/quick-find?q=hidden vault")
print("unrelated term", other.status_code, other.get_json()["groups"])

anon = app.test_client().get("/app/api/quick-find?q=gree")
print("anonymous", anon.status_code)
