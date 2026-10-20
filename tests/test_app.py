"""Smoke tests for Vaka. Run with: python -m unittest discover -s tests -v"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use a throwaway database and upload folder before importing the app.
_TEMP_DIR = tempfile.mkdtemp(prefix="vaka-tests-")
os.environ["DATABASE_FILE"] = str(Path(_TEMP_DIR) / "test.db")
os.environ["UPLOAD_DIR"] = str(Path(_TEMP_DIR) / "uploads")
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only"
os.environ["SEED_DEMO"] = "true"

from app import create_app  # noqa: E402


class VakaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

    def setUp(self):
        self.client = self.app.test_client()

    def csrf(self):
        """Reads the CSRF token from the session, creating one if needed."""
        with self.client.session_transaction() as session:
            token = session.get("csrf")
        if token:
            return token

        self.client.get("/login")
        with self.client.session_transaction() as session:
            return session["csrf"]

    def login(self, email="client@vaka.co.zw", password="Vaka2026!"):
        token = self.csrf()
        return self.client.post(
            "/login",
            data={"email": email, "password": password, "csrf_token": token},
            follow_redirects=True,
        )


class PublicPages(VakaTestCase):
    def test_landing_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Your home in Zimbabwe", response.data)

    def test_public_pages_render(self):
        for path in ["/login", "/register", "/suppliers", "/offline", "/manifest.webmanifest"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_unknown_page_returns_404(self):
        self.assertEqual(self.client.get("/nope").status_code, 404)


class Authentication(VakaTestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_login_success(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Greendale Family Home", response.data)

    def test_login_rejects_bad_password(self):
        response = self.login(password="wrong-password")
        self.assertIn(b"do not match", response.data)

    def test_post_without_csrf_is_rejected(self):
        response = self.client.post("/login", data={"email": "a@b.co", "password": "x"})
        self.assertEqual(response.status_code, 400)

    def test_logout_clears_session(self):
        self.login()
        token = self.csrf()
        self.client.post("/logout", data={"csrf_token": token})
        self.assertEqual(self.client.get("/app").status_code, 302)


class ProjectAccess(VakaTestCase):
    def test_user_cannot_open_another_users_project(self):
        self.login()

        token = self.csrf()
        self.client.post(
            "/register",
            data={
                "name": "Outsider Account",
                "email": "outsider@example.com",
                "phone": "0779999999",
                "country": "South Africa",
                "role": "client",
                "password": "Outsider2026!",
                "terms": "yes",
                "csrf_token": token,
            },
        )

        from db import query

        with self.app.app_context():
            project = query("SELECT id FROM projects WHERE code = 'VK-2401'", one=True)

        self.assertEqual(self.client.get(f"/app/projects/{project['id']}").status_code, 404)

    def test_new_project_creates_all_stages(self):
        self.login()
        token = self.csrf()
        response = self.client.post(
            "/app/projects",
            data={
                "name": "Test Stand Build",
                "city": "Bulawayo",
                "suburb": "Hillside",
                "stand_number": "Stand 12",
                "budget": "50,000",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        from db import query
        from stages import STAGES

        with self.app.app_context():
            project = query("SELECT * FROM projects WHERE name = 'Test Stand Build'", one=True)
            stages = query("SELECT * FROM stages WHERE project_id = ?", (project["id"],))

        self.assertEqual(project["budget_cents"], 5_000_000)
        self.assertEqual(len(stages), len(STAGES))


class MoneyLedger(VakaTestCase):
    def project_id(self):
        from db import query

        with self.app.app_context():
            return query("SELECT id FROM projects WHERE code = 'VK-2401'", one=True)["id"]

    def totals(self, project_id):
        from queries import money_totals

        with self.app.app_context():
            return money_totals(project_id)

    def test_recording_an_expense_reduces_the_balance(self):
        self.login()
        project_id = self.project_id()
        before = self.totals(project_id)

        response = self.client.post(
            "/app/money",
            data={
                "csrf_token": self.csrf(),
                "project_id": project_id,
                "type": "EXPENSE",
                "amount": "250.00",
                "description": "Test delivery charge",
                "category": "transport",
                "method": "CASH",
                "occurred_at": "2026-10-01",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        after = self.totals(project_id)
        self.assertEqual(after["spent"] - before["spent"], 25_000)
        self.assertEqual(after["balance"], before["balance"] - 25_000)

    def test_zero_amount_is_rejected(self):
        self.login()
        project_id = self.project_id()
        before = self.totals(project_id)

        self.client.post(
            "/app/money",
            data={
                "csrf_token": self.csrf(),
                "project_id": project_id,
                "type": "EXPENSE",
                "amount": "0",
                "description": "Nothing",
            },
            follow_redirects=True,
        )

        self.assertEqual(self.totals(project_id)["spent"], before["spent"])

    def test_funding_increases_the_balance(self):
        self.login()
        project_id = self.project_id()
        before = self.totals(project_id)

        self.client.post(
            "/app/money",
            data={
                "csrf_token": self.csrf(),
                "project_id": project_id,
                "type": "FUNDING",
                "amount": "1000",
                "description": "Fourth tranche",
                "method": "BANK_TRANSFER",
                "occurred_at": "2026-10-05",
            },
            follow_redirects=True,
        )

        after = self.totals(project_id)
        self.assertEqual(after["funded"] - before["funded"], 100_000)


class WhatsAppAssistant(VakaTestCase):
    def test_webhook_verification(self):
        response = self.client.get(
            "/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=vaka-verify-token&hub.challenge=abc123"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"abc123")

    def test_webhook_rejects_wrong_token(self):
        response = self.client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=nope")
        self.assertEqual(response.status_code, 403)

    def test_balance_intent_returns_the_ledger(self):
        from whatsapp import handle_inbound

        with self.app.app_context():
            result = handle_inbound("263771234567", "BALANCE")

        self.assertEqual(result["intent"], "balance")
        self.assertIn("Available", result["reply"])

    def test_intent_detection(self):
        from whatsapp import detect_intent

        self.assertEqual(detect_intent("hello there")[0], "help")
        self.assertEqual(detect_intent("PAY 750")[0], "deposit")
        self.assertEqual(detect_intent("PAY 750")[1], 75_000)
        self.assertEqual(detect_intent("status please")[0], "status")


class StageProgress(VakaTestCase):
    def test_progress_is_weighted_and_capped(self):
        from stages import STAGES, project_progress

        complete = [{"key": stage["key"], "status": "complete"} for stage in STAGES]
        self.assertEqual(project_progress(complete), 100)

        half = [{"key": stage["key"], "status": "in_progress"} for stage in STAGES]
        self.assertEqual(project_progress(half), 50)

        self.assertEqual(project_progress([]), 0)


class MoneyFormatting(unittest.TestCase):
    def test_rounding_and_parsing(self):
        from money import format_money, parse_money_to_cents

        self.assertEqual(parse_money_to_cents("1,250.555"), 125_056)
        self.assertEqual(parse_money_to_cents("$85,000"), 8_500_000)
        self.assertEqual(parse_money_to_cents(""), 0)
        self.assertEqual(format_money(8_500_000), "$85,000.00")
        self.assertEqual(format_money(-25_000), "-$250.00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
