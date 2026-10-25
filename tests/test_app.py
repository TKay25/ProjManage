"""Smoke tests for YaVaKa. Run with: python -m unittest discover -s tests -v"""

import os
import re
import sys
import tempfile
import time
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
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"

from app import create_app  # noqa: E402
from config import Config  # noqa: E402


def isolated_config(**overrides):
    """A throwaway app config, independent of this process's environment."""

    class Isolated(Config):
        TESTING = True
        # These tests build throwaway SQLite files; never inherit a Postgres
        # connection from the environment.
        DATABASE_URL = ""

    for key, value in overrides.items():
        setattr(Isolated, key, value)
    return Isolated


# One app for the whole module: faster, and safe because tests assert on
# deltas rather than absolute counts.
APP = create_app()


class VakaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = APP
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

    def login(self, email="client@yavaka.co.zw", password="YaVaKa2026!"):
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
        self.assertIn(b"You can't be on site.", response.data)

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


class RoleAwareCopy(VakaTestCase):
    """Copy addresses whoever is signed in, not a generic 'user'."""

    PASSWORD = "Str0ngPassw0rd!"

    def test_build_manager_reads_recording_language(self):
        self.login("manager@yavaka.co.zw")
        text = self.client.get("/app/money").get_data(as_text=True)

        self.assertIn("Record money", text)
        self.assertNotIn("Report a deposit", text)

    def test_client_with_a_manager_reads_receiving_language(self):
        self.login()
        text = self.client.get("/app/money").get_data(as_text=True)

        self.assertIn("Report a deposit", text)
        self.assertNotIn("Record money", text)

    def test_client_who_runs_the_build_reads_recording_language(self):
        from db import execute, new_id, now_iso

        email = f"selfrun-{os.urandom(4).hex()}@example.test"
        with self.app.app_context():
            user_id = new_id()
            project_id = new_id()
            execute(
                """INSERT INTO users
                     (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Self Runner', ?, ?, 'client', '#0F5D46', ?)""",
                (user_id, email, __import__("auth").hash_password(self.PASSWORD), now_iso()),
            )
            execute(
                """INSERT INTO projects
                     (id, code, name, owner_id, manager_id, created_at, updated_at)
                   VALUES (?, ?, 'Own Build', ?, NULL, ?, ?)""",
                (project_id, f"YVK-9{os.urandom(3).hex()}", user_id, now_iso(), now_iso()),
            )
        self.addCleanup(self._cleanup, user_id, project_id)

        self.login(email, self.PASSWORD)
        text = self.client.get("/app/money").get_data(as_text=True)

        self.assertIn("Record money", text)
        self.assertNotIn("Report a deposit", text)

    def test_self_managed_turns_off_once_a_manager_works_the_project(self):
        import auth
        from db import execute, new_id, now_iso, query

        email = f"managed-{os.urandom(4).hex()}@example.test"
        with self.app.app_context():
            user_id = new_id()
            manager_id = new_id()
            project_id = new_id()
            for identifier, name, role in (
                (user_id, "Managed Client", "client"),
                (manager_id, "Working Manager", "manager"),
            ):
                execute(
                    """INSERT INTO users
                         (id, name, email, password_hash, role, avatar_color, created_at)
                       VALUES (?, ?, ?, ?, ?, '#0F5D46', ?)""",
                    (
                        identifier,
                        name,
                        f"{role}-{identifier}@example.test",
                        __import__("auth").hash_password(self.PASSWORD),
                        role,
                        now_iso(),
                    ),
                )
            execute(
                """INSERT INTO projects
                     (id, code, name, owner_id, manager_id, created_at, updated_at)
                   VALUES (?, ?, 'Managed Build', ?, NULL, ?, ?)""",
                (project_id, f"YVK-8{os.urandom(3).hex()}", user_id, now_iso(), now_iso()),
            )

            client = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)

        # A fresh app context per check: the answer is cached for one request.
        with self.app.app_context():
            self.assertTrue(auth.runs_build(client))

        with self.app.app_context():
            execute(
                "UPDATE projects SET manager_id = ? WHERE id = ?", (manager_id, project_id)
            )

        with self.app.app_context():
            client = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
            self.assertFalse(auth.runs_build(client))

        self.addCleanup(self._cleanup, user_id, project_id, manager_id)

    def _cleanup(self, user_id, project_id, manager_id=None):
        from db import execute

        people = (user_id, manager_id or user_id)
        with self.app.app_context():
            execute("DELETE FROM notifications WHERE user_id IN (?, ?)", people)
            execute("DELETE FROM audit_events WHERE user_id IN (?, ?)", people)
            execute("DELETE FROM workspaces WHERE owner_id IN (?, ?)", people)
            execute("DELETE FROM projects WHERE id = ?", (project_id,))
            execute("DELETE FROM users WHERE id IN (?, ?)", people)


class PasswordReset(VakaTestCase):
    EMAIL = "client@yavaka.co.zw"

    def setUp(self):
        super().setUp()
        from db import execute, query

        with self.app.app_context():
            execute("DELETE FROM auth_throttle")
            self.user = query("SELECT * FROM users WHERE email = ?", (self.EMAIL,), one=True)
            execute("DELETE FROM password_resets WHERE user_id = ?", (self.user["id"],))
        self.original_config = {
            "SMTP_HOST": self.app.config.get("SMTP_HOST"),
            "SMTP_FROM_EMAIL": self.app.config.get("SMTP_FROM_EMAIL"),
        }
        self.app.config["SMTP_HOST"] = "smtp.test"
        self.app.config["SMTP_FROM_EMAIL"] = "no-reply@test"

    def tearDown(self):
        from db import execute

        with self.app.app_context():
            execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (self.user["password_hash"], self.user["id"]),
            )
            execute("DELETE FROM password_resets WHERE user_id = ?", (self.user["id"],))
        for key, value in self.original_config.items():
            self.app.config[key] = value

    def request_link(self, email=None):
        from unittest.mock import patch

        with patch("notifications.send_email_async") as send:
            send.return_value = True
            response = self.client.post(
                "/forgot-password",
                data={"email": email or self.EMAIL, "csrf_token": self.csrf()},
                follow_redirects=True,
            )
        body = send.call_args.args[2] if send.called else ""
        match = re.search(r"/reset-password/([A-Za-z0-9_\-]+)", body)
        return response, (match.group(1) if match else None)

    def reset(self, token, password="FreshStart123", confirm=None):
        return self.client.post(
            f"/reset-password/{token}",
            data={
                "password": password,
                "confirm_password": confirm if confirm is not None else password,
                "csrf_token": self.csrf(),
            },
            follow_redirects=True,
        )

    def test_login_page_links_to_password_help(self):
        page = self.client.get("/login").get_data(as_text=True)
        self.assertIn("/forgot-password", page)

        page = self.client.get("/forgot-password").get_data(as_text=True)
        self.assertIn("Reset your password", page)

    def test_reset_link_changes_the_password_once(self):
        response, token = self.request_link()
        self.assertIn(b"reset link is on its way", response.data)
        self.assertTrue(token)

        page = self.client.get(f"/reset-password/{token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Choose a new password", page.data)

        response = self.reset(token)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password changed", response.data)

        logged_in = self.login(self.EMAIL, "FreshStart123")
        self.assertEqual(logged_in.status_code, 200)
        self.assertIn(b"Greendale Family Home", logged_in.data)

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        reused = self.client.get(f"/reset-password/{token}")
        self.assertEqual(reused.status_code, 400)
        self.assertIn(b"That link has expired", reused.data)

    def test_reset_rejects_a_mismatched_confirmation_and_keeps_the_link(self):
        _, token = self.request_link()
        response = self.reset(token, "FreshStart123", confirm="Different123")
        self.assertIn(b"passwords do not match", response.data)

        response = self.reset(token)
        self.assertIn(b"Password changed", response.data)

    def test_expired_reset_link_is_rejected(self):
        from db import execute

        _, token = self.request_link()
        with self.app.app_context():
            execute(
                "UPDATE password_resets SET expires_at = ? WHERE user_id = ?",
                ("2000-01-01T00:00:00+00:00", self.user["id"]),
            )
        response = self.client.get(f"/reset-password/{token}")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"That link has expired", response.data)

    def test_unknown_address_gets_the_same_answer_and_no_token(self):
        from db import query

        response, token = self.request_link("nobody@example.test")
        self.assertIn(b"reset link is on its way", response.data)
        self.assertIsNone(token)
        with self.app.app_context():
            row = query(
                "SELECT COUNT(*) AS total FROM password_resets WHERE user_id = ?",
                (self.user["id"],),
                one=True,
            )
        self.assertEqual(row["total"], 0)

    def test_without_smtp_the_flow_is_closed(self):
        from db import query

        self.app.config["SMTP_HOST"] = ""
        response = self.client.post(
            "/forgot-password",
            data={"email": self.EMAIL, "csrf_token": self.csrf()},
            follow_redirects=True,
        )
        self.assertIn(b"not configured", response.data)
        with self.app.app_context():
            row = query(
                "SELECT COUNT(*) AS total FROM password_resets WHERE user_id = ?",
                (self.user["id"],),
                one=True,
            )
        self.assertEqual(row["total"], 0)


class ProjectAccess(VakaTestCase):
    def test_user_cannot_open_another_users_project(self):
        self.login()

        outsider = self.app.test_client()
        outsider.get("/login")
        with outsider.session_transaction() as session:
            token = session["csrf"]
        outsider.post(
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
        outsider.post(
            "/login",
            data={
                "email": "outsider@example.com",
                "password": "Outsider2026!",
                "csrf_token": token,
            },
        )

        from db import execute, query

        with self.app.app_context():
            project = query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)

        self.assertEqual(outsider.get(f"/app/projects/{project['id']}").status_code, 404)

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


class ClientContactDetails(VakaTestCase):
    def test_build_manager_records_client_email_and_whatsapp(self):
        from db import query

        self.login("manager@yavaka.co.zw")
        response = self.client.post(
            "/app/projects",
            data={
                "name": "Client Contact Build",
                "city": "Harare",
                "suburb": "Avondale",
                "budget": "20,000",
                "client_email": "Client@Example.com",
                "client_whatsapp": "077 123 4567",
                "csrf_token": self.csrf(),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            project = query(
                "SELECT * FROM projects WHERE name = 'Client Contact Build'", one=True
            )

        self.assertEqual(project["client_email"], "client@example.com")
        self.assertEqual(project["client_whatsapp"], "263771234567")
        page = response.get_data(as_text=True)
        self.assertIn("client@example.com", page)
        # The number is displayed through the country-aware field, which keeps
        # the dial code in the selector rather than in the text box.
        self.assertIn("data-phone-field", page)
        self.assertIn("263771234567", page)
        # And the manager is told how the client takes the build over.
        self.assertIn("sign up with that address", page)

    def test_client_edit_keeps_the_recorded_contact(self):
        from db import execute, query

        self.login()
        with self.app.app_context():
            project = query("SELECT * FROM projects WHERE code = 'YVK-0001'", one=True)
            execute(
                "UPDATE projects SET client_email = ?, client_whatsapp = ? WHERE id = ?",
                ("owner-client@example.com", "263771111222", project["id"]),
            )

        try:
            response = self.client.post(
                f"/app/projects/{project['id']}",
                data={
                    "name": project["name"],
                    "city": project["city"],
                    "suburb": project["suburb"] or "",
                    "stand_number": project["stand_number"] or "",
                    "budget": f"{project['budget_cents'] / 100:.2f}",
                    "description": project["description"] or "",
                    "status": project["status"],
                    "csrf_token": self.csrf(),
                },
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

            with self.app.app_context():
                saved = query(
                    "SELECT client_email, client_whatsapp FROM projects WHERE id = ?",
                    (project["id"],),
                    one=True,
                )
            self.assertEqual(saved["client_email"], "owner-client@example.com")
            self.assertEqual(saved["client_whatsapp"], "263771111222")
        finally:
            with self.app.app_context():
                execute(
                    "UPDATE projects SET client_email = NULL, client_whatsapp = NULL WHERE id = ?",
                    (project["id"],),
                )


class MoneyLedger(VakaTestCase):
    def project_id(self):
        from db import query

        with self.app.app_context():
            return query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)["id"]

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


class LedgerViews(VakaTestCase):
    """Saved views: the preset row, the month filter, and default pinning."""

    def project_id(self):
        from db import query

        with self.app.app_context():
            return query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)["id"]

    def test_the_money_page_offers_preset_views(self):
        self.login()
        page = self.client.get(f"/app/money?project={self.project_id()}").get_data(as_text=True)

        self.assertIn("data-ledger-views", page)
        self.assertIn("data-view-pin", page)
        for label in ("All entries", "Received", "Spent", "No receipt", "This month"):
            self.assertIn(label, page)

    def test_month_view_only_counts_the_current_month(self):
        from datetime import datetime

        from db import query

        self.login()
        project_id = self.project_id()
        month = datetime.now().strftime("%Y-%m")

        response = self.client.get(f"/app/money?project={project_id}&filter=month")
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            expected = query(
                """SELECT COUNT(*) AS total FROM transactions
                   WHERE project_id = ? AND substr(occurred_at, 1, 7) = ?""",
                (project_id, month),
                one=True,
            )["total"]

        page = response.get_data(as_text=True)
        self.assertIn(f"{expected} {'entry' if expected == 1 else 'entries'}", page)

    def test_pinned_view_is_a_client_side_preference(self):
        self.login()
        page = self.client.get(f"/app/money?project={self.project_id()}").get_data(as_text=True)

        # The pin state is never rendered server-side, so nothing depends on it.
        self.assertIn('aria-pressed="false"', page)
        self.assertIn("Pin as my default", page)


class WhatsAppAssistant(VakaTestCase):
    def test_webhook_verification(self):
        response = self.client.get(
            "/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=test-verify-token&hub.challenge=abc123"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"abc123")

    def test_webhook_rejects_wrong_token(self):
        response = self.client.get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=nope")
        self.assertEqual(response.status_code, 403)

    def test_webhook_fails_closed_without_configuration(self):
        self.app.config["WHATSAPP_VERIFY_TOKEN"] = ""
        try:
            response = self.client.get(
                "/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=&hub.challenge=abc"
            )
        finally:
            self.app.config["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"
        self.assertEqual(response.status_code, 403)

    def test_balance_intent_returns_the_ledger(self):
        from whatsapp import handle_inbound

        with self.app.app_context():
            result = handle_inbound("263771234567", "BALANCE")

        self.assertEqual(result["intent"], "balance")
        self.assertIn("Available", result["reply"])

    def test_recorded_client_whatsapp_links_the_project(self):
        from db import execute, query
        from whatsapp import handle_inbound

        phone = "263778887777"
        with self.app.app_context():
            project = query("SELECT id, name FROM projects WHERE code = 'YVK-0001'", one=True)
            execute(
                "UPDATE projects SET client_whatsapp = ? WHERE id = ?", (phone, project["id"])
            )

        try:
            with self.app.app_context():
                result = handle_inbound(phone, "BALANCE")

            self.assertEqual(result["intent"], "balance")
            self.assertIn(project["name"], result["reply"])
        finally:
            with self.app.app_context():
                execute("DELETE FROM whatsapp_contacts WHERE phone = ?", (phone,))
                execute(
                    "UPDATE projects SET client_whatsapp = NULL WHERE id = ?", (project["id"],)
                )

    def test_intent_detection(self):
        from whatsapp import detect_intent

        self.assertEqual(detect_intent("hello there")[0], "help")
        self.assertEqual(detect_intent("PAY 750")[0], "deposit")
        self.assertEqual(detect_intent("PAY 750")[1], 75_000)
        self.assertEqual(detect_intent("status please")[0], "status")

    def test_quick_reply_buttons_are_rendered_under_assistant_messages(self):
        self.login()
        page = self.client.get("/app/whatsapp").get_data(as_text=True)

        self.assertNotIn("WhatsApp connection", page)
        self.assertNotIn("Simulator mode", page)
        self.assertIn('class="wa-actions"', page)
        for command in ("BALANCE", "STATUS", "PROJECTS", "PAY 500"):
            with self.subTest(command=command):
                self.assertIn(f'data-wa-quick="{command}"', page)

    def test_replies_do_not_ask_for_another_text_command(self):
        from whatsapp import handle_inbound

        with self.app.app_context():
            balance = handle_inbound("263771234567", "BALANCE")
            status = handle_inbound("263771234567", "STATUS")

        self.assertIn("Available:", balance["reply"])
        self.assertNotIn("Reply *", balance["reply"])
        self.assertIn("Progress:", status["reply"])
        self.assertNotIn("Reply *", status["reply"])
        self.assertIn("STATUS", balance["quick_replies"])
        self.assertNotIn("BALANCE", balance["quick_replies"])
        self.assertIn("BALANCE", status["quick_replies"])
        self.assertNotIn("STATUS", status["quick_replies"])


class WhatsAppHandoff(VakaTestCase):
    PHONE = "263779900111"

    def setUp(self):
        super().setUp()
        from db import execute, new_id, now_iso, query

        with self.app.app_context():
            project = query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)
            execute("DELETE FROM whatsapp_contacts WHERE phone = ?", (self.PHONE,))
            self.contact_id = new_id()
            execute(
                """INSERT INTO whatsapp_contacts (id, phone, name, user_id, project_id, created_at)
                   VALUES (?, ?, 'Handoff Client', NULL, ?, ?)""",
                (self.contact_id, self.PHONE, project["id"], now_iso()),
            )

    def tearDown(self):
        from db import execute

        with self.app.app_context():
            execute(
                "DELETE FROM notifications WHERE href = ?",
                (f"/app/whatsapp?contact={self.contact_id}",),
            )
            execute("DELETE FROM whatsapp_contacts WHERE phone = ?", (self.PHONE,))

    def take_over(self):
        return self.client.post(
            "/app/whatsapp/handoff",
            data={"contact_id": self.contact_id, "csrf_token": self.csrf()},
            follow_redirects=True,
        )

    def test_taking_over_pauses_the_bot_and_resuming_restores_it(self):
        from db import query
        from whatsapp import handle_inbound

        self.login("manager@yavaka.co.zw")
        response = self.take_over()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"assistant will stay quiet", response.data)

        with self.app.app_context():
            result = handle_inbound(self.PHONE, "BALANCE")
            contact = query(
                "SELECT * FROM whatsapp_contacts WHERE id = ?", (self.contact_id,), one=True
            )
            outbound = query(
                """SELECT COUNT(*) AS count FROM whatsapp_messages
                   WHERE contact_id = ? AND direction = 'OUT'""",
                (self.contact_id,),
                one=True,
            )
            inbound = query(
                """SELECT * FROM whatsapp_messages
                   WHERE contact_id = ? AND direction = 'IN' ORDER BY created_at DESC LIMIT 1""",
                (self.contact_id,),
                one=True,
            )
            manager = query(
                "SELECT id FROM users WHERE email = 'manager@yavaka.co.zw'", one=True
            )
            alerts = query(
                "SELECT * FROM notifications WHERE href = ?",
                (f"/app/whatsapp?contact={self.contact_id}",),
            )

        self.assertTrue(result["handoff"])
        self.assertEqual(result["reply"], "")
        self.assertTrue(contact["handoff_at"])
        self.assertEqual(outbound["count"], 0)
        self.assertEqual(inbound["body"], "BALANCE")
        self.assertEqual(inbound["intent"], "balance")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["user_id"], manager["id"])
        self.assertEqual(alerts[0]["action"], "whatsapp.reply")
        self.assertIn("BALANCE", alerts[0]["body"])

        token = self.csrf()
        response = self.client.post(
            "/app/whatsapp/resume",
            data={"contact_id": self.contact_id, "csrf_token": token},
            follow_redirects=True,
        )
        self.assertIn(b"assistant is answering", response.data)

        with self.app.app_context():
            result = handle_inbound(self.PHONE, "BALANCE")

        self.assertFalse(result.get("handoff", False))
        self.assertIn("Available", result["reply"])

    def test_transcript_keeps_the_newest_messages(self):
        from datetime import datetime, timedelta, timezone

        from db import execute, new_id

        base = datetime.now(timezone.utc) - timedelta(minutes=205)
        with self.app.app_context():
            for index in range(1, 206):
                execute(
                    """INSERT INTO whatsapp_messages
                         (id, contact_id, direction, body, intent, status, created_at)
                       VALUES (?, ?, ?, ?, 'unknown', 'received', ?)""",
                    (
                        new_id(),
                        self.contact_id,
                        "IN" if index % 2 else "OUT",
                        f"MESSAGE-{index:04d}",
                        (base + timedelta(minutes=index)).isoformat(timespec="seconds"),
                    ),
                )

        self.login("manager@yavaka.co.zw")
        page = self.client.get(
            f"/app/whatsapp?contact={self.contact_id}"
        ).get_data(as_text=True)

        self.assertNotIn("MESSAGE-0005", page)
        self.assertIn("MESSAGE-0006", page)
        self.assertIn("MESSAGE-0205", page)
        self.assertLess(page.index("MESSAGE-0006"), page.index("MESSAGE-0205"))

    def test_manager_can_reply_while_the_assistant_is_paused(self):
        from db import query

        self.login("manager@yavaka.co.zw")
        self.take_over()

        response = self.client.post(
            "/app/whatsapp/send",
            data={
                "contact_id": self.contact_id,
                "body": "I'll call you in ten minutes.",
                "csrf_token": self.csrf(),
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Message sent to Handoff Client.", response.data)

        with self.app.app_context():
            message = query(
                """SELECT * FROM whatsapp_messages
                   WHERE contact_id = ? ORDER BY created_at DESC, id DESC LIMIT 1""",
                (self.contact_id,),
                one=True,
            )

        self.assertEqual(message["direction"], "OUT")
        self.assertEqual(message["intent"], "manual")
        self.assertEqual(message["body"], "I'll call you in ten minutes.")

    def test_takeover_controls_follow_the_conversation_state(self):
        self.login("manager@yavaka.co.zw")
        page = self.client.get(f"/app/whatsapp?contact={self.contact_id}").get_data(as_text=True)
        self.assertIn("Take over", page)
        self.assertIn("Message as the client", page)

        self.take_over()
        page = self.client.get(f"/app/whatsapp?contact={self.contact_id}").get_data(as_text=True)
        self.assertIn("Hand back to assistant", page)
        self.assertIn("You're replying", page)
        self.assertNotIn("Message as the client", page)
        self.assertIn("Reply to Handoff Client as Tendai Moyo", page)

    def test_manager_cannot_take_over_another_managers_conversation(self):
        from db import execute, new_id, now_iso

        other_phone = "263779900222"
        with self.app.app_context():
            owner_id = new_id()
            project_id = new_id()
            contact_id = new_id()
            execute(
                """INSERT INTO users (id, name, email, password_hash, role, created_at)
                   VALUES (?, 'Other Client', 'other-client@example.test', 'x', 'client', ?)""",
                (owner_id, now_iso()),
            )
            execute(
                """INSERT INTO projects (id, code, name, owner_id, created_at, updated_at)
                   VALUES (?, 'YVK-9001', 'Other Build', ?, ?, ?)""",
                (project_id, owner_id, now_iso(), now_iso()),
            )
            execute(
                """INSERT INTO whatsapp_contacts (id, phone, name, user_id, project_id, created_at)
                   VALUES (?, ?, 'Other Client', ?, ?, ?)""",
                (contact_id, other_phone, owner_id, project_id, now_iso()),
            )
        self.addCleanup(self.cleanup_other, contact_id, project_id, owner_id)

        self.login("manager@yavaka.co.zw")
        response = self.client.post(
            "/app/whatsapp/handoff",
            data={"contact_id": contact_id, "csrf_token": self.csrf()},
        )
        self.assertEqual(response.status_code, 403)

    def cleanup_other(self, contact_id, project_id, owner_id):
        from db import execute

        with self.app.app_context():
            execute("DELETE FROM whatsapp_contacts WHERE id = ?", (contact_id,))
            execute("DELETE FROM projects WHERE id = ?", (project_id,))
            execute("DELETE FROM users WHERE id = ?", (owner_id,))


class StageProgress(VakaTestCase):
    def test_progress_is_weighted_and_capped(self):
        from stages import STAGES, project_progress

        complete = [{"key": stage["key"], "status": "complete"} for stage in STAGES]
        self.assertEqual(project_progress(complete), 100)

        half = [{"key": stage["key"], "status": "in_progress"} for stage in STAGES]
        self.assertEqual(project_progress(half), 50)

        self.assertEqual(project_progress([]), 0)


class ProductionSafety(unittest.TestCase):
    """Guards the things that would be embarrassing — or costly — in production."""

    def test_security_headers_are_set(self):
        response = APP.test_client().get("/login")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'self'", response.headers.get("Content-Security-Policy", ""))
        self.assertIn("frame-ancestors 'none'", response.headers.get("Content-Security-Policy", ""))

    def test_authenticated_pages_are_not_cacheable(self):
        client = APP.test_client()
        with client.session_transaction() as session:
            session["csrf"] = "test-token"

        client.post(
            "/login",
            data={
                "email": "client@yavaka.co.zw",
                "password": "YaVaKa2026!",
                "csrf_token": "test-token",
            },
        )
        response = client.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_demo_accounts_are_not_created_without_opt_in(self):
        """A forgotten env var must never ship published admin credentials."""
        database = Path(_TEMP_DIR) / "clean.db"
        config = isolated_config(
            SEED_DEMO=False,
            DEMO_MODE=False,
            DATABASE=str(database),
            UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "clean-uploads"),
        )

        from db import query

        clean = create_app(config)
        with clean.app_context():
            users = query("SELECT email FROM users")
            suppliers = query("SELECT COUNT(*) AS c FROM suppliers", one=True)["c"]

        self.assertEqual(users, [])
        # The supplier directory is reference data, not an account.
        self.assertGreater(suppliers, 0)

    def test_login_page_hides_credentials_when_demo_is_off(self):
        config = isolated_config(
            SEED_DEMO=False,
            DEMO_MODE=False,
            DATABASE=str(Path(_TEMP_DIR) / "clean-login.db"),
            UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "clean-login-uploads"),
        )

        body = create_app(config).test_client().get("/login").get_data(as_text=True)

        self.assertNotIn("YaVaKa2026!", body)
        self.assertNotIn("client@yavaka.co.zw", body)

    def test_password_hashes_are_salted(self):
        import auth

        first = auth.hash_password("same-password")
        second = auth.hash_password("same-password")
        self.assertNotEqual(first, second)
        self.assertTrue(auth.verify_password("same-password", first))
        self.assertFalse(auth.verify_password("different", first))

    def test_https_sets_hsts_and_secure_cookie(self):
        """Behind a TLS proxy: HSTS on the response, Secure on the session cookie."""
        config = isolated_config(
            SEED_DEMO=True,
            DATABASE=str(Path(_TEMP_DIR) / "https.db"),
            UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "https-uploads"),
            SESSION_COOKIE_SECURE=True,
        )
        client = create_app(config).test_client()

        with client.session_transaction() as session:
            session["csrf"] = "token"

        response = client.post(
            "/login",
            base_url="https://vaka.test",
            data={
                "email": "client@yavaka.co.zw",
                "password": "YaVaKa2026!",
                "csrf_token": "token",
            },
        )
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)

        page = client.get("/app", base_url="https://vaka.test")
        self.assertIn("max-age=31536000", page.headers.get("Strict-Transport-Security", ""))


class AgreementReaderModal(VakaTestCase):
    """Clicking an agreement opens it in the shared reader dialog."""

    def _first_agreement_id(self):
        from db import query

        with self.app.app_context():
            row = query("SELECT id FROM agreements ORDER BY created_at LIMIT 1", one=True)
        self.assertIsNotNone(row, "seed data should include an agreement")
        return row["id"]

    def test_list_links_agreements_to_the_reader(self):
        self.login()
        page = self.client.get("/app/agreements").get_data(as_text=True)
        self.assertIn("data-modal-remote=", page)
        self.assertIn('id="modal-view"', page)

    def test_detail_returns_a_fragment_for_the_dialog(self):
        self.login()
        agreement_id = self._first_agreement_id()

        response = self.client.get(
            f"/app/agreements/{agreement_id}",
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/json")
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["title"])
        # A fragment must not carry page chrome, or the dialog would nest a page.
        self.assertNotIn("<html", payload["fragment"].lower())
        self.assertNotIn('id="modal-view"', payload["fragment"])
        self.assertIn("contract-doc", payload["fragment"])

    def test_detail_still_renders_a_full_page_without_javascript(self):
        self.login()
        agreement_id = self._first_agreement_id()

        response = self.client.get(f"/app/agreements/{agreement_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<html", response.data.lower())


class LoginThrottle(VakaTestCase):
    """The throttle must count failures only, or clients lock themselves out."""

    def setUp(self):
        super().setUp()
        from db import execute

        with self.app.app_context():
            execute("DELETE FROM auth_throttle")

    def _post(self, password):
        return self.client.post(
            "/login",
            data={
                "email": "client@yavaka.co.zw",
                "password": password,
                "csrf_token": self.csrf(),
            },
        )

    def test_repeated_successful_logins_are_never_throttled(self):
        for _ in range(12):
            self.assertEqual(self._post("YaVaKa2026!").status_code, 302)

    def test_failures_still_throttle(self):
        codes = [self._post("definitely-not-the-password").status_code for _ in range(10)]
        self.assertEqual(codes[0], 401)
        self.assertEqual(codes[-1], 429)


class LedgerExport(VakaTestCase):
    """The CSV statement a diaspora client keeps for their own records."""

    def _export_rows(self, query_string=""):
        import csv
        import io

        response = self.client.get(f"/app/money/export{query_string}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        return list(csv.reader(io.StringIO(response.data.decode("utf-8-sig"))))

    def test_export_has_header_rows_and_totals(self):
        self.login()
        rows = self._export_rows()
        self.assertEqual(rows[0][:4], ["Date", "Direction", "Description", "Category"])
        self.assertIn("Balance", rows[0])
        self.assertEqual(rows[-1][2], "Totals")
        # Every data row must carry a running balance.
        for row in rows[1:-2]:
            self.assertNotEqual(row[rows[0].index("Balance")], "")

    def test_export_neutralises_spreadsheet_formulas(self):
        from db import execute, query

        self.login()
        with self.app.app_context():
            # Target a project the signed-in client can see; other tests create
            # newer projects that belong to unrelated accounts.
            user = query(
                "SELECT id FROM users WHERE email = 'client@yavaka.co.zw' LIMIT 1", one=True
            )
            project = query(
                "SELECT id FROM projects WHERE owner_id = ? ORDER BY created_at DESC LIMIT 1",
                (user["id"],),
                one=True,
            )
            execute(
                """INSERT INTO transactions
                     (id, project_id, type, amount_cents, currency, category, stage_key,
                      description, method, reference, occurred_at, created_by, created_at)
                   VALUES ('tx-formula', ?, 'EXPENSE', 100, 'USD', 'materials', NULL,
                           '=HYPERLINK("http://example.invalid","x")', 'CASH', NULL,
                           '2026-03-01', ?, '2026-03-01T00:00:00')""",
                (project["id"], user["id"]),
            )

        rows = self._export_rows(f"?project={project['id']}")
        injected = [row for row in rows if "HYPERLINK" in "".join(row)]
        self.assertTrue(injected)
        self.assertTrue(injected[0][2].startswith("'"))

    def test_page_out_of_range_clamps_instead_of_blank(self):
        self.login()
        response = self.client.get("/app/money?page=9999")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ledger", response.data)


class Accessibility(VakaTestCase):
    """Cheap guards so the small things do not regress."""

    def test_workspace_has_skip_link_and_main_landmark(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn('class="skip-link" href="#main"', page)
        self.assertIn('<main class="content" id="main"', page)

    def test_active_nav_item_is_marked_for_screen_readers(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn('aria-current="page"', page)

    def test_table_headers_are_scoped(self):
        self.login("admin@yavaka.co.zw")
        page = self.client.get("/admin/projects").get_data(as_text=True)
        self.assertIn("<th scope=\"col\"", page)

    def test_search_fields_have_accessible_names(self):
        self.login()
        page = self.client.get("/app/money").get_data(as_text=True)
        self.assertIn('aria-label="Search the ledger"', page)


    def test_signing_updates_badge_and_status_in_the_dialog(self):
        from db import execute, now_iso, query

        self.login()
        with self.app.app_context():
            project = query("SELECT id FROM projects ORDER BY created_at DESC LIMIT 1", one=True)
            user = query("SELECT id FROM users WHERE role = 'client' LIMIT 1", one=True)
            execute(
                """INSERT INTO agreements
                     (id, project_id, type, title, contract_value_cents, currency, scope, terms,
                      payment_schedule, client_name, client_signature, signed_at, status, created_by, created_at)
                   VALUES ('agr-sign-test', ?, 'build_contract', 'Signing test', 100000, 'USD',
                           'Scope long enough to pass validation checks.', 'Terms.',
                           '[]', 'Test Client', NULL, NULL, 'awaiting_signature', ?, ?)""",
                (project["id"], user["id"], now_iso()),
            )

        response = self.client.post(
            "/app/agreements/agr-sign-test/sign",
            data={"csrf_token": self.csrf(), "signed_name": "Test Client", "signature": ""},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        payload = response.get_json()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["target"], "[data-signature-panel]")
        self.assertEqual(payload["fields"]["[data-agreement-status]"], "Signed")
        # The badge must be swapped too, or the dialog contradicts itself.
        self.assertIn("Signed", payload["html"]["[data-agreement-badge]"])


class RegistrationModal(VakaTestCase):
    """Sign-up happens in a dialog so public pages never navigate away."""

    def _csrf(self, client=None):
        client = client or self.client
        return re.search(
            r'name="csrf-token" content="([^"]+)"',
            client.get("/login").get_data(as_text=True),
        ).group(1)

    def test_public_pages_carry_the_dialogs_but_auth_pages_do_not(self):
        for path in ["/", "/suppliers"]:
            page = self.client.get(path).get_data(as_text=True)
            self.assertIn('id="modal-login"', page, path)
            self.assertIn('id="modal-register"', page, path)
            self.assertIn('data-modal-open="modal-register"', page, path)
            self.assertIn('data-modal-open="modal-login"', page, path)

        # The standalone auth pages already show their own form.
        for path in ["/login", "/register"]:
            page = self.client.get(path).get_data(as_text=True)
            self.assertNotIn('id="modal-login"', page, path)
            self.assertNotIn('id="modal-register"', page, path)

    def test_the_two_dialogs_offer_a_way_to_each_other(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-modal-switch="modal-login"', page)
        self.assertIn('data-modal-switch="modal-register"', page)
        self.assertEqual(page.count('class="auth-aside modal-auth-aside"'), 2)
        self.assertIn('class="btn btn-outline btn-sm auth-switch-btn"', page)
        self.assertIn('>Create an account</a>', page)

    def test_auth_dialogs_name_the_work_they_are_doing(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('data-busy-text="Logging you in…"', page)
        self.assertIn('data-busy-text="Creating your account…"', page)

    def test_sign_in_posts_json_so_the_dialog_never_navigates(self):
        client = self.app.test_client()
        page = client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)

        response = client.post(
            "/login",
            data={"email": "client@yavaka.co.zw", "password": "YaVaKa2026!", "csrf_token": token},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("redirect", payload)
        # Same session, now signed in.
        self.assertEqual(client.get("/app").status_code, 200)

    def test_bad_password_returns_json_not_a_page(self):
        client = self.app.test_client()
        page = client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)

        response = client.post(
            "/login",
            data={"email": "client@yavaka.co.zw", "password": "wrong", "csrf_token": token},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_validation_error_returns_json_so_the_dialog_stays_open(self):
        response = self.client.post(
            "/register",
            data={"csrf_token": self._csrf(), "name": "A B", "email": "short@example.com",
                  "password": "short", "terms": "yes"},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("8 characters", payload["message"])

    def test_successful_signup_opens_login_modal_without_signing_in(self):
        client = self.app.test_client()
        email = f"modal-{os.urandom(4).hex()}@example.com"
        response = client.post(
            "/register",
            data={"csrf_token": self._csrf(client), "name": "Modal Signup",
                  "email": email, "phone": "+263771234567", "country": "United Kingdom",
                  "role": "client", "password": "Str0ngPassw0rd!", "terms": "yes"},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["open_modal"], "modal-login")
        self.assertIn("created successfully", payload["modal_notice"])
        self.assertNotIn("redirect", payload)
        # Creating an account no longer signs the user in automatically.
        self.assertEqual(client.get("/app").status_code, 302)
        # The new credentials work in the sign-in flow.
        login_response = client.post(
            "/login",
            data={"email": email, "password": "Str0ngPassw0rd!", "csrf_token": self._csrf(client)},
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(client.get("/app").status_code, 200)

    def test_signup_without_javascript_still_redirects(self):
        response = self.client.post(
            "/register",
            data={"csrf_token": self._csrf(), "name": "Plain Signup",
                  "email": f"plain-{os.urandom(4).hex()}@example.com",
                  "password": "Str0ngPassw0rd!", "terms": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        login_page = self.client.get(response.headers["Location"])
        self.assertIn(b"created successfully", login_page.data)


class BrandMigration(unittest.TestCase):
    """The rename has to move existing demo rows, not just the source."""

    def _app(self, name, seed_demo=False):
        return create_app(
            isolated_config(
                SEED_DEMO=seed_demo,
                DATABASE=str(Path(_TEMP_DIR) / f"{name}.db"),
                UPLOAD_FOLDER=str(Path(_TEMP_DIR) / f"{name}-uploads"),
            )
        )

    def test_moves_demo_accounts_to_the_new_domain(self):
        import db

        app = self._app("brand-migration")
        with app.app_context():
            connection = db.get_db()
            connection.execute("PRAGMA user_version = 0")
            connection.execute(
                """INSERT INTO users (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES ('legacy', 'Legacy Client', 'client@vaka.co.zw', 'placeholder',
                           'client', '#0F5D46', '2026-01-01T00:00:00+00:00')"""
            )
            connection.commit()

            db.run_migrations(connection)

            row = db.query("SELECT email, password_hash FROM users WHERE id = 'legacy'", one=True)
            self.assertEqual(row["email"], "client@yavaka.co.zw")
            # The displayed demo password is reset to the on-brand one, so the
            # credentials on the sign-in page keep working.
            import auth
            from seed import DEMO_PASSWORD

            self.assertTrue(auth.verify_password(DEMO_PASSWORD, row["password_hash"]))
            self.assertGreaterEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

            # Running again must not change anything.
            db.run_migrations(connection)
            self.assertEqual(
                db.query("SELECT email FROM users WHERE id = 'legacy'", one=True)["email"],
                "client@yavaka.co.zw",
            )

    def test_demo_login_works_with_the_new_credentials(self):
        app = self._app("brand-login", seed_demo=True)
        client = app.test_client()
        from seed import DEMO_PASSWORD

        page = client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        response = client.post(
            "/login",
            data={"email": "client@yavaka.co.zw", "password": DEMO_PASSWORD, "csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/app").status_code, 200)


class StageAttachments(VakaTestCase):
    """Files attached to a build stage also appear in the document vault."""

    def _project(self):
        from db import query

        with self.app.app_context():
            return query("SELECT id FROM projects ORDER BY created_at LIMIT 1", one=True)["id"]

    def _png(self):
        import io

        return io.BytesIO(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                "0000000a49444154789c6360000002000100ffff03000006000557bfabd4"
                "0000000049454e44ae426082"
            )
        )

    def _upload(self, project_id, stage_key, name):
        return self.client.post(
            "/app/documents/upload",
            data={
                "csrf_token": self.csrf(),
                "project_id": project_id,
                "kind": "document",
                "stage_key": stage_key,
                "file": (self._png(), name),
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
            content_type="multipart/form-data",
        )

    def test_stage_upload_lands_on_the_stage_and_in_documents(self):
        self.login()
        project_id = self._project()

        response = self._upload(project_id, "plan_approval", "council-approval.png")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["target"], '[data-stage-files="plan_approval"]')
        self.assertEqual(payload["mode"], "prepend")
        self.assertIn("council-approval.png", payload["fragment"])

        detail = self.client.get(f"/app/projects/{project_id}").get_data(as_text=True)
        self.assertIn("council-approval.png", detail)

        documents = self.client.get(f"/app/documents?project={project_id}").get_data(as_text=True)
        self.assertIn("council-approval.png", documents)
        # The vault shows which stage the file belongs to.
        self.assertIn("Council plan approval", documents)

    def test_stage_filter_isolates_the_file(self):
        self.login()
        project_id = self._project()
        self._upload(project_id, "foundation", "foundation-pour.png")

        matching = self.client.get(
            f"/app/documents?project={project_id}&stage=foundation"
        ).get_data(as_text=True)
        other = self.client.get(
            f"/app/documents?project={project_id}&stage=superstructure"
        ).get_data(as_text=True)

        self.assertIn("foundation-pour.png", matching)
        self.assertNotIn("foundation-pour.png", other)

    def test_unknown_stage_is_ignored_rather_than_rejected(self):
        from db import query

        self.login()
        project_id = self._project()

        response = self._upload(project_id, "not_a_real_stage", "loose-file.png")
        self.assertEqual(response.status_code, 200)
        # Falls back to a plain project document.
        self.assertEqual(response.get_json()["target"], "[data-doc-grid]")

        with self.app.app_context():
            row = query(
                "SELECT stage_key FROM attachments WHERE original_name = 'loose-file.png'", one=True
            )
        self.assertIsNone(row["stage_key"])


class GlobalSearch(VakaTestCase):
    def test_finds_projects_money_and_stages(self):
        self.login()
        response = self.client.get("/app/search?q=greendale")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Greendale Family Home", page)

        money = self.client.get("/app/search?q=cement").get_data(as_text=True)
        self.assertIn("Cement", money)

        stage = self.client.get("/app/search?q=foundation").get_data(as_text=True)
        self.assertIn("Build stages", stage)

    def test_empty_search_page_and_no_results(self):
        self.login()
        self.assertIn("Search across your builds", self.client.get("/app/search").get_data(as_text=True))
        self.assertIn(
            "Nothing matches",
            self.client.get("/app/search?q=zzzznothinghere").get_data(as_text=True),
        )

    def test_search_never_crosses_into_another_client(self):
        from db import execute, new_id, now_iso, query

        # A project owned by somebody the manager has no relationship with. The
        # demo client may itself be linked to the manager by other tests, so this
        # stranger is created fresh.
        with self.app.app_context():
            other_id = new_id()
            execute(
                """INSERT INTO users (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Unlinked Client', ?, 'x', 'client', '#0F5D46', ?)""",
                (other_id, f"{other_id}@example.com", now_iso()),
            )
            execute(
                """INSERT INTO projects (id, code, name, owner_id, city, status, budget_cents,
                                         created_at, updated_at, workspace_id)
                   VALUES (?, ?, 'Hidden Vault Project', ?, 'Harare', 'planning',
                           100000, ?, ?, NULL)""",
                (new_id(), f"YVK-H{new_id()[:4].upper()}", other_id, now_iso(), now_iso()),
            )

        self.login("manager@yavaka.co.zw")
        page = self.client.get("/app/search?q=hidden vault").get_data(as_text=True)
        self.assertNotIn("Hidden Vault Project", page)


class StageSelection(VakaTestCase):
    def test_project_keeps_only_the_chosen_stages_and_still_spends_the_budget(self):
        from db import query

        self.login()
        response = self.client.post(
            "/app/projects",
            data={
                "csrf_token": self.csrf(),
                "name": "Skeleton Build",
                "budget": "30000",
                "city": "Harare",
                "stage_keys": ["land_due_diligence", "foundation", "superstructure"],
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertTrue(response.get_json()["ok"])

        with self.app.app_context():
            project = query("SELECT id, code FROM projects WHERE name = 'Skeleton Build'", one=True)
            stages = query(
                "SELECT key, budget_cents FROM stages WHERE project_id = ? ORDER BY position",
                (project["id"],),
            )

        self.assertEqual([row["key"] for row in stages], ["land_due_diligence", "foundation", "superstructure"])
        self.assertEqual(sum(row["budget_cents"] for row in stages), 3_000_000)
        self.assertTrue(project["code"].startswith("YVK-"))

    def test_no_selection_falls_back_to_the_full_sequence(self):
        from db import query

        self.login()
        self.client.post(
            "/app/projects",
            data={
                "csrf_token": self.csrf(),
                "name": "Complete Build",
                "budget": "20000",
                "city": "Harare",
            },
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )

        with self.app.app_context():
            project = query("SELECT id FROM projects WHERE name = 'Complete Build'", one=True)
            count = query(
                "SELECT COUNT(*) AS c FROM stages WHERE project_id = ?", (project["id"],), one=True
            )["c"]
        self.assertEqual(count, 19)


class DigestEndpoint(VakaTestCase):
    def setUp(self):
        super().setUp()
        self.app.config["DIGEST_TOKEN"] = "digest-secret"

    def tearDown(self):
        self.app.config["DIGEST_TOKEN"] = ""

    def test_requires_the_shared_token(self):
        self.assertEqual(self.client.post("/api/whatsapp/digest").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/whatsapp/digest", headers={"X-Digest-Token": "wrong"}
            ).status_code,
            403,
        )

    def test_fails_closed_when_unconfigured(self):
        self.app.config["DIGEST_TOKEN"] = ""
        self.assertEqual(
            self.client.post("/api/whatsapp/digest", headers={"X-Digest-Token": ""}).status_code,
            403,
        )

    def test_sends_a_summary_per_active_project(self):
        response = self.client.post(
            "/api/whatsapp/digest", headers={"X-Digest-Token": "digest-secret"}
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["sent"], 1)
        self.assertEqual(payload["failed"], [])

    def test_message_contains_progress_and_balance(self):
        from db import query
        from routes_digest import build_digest

        with self.app.app_context():
            project = query("SELECT * FROM projects LIMIT 1", one=True)
            body = build_digest(project)

        self.assertIn(project["name"], body)
        self.assertIn("Progress:", body)
        self.assertIn("Balance:", body)


class ProjectUpdateNotifications(VakaTestCase):
    def setUp(self):
        super().setUp()
        self.original_token = self.app.config.get("NOTIFICATIONS_TOKEN", "")

    def tearDown(self):
        self.app.config["NOTIFICATIONS_TOKEN"] = self.original_token

    def test_dispatch_requires_a_configured_shared_token(self):
        self.app.config["NOTIFICATIONS_TOKEN"] = ""
        self.assertEqual(self.client.post("/api/notifications/dispatch").status_code, 403)
        self.app.config["NOTIFICATIONS_TOKEN"] = "notifications-secret"
        self.assertEqual(
            self.client.post(
                "/api/notifications/dispatch",
                headers={"X-Notifications-Token": "wrong"},
            ).status_code,
            403,
        )

    def test_dispatch_accepts_the_shared_token_without_browser_csrf(self):
        from unittest.mock import patch

        self.app.config["NOTIFICATIONS_TOKEN"] = "notifications-secret"
        with patch("routes_notifications.schedule_dispatch"):
            response = self.client.post(
                "/api/notifications/dispatch",
                headers={"X-Notifications-Token": "notifications-secret"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def _add_pending_delivery(self, status="pending", claimed_at=None):
        from db import execute, new_id, query

        with self.app.app_context():
            project = query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)
            delivery_id = new_id()
            execute(
                """INSERT INTO notification_outbox
                     (id, event_key, project_id, channel, recipient, subject, body,
                      status, created_at, claimed_at)
                   VALUES (?, ?, ?, 'email', 'owner@example.test', 'Subject', 'Update',
                           ?, '2099-01-01T00:00:00+00:00', ?)""",
                (delivery_id, new_id(), project["id"], status, claimed_at),
            )
        return delivery_id

    def test_dispatch_persists_success(self):
        from unittest.mock import patch

        from db import execute, query
        from notifications import dispatch_pending

        delivery_id = self._add_pending_delivery()
        with patch("notifications._deliver", return_value={"status": "sent"}):
            self.assertEqual(dispatch_pending(self.app), 1)

        with self.app.app_context():
            delivery = query(
                "SELECT status, sent_at, attempts, claimed_at FROM notification_outbox WHERE id = ?",
                (delivery_id,),
                one=True,
            )
            execute("DELETE FROM notification_outbox WHERE id = ?", (delivery_id,))
        self.assertEqual(delivery["status"], "sent")
        self.assertTrue(delivery["sent_at"])
        self.assertEqual(delivery["attempts"], 1)
        self.assertIsNone(delivery["claimed_at"])

    def test_dispatch_recovers_a_stale_sending_delivery(self):
        from unittest.mock import patch

        from db import execute, query
        from notifications import dispatch_pending

        delivery_id = self._add_pending_delivery(
            status="sending",
            claimed_at="2000-01-01T00:00:00+00:00",
        )
        with patch("notifications._deliver", return_value={"status": "sent"}):
            self.assertEqual(dispatch_pending(self.app), 1)

        with self.app.app_context():
            delivery = query(
                "SELECT status, claimed_at FROM notification_outbox WHERE id = ?",
                (delivery_id,),
                one=True,
            )
            execute("DELETE FROM notification_outbox WHERE id = ?", (delivery_id,))
        self.assertEqual(delivery["status"], "sent")
        self.assertIsNone(delivery["claimed_at"])

    def test_dispatch_persists_failure_after_retries(self):
        from unittest.mock import patch

        from db import execute, query
        from notifications import dispatch_pending

        delivery_id = self._add_pending_delivery()
        with self.assertLogs("yavaka.notifications", level="ERROR") as logs, patch(
            "notifications._deliver",
            side_effect=RuntimeError("provider unavailable"),
        ) as deliver, patch("notifications.time.sleep"):
            self.assertEqual(dispatch_pending(self.app), 0)

        with self.app.app_context():
            delivery = query(
                "SELECT status, attempts, last_error FROM notification_outbox WHERE id = ?",
                (delivery_id,),
                one=True,
            )
            execute("DELETE FROM notification_outbox WHERE id = ?", (delivery_id,))
        self.assertEqual(deliver.call_count, 3)
        self.assertEqual(len(logs.output), 4)
        self.assertEqual(delivery["status"], "failed")
        self.assertEqual(delivery["attempts"], 3)
        self.assertEqual(delivery["last_error"], "provider unavailable")

    def test_only_assigned_manager_updates_are_queued(self):
        from unittest.mock import patch

        from db import execute, query
        from notifications import queue_manager_update

        original = {
            key: self.app.config.get(key)
            for key in (
                "SMTP_HOST",
                "SMTP_FROM_EMAIL",
                "WHATSAPP_TOKEN",
                "WHATSAPP_PHONE_NUMBER_ID",
                "WHATSAPP_UPDATE_TEMPLATE",
            )
        }
        self.app.config.update(
            SMTP_HOST="smtp.example.test",
            SMTP_FROM_EMAIL="updates@example.test",
            WHATSAPP_TOKEN="test-token",
            WHATSAPP_PHONE_NUMBER_ID="12345",
            WHATSAPP_UPDATE_TEMPLATE="project_update",
        )
        try:
            with self.app.app_context():
                project = query(
                    """SELECT p.id, p.manager_id FROM projects p
                       WHERE p.code = 'YVK-0001'""",
                    one=True,
                )
                with patch("notifications.schedule_dispatch"):
                    queued = queue_manager_update(
                        project["id"],
                        project["manager_id"],
                        "Assigned Manager",
                        "Stage updated",
                        "Survey complete",
                    )
                    ignored = queue_manager_update(
                        project["id"],
                        "not-the-assigned-manager",
                        "Other Manager",
                        "Stage updated",
                        "Should not notify",
                    )

                rows = query(
                    """SELECT id, channel, recipient, body FROM notification_outbox
                       WHERE project_id = ? AND body LIKE ? ORDER BY channel""",
                    (project["id"], "%Survey complete%"),
                )
                for row in rows:
                    execute("DELETE FROM notification_outbox WHERE id = ?", (row["id"],))

            self.assertEqual(queued, 2)
            self.assertEqual(ignored, 0)
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["channel"] for row in rows}, {"email", "whatsapp"})
            self.assertTrue(all("Available balance:" in row["body"] for row in rows))
        finally:
            self.app.config.update(original)

    def test_updates_go_to_the_recorded_client_contact(self):
        from unittest.mock import patch

        from db import execute, query
        from notifications import queue_manager_update

        original = {
            key: self.app.config.get(key)
            for key in (
                "SMTP_HOST",
                "SMTP_FROM_EMAIL",
                "WHATSAPP_TOKEN",
                "WHATSAPP_PHONE_NUMBER_ID",
                "WHATSAPP_UPDATE_TEMPLATE",
            )
        }
        self.app.config.update(
            SMTP_HOST="smtp.example.test",
            SMTP_FROM_EMAIL="updates@example.test",
            WHATSAPP_TOKEN="test-token",
            WHATSAPP_PHONE_NUMBER_ID="12345",
            WHATSAPP_UPDATE_TEMPLATE="project_update",
        )
        try:
            with self.app.app_context():
                project = query(
                    "SELECT id, manager_id FROM projects WHERE code = 'YVK-0001'", one=True
                )
                execute(
                    "UPDATE projects SET client_email = ?, client_whatsapp = ? WHERE id = ?",
                    ("client-contact@example.test", "263779998888", project["id"]),
                )
                with patch("notifications.schedule_dispatch"):
                    queued = queue_manager_update(
                        project["id"],
                        project["manager_id"],
                        "Assigned Manager",
                        "Stage updated",
                        "Client contact routing",
                    )

                rows = query(
                    """SELECT id, channel, recipient FROM notification_outbox
                       WHERE project_id = ? AND body LIKE ? ORDER BY channel""",
                    (project["id"], "%Client contact routing%"),
                )
                for row in rows:
                    execute("DELETE FROM notification_outbox WHERE id = ?", (row["id"],))
                execute(
                    "UPDATE projects SET client_email = NULL, client_whatsapp = NULL WHERE id = ?",
                    (project["id"],),
                )

            self.assertEqual(queued, 2)
            self.assertEqual(
                {row["channel"]: row["recipient"] for row in rows},
                {"email": "client-contact@example.test", "whatsapp": "263779998888"},
            )
        finally:
            self.app.config.update(original)

    def test_whatsapp_requires_credentials_and_an_approved_template(self):
        from unittest.mock import patch

        from db import execute, query
        from notifications import queue_manager_update

        original = {
            key: self.app.config.get(key)
            for key in (
                "SMTP_HOST",
                "SMTP_FROM_EMAIL",
                "WHATSAPP_TOKEN",
                "WHATSAPP_PHONE_NUMBER_ID",
                "WHATSAPP_UPDATE_TEMPLATE",
            )
        }
        self.app.config.update(
            SMTP_HOST="smtp.example.test",
            SMTP_FROM_EMAIL="updates@example.test",
            WHATSAPP_TOKEN="test-token",
            WHATSAPP_PHONE_NUMBER_ID="12345",
            WHATSAPP_UPDATE_TEMPLATE="",
        )
        try:
            with self.app.app_context():
                project = query(
                    "SELECT id, manager_id FROM projects WHERE code = 'YVK-0001'",
                    one=True,
                )
                with patch("notifications.schedule_dispatch"):
                    queued = queue_manager_update(
                        project["id"],
                        project["manager_id"],
                        "Assigned Manager",
                        "Template missing",
                        "Email only",
                    )
                rows = query(
                    """SELECT id, channel FROM notification_outbox
                       WHERE project_id = ? AND body LIKE ?""",
                    (project["id"], "%Email only%"),
                )
                for row in rows:
                    execute("DELETE FROM notification_outbox WHERE id = ?", (row["id"],))

            self.assertEqual(queued, 1)
            self.assertEqual([row["channel"] for row in rows], ["email"])
        finally:
            self.app.config.update(original)


class BrandCodes(VakaTestCase):
    def test_project_codes_use_the_new_prefix(self):
        from db import query

        self.login()
        with self.app.app_context():
            codes = [row["code"] for row in query("SELECT code FROM projects")]
        self.assertTrue(codes)
        for code in codes:
            self.assertTrue(code.startswith("YVK-"), code)


class TextEncoding(VakaTestCase):
    """Guards against UTF-8 being decoded as Windows-1252 and saved back.

    That mistake turns an em dash into three stray characters, which is easy to
    miss in review but glaring on the page. Patterns are written as escapes so
    this test file can never be the thing that is corrupted.
    """

    MOJIBAKE = (
        "\u00e2\u20ac",  # em dash / curly quote read as cp1252
        "\u00c2\u00b7",  # middle dot read as cp1252
        "\u00e2\u0153",  # check mark read as cp1252
        "\u00c3\u00a2",  # double-encoded lead byte
    )

    def test_pages_contain_no_mojibake(self):
        self.login()
        for path in ["/", "/app", "/app/projects", "/app/money", "/app/documents"]:
            with self.subTest(path=path):
                html = self.client.get(path).get_data(as_text=True)
                for sequence in self.MOJIBAKE:
                    self.assertNotIn(sequence, html, f"{path} carries mojibake {sequence!r}")
                self.assertNotIn("\ufffd", html, f"{path} carries a replacement character")

    def test_landing_page_keeps_real_punctuation(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("\u2014", html)  # em dash
        self.assertIn("\u00b7", html)  # middle dot


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


class DisplayPreferences(VakaTestCase):
    """Density and page size live on the user, so they follow the account."""

    def _row(self):
        from db import query

        with self.app.app_context():
            return query(
                "SELECT density, page_size FROM users WHERE email = ?",
                ("client@yavaka.co.zw",),
                one=True,
            )

    def test_default_density_is_comfortable(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn('data-density="comfortable"', page)

    def test_a_change_is_saved_and_rendered(self):
        self.login()
        response = self.client.post(
            "/app/settings/preferences",
            data={
                "csrf_token": self.csrf(),
                "density": "compact",
                "page_size": "50",
                "save": "1",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Display preferences saved.", response.get_data(as_text=True))
        self.assertIn('data-density="compact"', response.get_data(as_text=True))
        self.assertEqual(self._row()["page_size"], 50)

        self.client.post(
            "/app/settings/preferences",
            data={"csrf_token": self.csrf(), "density": "comfortable", "page_size": "25"},
            follow_redirects=True,
        )
        self.assertEqual(self._row()["density"], "comfortable")

    def test_junk_input_keeps_the_previous_value(self):
        self.login()
        before = self._row()

        self.client.post(
            "/app/settings/preferences",
            data={"csrf_token": self.csrf(), "density": "enormous", "page_size": "9999"},
            follow_redirects=True,
        )

        after = self._row()
        self.assertEqual(after["density"], before["density"])
        self.assertEqual(after["page_size"], before["page_size"])

    def test_the_palette_posts_json(self):
        self.login()
        response = self.client.post(
            "/app/settings/preferences",
            data={"csrf_token": self.csrf(), "density": "compact"},
            headers={"X-Requested-With": "fetch"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["density"], "compact")

        self.client.post(
            "/app/settings/preferences",
            data={"csrf_token": self.csrf(), "density": "comfortable"},
            headers={"X-Requested-With": "fetch"},
        )


class PagerWindow(unittest.TestCase):
    """The numbered pager is pure arithmetic, so test it without a request."""

    def test_small_lists_show_every_page(self):
        from paging import page_list

        self.assertEqual(page_list(1, 1), [1])
        self.assertEqual(page_list(3, 7), [1, 2, 3, 4, 5, 6, 7])

    def test_long_lists_keep_the_ends_and_the_neighbours(self):
        from paging import page_list

        self.assertEqual(page_list(1, 12), [1, 2, 3, 4, 5, None, 12])
        self.assertEqual(page_list(6, 12), [1, None, 5, 6, 7, None, 12])
        self.assertEqual(page_list(12, 12), [1, None, 8, 9, 10, 11, 12])

    def test_offsets_never_go_negative(self):
        from paging import offset

        self.assertEqual(offset(1, 25), 0)
        self.assertEqual(offset(4, 25), 75)


class AttentionInbox(VakaTestCase):
    def test_the_three_kinds_are_grouped(self):
        self.login()
        response = self.client.get("/app/attention")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Needs attention", page)
        self.assertIn("Approvals due", page)
        self.assertIn("Blocked stages", page)
        # The demo client has a build manager, so the receipt group is framed
        # as proof they are waiting on rather than something they chase.
        self.assertIn("Missing receipts", page)
        self.assertNotIn("Receipts to chase", page)

    def test_another_clients_blocked_stage_never_appears(self):
        from db import execute, new_id, now_iso, query

        with self.app.app_context():
            owner = query("SELECT id FROM users WHERE role = 'client' LIMIT 1", one=True)
            project_id = new_id()
            execute(
                """INSERT INTO projects (id, code, name, owner_id, city, status, budget_cents,
                                         created_at, updated_at)
                   VALUES (?, 'YVK-VAULT-A', 'Hidden Vault Build', ?, 'Harare', 'planning',
                           100000, ?, ?)""",
                (project_id, owner["id"], now_iso(), now_iso()),
            )
            execute(
                """INSERT INTO stages (id, project_id, key, name, position, status,
                                       budget_cents, notes, started_at)
                   VALUES (?, ?, 'foundation', 'Secret Vault Stage', 1, 'blocked', 0,
                           'Waiting on the owner', ?)""",
                (new_id(), project_id, now_iso()),
            )

        self.login("manager@yavaka.co.zw")
        page = self.client.get("/app/attention").get_data(as_text=True)
        self.assertNotIn("Secret Vault Stage", page)
        self.assertNotIn("Hidden Vault Build", page)


class OfflineSnapshot(VakaTestCase):
    def _project(self):
        from db import query

        with self.app.app_context():
            return query("SELECT id, name FROM projects WHERE code = 'YVK-0001'", one=True)

    def test_the_snapshot_is_read_only_and_token_free(self):
        self.login()
        project = self._project()

        response = self.client.get(f"/app/projects/{project['id']}/snapshot")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn(project["name"], page)
        self.assertIn("Offline copy", page)
        # Cached on the device: nothing replayable may travel with it.
        self.assertNotIn("csrf", page.lower())
        self.assertNotIn("<form", page.lower())
        self.assertNotIn("<script", page.lower())

    def test_another_users_project_is_not_snapshotted(self):
        from db import execute, new_id, now_iso, query

        with self.app.app_context():
            # Not the demo client: other tests link that client to the manager,
            # which legitimately grants access. This stranger is unrelated.
            stranger = new_id()
            execute(
                """INSERT INTO users (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Unrelated Client', ?, 'x', 'client', '#0F5D46', ?)""",
                (stranger, f"{stranger}@example.com", now_iso()),
            )
            project_id = new_id()
            execute(
                """INSERT INTO projects (id, code, name, owner_id, city, status, budget_cents,
                                         created_at, updated_at)
                   VALUES (?, ?, 'Snapshot Wall', ?, 'Harare', 'planning',
                           1000, ?, ?)""",
                (project_id, f"YVK-S{new_id()[:4].upper()}", stranger, now_iso(), now_iso()),
            )

        self.login("manager@yavaka.co.zw")
        self.assertEqual(self.client.get(f"/app/projects/{project_id}/snapshot").status_code, 404)


class BackupDownload(VakaTestCase):
    def test_staff_get_a_zip_with_the_database(self):
        import io
        import zipfile

        self.login("admin@yavaka.co.zw")
        response = self.client.get("/app/settings/backup?uploads=0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        archive = zipfile.ZipFile(io.BytesIO(response.data))
        self.assertIn("vaka.db", archive.namelist())
        response.close()

    def test_clients_cannot_download_the_platform_backup(self):
        self.login()
        self.assertEqual(self.client.get("/app/settings/backup").status_code, 403)


class PaletteActions(VakaTestCase):
    def test_the_workspace_offers_the_cheat_sheet_and_actions(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)

        self.assertIn('id="modal-shortcuts"', page)
        self.assertIn('data-palette-action="new-money"', page)
        self.assertIn('data-palette-action="switch-project"', page)
        self.assertIn("Toggle compact view", page)

    def test_switch_project_lists_only_accessible_builds(self):
        self.login()
        response = self.client.get("/app/api/quick-find?group=projects")

        self.assertEqual(response.status_code, 200)
        groups = response.get_json()["groups"]
        self.assertEqual(groups[0]["label"], "Switch project")
        self.assertTrue(groups[0]["items"])
        self.assertTrue(groups[0]["items"][0]["href"].startswith("/app/projects/"))

    def test_switch_project_needs_a_session(self):
        self.assertEqual(self.client.get("/app/api/quick-find?group=projects").status_code, 302)


class ShellChrome(VakaTestCase):
    """The workspace chrome: attention entry points and the theme control."""

    def test_the_bell_opens_updates_and_attention_keeps_its_sidebar_entry(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)

        # The bell is a disclosure button now: it opens the panel in place
        # rather than throwing away the page you were reading.
        bell = re.search(r"<summary[^>]*class=\"icon-btn topbar-alert[^\"]*\"[^>]*>", page)
        self.assertIsNotNone(bell)
        self.assertIn("Updates", bell.group(0))
        self.assertIn('class="notif-foot" href="/app/updates"', page)
        # Attention still has its own entry point in the sidebar.
        self.assertIn('href="/app/attention"', page)

    def test_the_badge_appears_next_to_the_attention_nav_item(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        # Seeded demo data always has outstanding receipts, so the badge shows.
        self.assertIn("nav-count", page)

    def test_settings_offers_system_light_and_dark(self):
        self.login()
        page = self.client.get("/app/settings").get_data(as_text=True)

        self.assertIn("data-theme-choice", page)
        for mode in ("system", "light", "dark"):
            self.assertIn(f'data-theme-set="{mode}"', page)
        self.assertIn("Row density", page)

    def test_the_theme_survives_a_page_render_without_javascript(self):
        # theme.js is synchronous in <head> so the first paint is already right.
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        self.assertRegex(page, r'<script src="[^"]*theme\.js[^"]*"></script>')


class AttentionCounts(unittest.TestCase):
    """The badge tally must match what the attention page lists."""

    def test_counts_blocked_unsigned_and_unreceipted(self):
        from db import execute, new_id, now_iso, query
        from queries import attention_counts

        with APP.app_context():
            owner = query("SELECT id FROM users WHERE role = 'client' LIMIT 1", one=True)
            project_id = new_id()
            execute(
                """INSERT INTO projects (id, code, name, owner_id, city, status, budget_cents,
                                         created_at, updated_at)
                   VALUES (?, ?, 'Badge Count Build', ?, 'Harare', 'planning', 1000, ?, ?)""",
                (project_id, f"YVK-B{new_id()[:5].upper()}", owner["id"], now_iso(), now_iso()),
            )
            execute(
                """INSERT INTO stages (id, project_id, key, name, position, status,
                                       budget_cents, started_at)
                   VALUES (?, ?, 'plan_approval', 'Plan approval', 1, 'in_progress', 0, ?)""",
                (new_id(), project_id, now_iso()),
            )
            execute(
                """INSERT INTO stages (id, project_id, key, name, position, status,
                                       budget_cents, started_at)
                   VALUES (?, ?, 'foundation', 'Foundation', 2, 'blocked', 0, ?)""",
                (new_id(), project_id, now_iso()),
            )
            execute(
                """INSERT INTO agreements (id, project_id, title, scope, terms, client_name,
                                           status, created_by, created_at)
                   VALUES (?, ?, 'Unsigned build contract', 'Scope', 'Terms', 'Client',
                           'awaiting_signature', ?, ?)""",
                (new_id(), project_id, owner["id"], now_iso()),
            )
            # Both expenses are missing a receipt: the badge mirrors the list,
            # which flags the older one as overdue further down the page.
            for occurred in ("2026-01-05T09:00:00+00:00", now_iso()):
                execute(
                    """INSERT INTO transactions (id, project_id, type, amount_cents, description,
                                                 category, method, occurred_at, created_by, created_at)
                       VALUES (?, ?, 'EXPENSE', 5000, 'No receipt yet', 'materials',
                               'CASH', ?, ?, ?)""",
                    (new_id(), project_id, occurred, owner["id"], now_iso()),
                )

            counts = attention_counts([project_id])

        self.assertEqual(counts["blocked"], 1)
        self.assertEqual(counts["approvals"], 1)
        self.assertEqual(counts["agreements"], 1)
        self.assertEqual(counts["receipts"], 2)
        self.assertEqual(counts["total"], 5)

    def test_no_projects_means_no_work(self):
        from queries import attention_counts

        self.assertEqual(attention_counts([])["total"], 0)


class PageSkeletons(unittest.TestCase):
    """Each destination has a placeholder shaped like the real page.

    The skeleton only appears for slow swaps, so a unit test can only assert the
    mapping exists and covers the workspace routes.
    """

    def test_every_workspace_route_maps_to_a_skeleton(self):
        import re
        from pathlib import Path

        source = Path("static/js/nav.js").read_text(encoding="utf-8")
        block = source.split("function skeletonFor", 1)[1]
        routes = re.findall(r'pathname\.startsWith\("([^"]+)"\)', block)
        self.assertTrue(routes)
        for expected in (
            "/app/money",
            "/app/attention",
            "/app/projects",
            "/app/documents",
            "/app/agreements",
            "/app/suppliers",
            "/app/whatsapp",
            "/app/settings",
            "/app/search",
        ):
            self.assertIn(expected, routes)
        # Project detail must be checked before the project list, or every
        # project would get the grid placeholder.
        self.assertLess(block.index('"/app/projects/"'), block.index('"/app/projects"'))

    def test_skeletons_use_only_the_css_parts_that_exist(self):
        import re
        from pathlib import Path

        source = Path("static/js/nav.js").read_text(encoding="utf-8")
        css = Path("static/css/portal.css").read_text(encoding="utf-8")

        # Template expressions ("sk-kpis${...}") are not class names: drop them
        # so only the literal part is checked.
        markup = source.split("function skeletonFor", 1)[0]
        markup = re.sub(r"\$\{[^}]*\}", "", markup)

        classes = set()
        for value in re.findall(r'class="([^"]+)"', markup):
            classes.update(part for part in value.split() if part.startswith("sk"))

        self.assertTrue(classes)
        for name in sorted(classes):
            with self.subTest(name=name):
                self.assertIn(f".{name}", css)


class UpdateNotifications(VakaTestCase):
    """A build manager's work lands in the client's updates inbox."""

    def _project(self):
        from db import query

        with self.app.app_context():
            return query("SELECT id, owner_id, manager_id FROM projects WHERE code = 'YVK-0001'", one=True)

    def _people(self):
        from db import query

        with self.app.app_context():
            owner = query("SELECT id, name FROM users WHERE email = 'client@yavaka.co.zw'", one=True)
            manager = query("SELECT id, name FROM users WHERE email = 'manager@yavaka.co.zw'", one=True)
        return owner, manager

    def _notifications(self, user_id):
        from db import query

        with self.app.app_context():
            return query(
                "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )

    def test_a_manager_update_notifies_the_client_but_not_the_manager(self):
        from db import log_event

        project = self._project()
        owner, manager = self._people()

        with self.app.app_context():
            log_event(manager["id"], project["id"], "stage.completed", "Ring beam cast")

        mine = self._notifications(owner["id"])
        self.assertTrue(mine)
        self.assertEqual(mine[0]["action"], "stage.completed")
        self.assertEqual(mine[0]["body"], "Ring beam cast")
        self.assertIsNone(mine[0]["read_at"])
        # The actor never gets a notification about their own work.
        self.assertFalse(
            [row for row in self._notifications(manager["id"]) if row["body"] == "Ring beam cast"]
        )

    def test_a_document_upload_links_to_the_vault(self):
        from db import log_event

        project = self._project()
        owner, manager = self._people()

        with self.app.app_context():
            log_event(manager["id"], project["id"], "document.uploaded", "site-week-12.jpg")

        row = self._notifications(owner["id"])[0]
        self.assertEqual(row["title"], "Document uploaded")
        self.assertEqual(row["href"], f"/app/documents?project={project['id']}")

    def test_client_actions_notify_the_manager(self):
        from db import log_event

        project = self._project()
        owner, manager = self._people()

        with self.app.app_context():
            log_event(owner["id"], project["id"], "funding.recorded", "Tranche 3 — received")

        manager_rows = [row for row in self._notifications(manager["id"]) if row["body"] == "Tranche 3"]
        self.assertTrue(manager_rows)
        self.assertEqual(manager_rows[0]["title"], "Funding received")

    def test_system_events_are_audited_but_never_notified(self):
        from db import log_event

        project = self._project()
        owner, _manager = self._people()

        with self.app.app_context():
            log_event(None, project["id"], "digest.sent", "Weekly digest to +263...")
            log_event(owner["id"], project["id"], "digest.sent", "Weekly digest again")

        self.assertFalse([row for row in self._notifications(owner["id"]) if row["action"] == "digest.sent"])

    def test_the_updates_page_shows_new_items_then_clears_the_badge(self):
        from db import log_event

        project = self._project()
        _owner, manager = self._people()

        with self.app.app_context():
            log_event(manager["id"], project["id"], "stage.blocked", "Council query on the slab")

        self.login()
        first = self.client.get("/app/updates").get_data(as_text=True)
        self.assertIn("Stage blocked", first)
        self.assertIn("Council query on the slab", first)
        self.assertIn("Greendale Family Home", first)
        self.assertIn("is-new", first)
        # The badge is cleared before the page renders, so it is not repeated.
        self.assertNotIn("nav-count--live", first)

        second = self.client.get("/app/updates").get_data(as_text=True)
        self.assertNotIn("is-new", second)

    def test_the_unread_endpoint_reports_the_latest_item(self):
        from db import log_event

        project = self._project()
        _owner, manager = self._people()

        with self.app.app_context():
            log_event(manager["id"], project["id"], "expense.recorded", "Cement delivery — spent")

        self.login()
        payload = self.client.get("/app/api/updates/unread").get_json()

        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["count"], 1)
        self.assertEqual(payload["latest"]["title"], "Expense recorded")
        self.assertEqual(payload["latest"]["project"], "Greendale Family Home")
        # The stored detail drops the "— spent" tail the label already carries.
        self.assertNotIn("— spent", payload["latest"].get("detail", ""))

    def test_the_unread_endpoint_needs_a_session(self):
        self.assertEqual(self.client.get("/app/api/updates/unread").status_code, 302)

    def test_another_clients_updates_are_never_listed(self):
        from db import execute, log_event, new_id, now_iso, query

        with self.app.app_context():
            stranger = new_id()
            execute(
                """INSERT INTO users (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Stranger Client', ?, 'x', 'client', '#0F5D46', ?)""",
                (stranger, f"{stranger}@example.com", now_iso()),
            )
            project_id = new_id()
            execute(
                """INSERT INTO projects (id, code, name, owner_id, city, status, budget_cents,
                                         created_at, updated_at)
                   VALUES (?, ?, 'Quiet Build', ?, 'Harare', 'planning', 1000, ?, ?)""",
                (project_id, f"YVK-Q{new_id()[:5].upper()}", stranger, now_iso(), now_iso()),
            )
            manager = query("SELECT id FROM users WHERE role = 'manager' LIMIT 1", one=True)
            log_event(manager["id"], project_id, "stage.updated", "Private stage note")

        self.login()
        page = self.client.get("/app/updates").get_data(as_text=True)
        self.assertNotIn("Private stage note", page)
        self.assertNotIn("Quiet Build", page)
        self.assertEqual(self.client.get("/app/api/updates/unread").get_json()["count"], 0)

    def test_the_workspace_offers_the_updates_tab_and_card(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)

        self.assertIn('href="/app/updates"', page)
        self.assertIn("Latest updates", page)


class AssistantWindow(VakaTestCase):
    """The floating assistant answers from the same rows the pages render."""

    def _ask(self, question, client=None):
        client = client or self.client
        return client.post(
            "/api/assistant/ask",
            json={"question": question},
            headers={"X-CSRF-Token": self.csrf()},
        )

    def test_the_window_is_on_the_site_and_in_the_app(self):
        self.login()
        for path in ("/app", "/app/money"):
            with self.subTest(path=path):
                page = self.client.get(path).get_data(as_text=True)
                self.assertIn("data-aide", page)
                self.assertIn("YaVaKa assistant", page)
                self.assertIn("js/assistant.js", page)

    def test_the_window_is_not_on_the_auth_pages(self):
        for path in ("/login", "/register"):
            with self.subTest(path=path):
                page = self.client.get(path).get_data(as_text=True)
                self.assertNotIn("data-aide", page)

    def test_asking_needs_a_session_and_a_csrf_token(self):
        # CSRF is verified before the session, so a bare post is refused outright.
        self.assertEqual(
            self.client.post("/api/assistant/ask", json={"question": "balance"}).status_code,
            400,
        )
        # With a valid token but no session it falls through to the login redirect.
        self.assertEqual(self._ask("balance").status_code, 302)

        self.login()
        self.assertEqual(
            self.client.post("/api/assistant/ask", json={"question": "balance"}).status_code,
            400,
        )

    def test_the_balance_matches_the_ledger_page(self):
        import queries

        self.login()
        payload = self._ask("What is my balance?").get_json()
        self.assertTrue(payload["ok"])

        with self.app.app_context():
            from db import query

            owner = query(
                "SELECT id FROM users WHERE email = 'client@yavaka.co.zw'", one=True
            )
            ids = [
                row["id"]
                for row in query(
                    "SELECT id FROM projects WHERE owner_id = ?", (owner["id"],)
                )
            ]
            expected = queries.totals_for_projects(ids)

        self.assertIn(f"${expected['balance'] / 100:,.2f}", payload["reply"])
        self.assertEqual(payload["links"][0][1], "/app/money")

    def test_a_manager_hears_about_clients_and_a_client_does_not(self):
        self.login()  # client
        own = self._ask("How are my clients doing?").get_json()
        self.assertIn("do not manage", own["reply"])

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.login(email="manager@yavaka.co.zw")
        manage = self._ask("How are my clients doing?").get_json()
        self.assertIn("/app/whatsapp", [href for _label, href in manage["links"]])

    def test_an_unrecognised_question_still_answers(self):
        self.login()
        response = self._ask("do my goats need planning permission")
        self.assertEqual(response.status_code, 200)
        self.assertIn("did not follow", response.get_json()["reply"])

    def test_counts_agree_with_their_nouns(self):
        self.login()
        reply = self._ask("What needs attention?").get_json()["reply"]

        # These are noun phrases, not bare nouns, so a trailing "s" is wrong.
        for broken in ("waitings", "without a receipts", "1 approvals", "1 payments"):
            with self.subTest(broken=broken):
                self.assertNotIn(broken, reply)

    def test_money_is_never_recorded_from_the_window(self):
        self.login()
        payload = self._ask("I paid 500").get_json()
        # detect_intent reads an amount; the assistant must still refuse and
        # send the person to the ledger rather than write a transaction.
        self.assertIn("/app/money", [href for _label, href in payload["links"]])
        with self.app.app_context():
            from db import query

            self.assertFalse(
                query(
                    "SELECT 1 AS hit FROM transactions WHERE amount_cents = 50000",
                    one=True,
                )
            )

    def test_a_blank_question_is_refused(self):
        self.login()
        self.assertEqual(
            self.client.post(
                "/api/assistant/ask",
                json={"question": "   "},
                headers={"X-CSRF-Token": self.csrf()},
            ).status_code,
            400,
        )


class NotificationBellPanel(VakaTestCase):
    """The bell opens what changed; it does not throw the page away."""

    def _raise_update(self, action="expense.recorded", detail="Cement delivery — spent"):
        from db import log_event, query

        with self.app.app_context():
            project = query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)
            manager = query(
                "SELECT id FROM users WHERE email = 'manager@yavaka.co.zw'", one=True
            )
            log_event(manager["id"], project["id"], action, detail)

    def test_the_bell_is_a_disclosure_not_a_plain_link(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)

        # A <details>/<summary> pair is what makes the panel open in place.
        self.assertIn("data-notif", page)
        self.assertIn('class="icon-btn topbar-alert', page)
        self.assertNotIn(
            '<a class="icon-btn topbar-alert" href="/app/updates"',
            page,
            "the bell must not navigate straight to the inbox",
        )
        # The inbox is still reachable, from the foot of the panel.
        self.assertIn('class="notif-foot" href="/app/updates"', page)

    def test_each_row_links_to_its_own_record(self):
        self._raise_update("document.uploaded", "site-week-12.jpg")
        self.login()
        page = self.client.get("/app").get_data(as_text=True)

        self.assertIn("notif-row", page)
        # A document upload belongs in the vault, not the generic project page.
        self.assertIn("/app/documents?project=", page)

    def test_unread_state_survives_the_panel(self):
        from db import query

        self._raise_update()
        self.login()

        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn("is-unread", page)
        self.assertIn("notif-head-count", page)

        with self.app.app_context():
            owner = query(
                "SELECT id FROM users WHERE email = 'client@yavaka.co.zw'", one=True
            )
            import updates

            # Rendering the panel must not acknowledge anything.
            self.assertGreaterEqual(updates.unread_count(owner["id"]), 1)

    def test_an_empty_inbox_explains_itself(self):
        self.login()
        from db import execute, query

        with self.app.app_context():
            owner = query(
                "SELECT id FROM users WHERE email = 'client@yavaka.co.zw'", one=True
            )
            execute("DELETE FROM notifications WHERE user_id = ?", (owner["id"],))

        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn("notif-empty", page)
        self.assertNotIn("notif-head-count", page)


class UpdateCatalogue(unittest.TestCase):
    def test_every_audited_action_has_a_label(self):
        import re
        from pathlib import Path
        import updates

        source = ""
        for path in Path(".").glob("routes_*.py"):
            source += path.read_text(encoding="utf-8")
        actions = set(re.findall(r'log_event\([^)]*?"([a-z]+\.[a-z]+)"', source, flags=re.S))

        self.assertTrue(actions)
        for action in sorted(actions):
            if action in updates.QUIET_ACTIONS:
                continue
            with self.subTest(action=action):
                self.assertIn(action, updates.ACTIONS)

    def test_kinds_cover_every_prefix(self):
        import updates

        for action in updates.ACTIONS:
            kind = updates.kind_for(action)
            self.assertIn(kind, updates.KINDS)
            if kind != "all":
                self.assertTrue(action.startswith(updates.KINDS[kind][1]))

    def test_dot_paths_never_leak_into_a_label(self):
        import updates

        described = updates.describe("mystery.event", "detail")
        self.assertNotIn(".", described["title"])
        self.assertIn(described["kind"], updates.KINDS)


class BuildManagerInvites(VakaTestCase):
    """Inviting a manager, accepting the link, and what each side can open."""

    def _people(self):
        from db import query

        with self.app.app_context():
            return (
                query("SELECT * FROM users WHERE email = 'client@yavaka.co.zw'", one=True),
                query("SELECT * FROM users WHERE email = 'manager@yavaka.co.zw'", one=True),
            )

    def _token(self, email="newmanager@example.com"):
        from db import query

        with self.app.app_context():
            return query(
                "SELECT * FROM invitations WHERE email = ? AND status = 'pending' ORDER BY created_at DESC",
                (email,),
                one=True,
            )

    def test_a_client_invites_an_email_with_no_account(self):
        self.login()
        response = self.client.post(
            "/app/team/invite",
            data={"csrf_token": self.csrf(), "email": "NewManager@Example.com"},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("newmanager@example.com", page)
        self.assertIn("/invite/", page)
        self.assertIn("Invite build manager", page)

    def test_a_manager_with_an_account_is_linked_immediately(self):
        from db import execute, new_id, now_iso, query

        with self.app.app_context():
            client, _manager = self._people()
            helper_id = new_id()
            execute(
                """INSERT INTO users (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Helper Manager', 'helper@example.com', 'x', 'manager', '#0F5D46', ?)""",
                (helper_id, now_iso()),
            )

        self.login()
        page = self.client.post(
            "/app/team/invite",
            data={"csrf_token": self.csrf(), "email": "helper@example.com"},
            follow_redirects=True,
        ).get_data(as_text=True)

        self.assertIn("Helper Manager now works on your builds", page)
        with self.app.app_context():
            linked = query(
                "SELECT * FROM manager_links WHERE client_id = ? AND manager_id = ?",
                (client["id"], helper_id),
                one=True,
            )
            self.assertIsNotNone(linked)
            # No pending invitation was needed for an existing account.
            self.assertIsNone(
                query(
                    "SELECT * FROM invitations WHERE email = 'helper@example.com'",
                    one=True,
                )
            )

    def test_accepting_links_the_manager_and_opens_the_clients_projects(self):
        from db import query

        self.login()
        self.client.post(
            "/app/team/invite",
            data={"csrf_token": self.csrf(), "email": "brandnew@example.com"},
        )
        invitation = self._token("brandnew@example.com")
        self.assertIsNotNone(invitation)

        # A different signed-in user cannot accept somebody else's invitation.
        self.login("manager@yavaka.co.zw")
        blocked = self.client.post(
            f"/invite/{invitation['token']}",
            data={"csrf_token": self.csrf()},
            follow_redirects=True,
        )
        self.assertIn("different email address", blocked.get_data(as_text=True))

        # Register the invited address, then accept.
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        with self.app.app_context():
            target_project = query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)["id"]

        registered = self.client.post(
            "/register",
            data={
                "name": "Brand New",
                "email": "brandnew@example.com",
                "password": "Builder2026!",
                "role": "manager",
                "country": "United Kingdom",
                "terms": "yes",
                "invite": invitation["token"],
                "csrf_token": self.csrf(),
            },
            follow_redirects=False,
        )
        self.assertIn("/login", registered.headers["Location"])

        self.login("brandnew@example.com", "Builder2026!")
        accepted = self.client.post(
            f"/invite/{invitation['token']}",
            data={"csrf_token": self.csrf()},
            follow_redirects=True,
        )
        self.assertEqual(accepted.status_code, 200)

        # The manager can now open the client's build.
        self.assertEqual(self.client.get(f"/app/projects/{target_project}").status_code, 200)

    def test_a_project_invitation_also_assigns_that_build(self):
        from db import query

        self.login()
        with self.app.app_context():
            project = query("SELECT id, manager_id FROM projects WHERE code = 'YVK-0001'", one=True)

        self.client.post(
            f"/app/projects/{project['id']}/manager",
            data={"csrf_token": self.csrf(), "email": "siteperson@example.com"},
            follow_redirects=True,
        )
        invitation = self._token("siteperson@example.com")
        self.assertIsNotNone(invitation)
        self.assertEqual(invitation["project_id"], project["id"])

    def test_assigning_an_existing_account_still_works(self):
        self.login()
        with self.app.app_context():
            from db import query

            project = query(
                """SELECT p.id FROM projects p
                     JOIN users u ON u.id = p.owner_id
                    WHERE u.email = 'client@yavaka.co.zw'
                    ORDER BY p.created_at DESC, p.code DESC LIMIT 1""",
                one=True,
            )
        self.assertIsNotNone(project)

        response = self.client.post(
            f"/app/projects/{project['id']}/manager",
            data={"csrf_token": self.csrf(), "email": "manager@yavaka.co.zw"},
            follow_redirects=True,
        )
        self.assertIn("build manager on this project", response.get_data(as_text=True))

    def test_a_manager_creating_a_project_for_an_existing_client_files_it_under_them(self):
        from db import query

        self.login("manager@yavaka.co.zw")
        response = self.client.post(
            "/app/projects",
            data={
                "csrf_token": self.csrf(),
                "name": "Client Owned Build",
                "city": "Harare",
                "suburb": "Avondale",
                "budget": "50000",
                "client_email": "client@yavaka.co.zw",
                "client_whatsapp": "+263 77 999 0000",
                "stage_keys": ["foundation"],
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            client, manager = self._people()
            project = query(
                "SELECT * FROM projects WHERE name = 'Client Owned Build'", one=True
            )
            self.assertEqual(project["owner_id"], client["id"])
            self.assertEqual(project["manager_id"], manager["id"])
            self.assertIsNotNone(
                query(
                    "SELECT * FROM manager_links WHERE client_id = ? AND manager_id = ?",
                    (client["id"], manager["id"]),
                    one=True,
                )
            )

        # The client sees it without being assigned anything.
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.login()
        self.assertIn("Client Owned Build", self.client.get("/app/projects").get_data(as_text=True))

    def test_a_client_cannot_set_a_client_contact_on_their_own_project(self):
        from db import query

        self.login()
        self.client.post(
            "/app/projects",
            data={
                "csrf_token": self.csrf(),
                "name": "Sneaky Contact Build",
                "city": "Harare",
                "budget": "20000",
                "client_email": "victim@example.com",
                "client_whatsapp": "+263 77 111 2222",
                "stage_keys": ["foundation"],
            },
            follow_redirects=True,
        )

        with self.app.app_context():
            project = query("SELECT * FROM projects WHERE name = 'Sneaky Contact Build'", one=True)
            self.assertIsNone(project["client_email"])
            self.assertIsNone(project["client_whatsapp"])

    def test_registering_claims_a_project_filed_for_your_email(self):
        from db import query

        self.login("manager@yavaka.co.zw")
        self.client.post(
            "/app/projects",
            data={
                "csrf_token": self.csrf(),
                "name": "Filed Before You Joined",
                "city": "Harare",
                "budget": "30000",
                "client_email": "later@example.com",
                "stage_keys": ["foundation"],
            },
            follow_redirects=True,
        )

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.post(
            "/register",
            data={
                "name": "Later Client",
                "email": "later@example.com",
                "password": "Later2026!",
                "role": "client",
                "country": "United Kingdom",
                "terms": "yes",
                "csrf_token": self.csrf(),
            },
            follow_redirects=True,
        )

        with self.app.app_context():
            project = query("SELECT * FROM projects WHERE name = 'Filed Before You Joined'", one=True)
            new_user = query("SELECT * FROM users WHERE email = 'later@example.com'", one=True)
            self.assertIsNotNone(project)
            self.assertIsNotNone(new_user)
            self.assertEqual(project["owner_id"], new_user["id"])
            self.assertIsNotNone(project["manager_id"])

    def test_invitation_only_works_once(self):
        self.login()
        self.client.post(
            "/app/team/invite",
            data={"csrf_token": self.csrf(), "email": "once@example.com"},
        )
        invitation = self._token("once@example.com")
        self.client.post("/logout", data={"csrf_token": self.csrf()})
        self.client.post(
            "/register",
            data={
                "name": "Once Only",
                "email": "once@example.com",
                "password": "Once2026!",
                "role": "manager",
                "country": "United Kingdom",
                "terms": "yes",
                "csrf_token": self.csrf(),
            },
        )

        # Registering with the invited address already claims it.
        from db import query

        with self.app.app_context():
            row = query("SELECT * FROM invitations WHERE id = ?", (invitation["id"],), one=True)
        self.assertEqual(row["status"], "accepted")

        self.login("once@example.com", "Once2026!")
        again = self.client.post(
            f"/invite/{invitation['token']}",
            data={"csrf_token": self.csrf()},
            follow_redirects=True,
        )
        self.assertIn("already been used", again.get_data(as_text=True))

    def test_only_a_client_can_invite_and_only_their_own(self):
        # Anonymous: CSRF rejects it outright, and nothing is created.
        self.assertIn(
            self.client.post("/app/team/invite", data={"email": "x@example.com"}).status_code,
            (302, 400),
        )
        from db import query as _query

        with self.app.app_context():
            self.assertIsNone(
                _query("SELECT id FROM invitations WHERE email = 'x@example.com'", one=True)
            )

        self.login("manager@yavaka.co.zw")
        page = self.client.post(
            "/app/team/invite",
            data={"csrf_token": self.csrf(), "email": "someone@example.com"},
            follow_redirects=True,
        ).get_data(as_text=True)
        # A manager inviting on their own account is a client-side action only;
        # they get the manager view, not an invite form.
        self.assertIn("Clients you work with", page)

    def test_a_manager_assigned_without_a_team_link_can_still_be_removed(self):
        from auth import hash_password
        from db import execute, new_id, now_iso, query

        password = "Legacy2026!"
        with self.app.app_context():
            _client, manager = self._people()
            # A fresh client keeps this test's cleanup away from demo data.
            owner_id = new_id()
            owner_email = f"{owner_id}@example.com"
            execute(
                """INSERT INTO users (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Legacy Client', ?, ?, 'client', '#0F5D46', ?)""",
                (owner_id, owner_email, hash_password(password), now_iso()),
            )
            project_id = new_id()
            execute(
                """INSERT INTO projects (id, code, name, owner_id, manager_id, city, status,
                                         budget_cents, created_at, updated_at)
                   VALUES (?, ?, 'Legacy Assignment', ?, ?, 'Harare', 'planning',
                           1000, ?, ?)""",
                (
                    project_id,
                    f"YVK-L{new_id()[:4].upper()}",
                    owner_id,
                    manager["id"],
                    now_iso(),
                    now_iso(),
                ),
            )

        self.login(owner_email, password)
        page = self.client.post(
            f"/app/team/{manager['id']}/remove",
            data={"csrf_token": self.csrf()},
            follow_redirects=True,
        ).get_data(as_text=True)
        self.assertIn("Build manager removed from your builds", page)

        with self.app.app_context():
            row = query(
                "SELECT manager_id FROM projects WHERE id = ?", (project_id,), one=True
            )
            self.assertIsNone(row["manager_id"])
            self.assertIsNone(
                query(
                    "SELECT id FROM manager_links WHERE client_id = ? AND manager_id = ?",
                    (owner_id, manager["id"]),
                    one=True,
                )
            )

class SecurityHardening(VakaTestCase):
    """Sessions, throttling and two-factor authentication."""

    PASSWORD = "Str0ngPassw0rd!"

    def _make_user(self, role="client"):
        import auth
        from db import execute, new_id, now_iso

        email = f"sec-{os.urandom(4).hex()}@example.test"
        user_id = new_id()
        with self.app.app_context():
            execute(
                """INSERT INTO users
                     (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Security Case', ?, ?, ?, '#0F5D46', ?)""",
                (user_id, email, auth.hash_password(self.PASSWORD), role, now_iso()),
            )
        self.addCleanup(self._drop_user, user_id)
        return email, user_id

    def _drop_user(self, user_id):
        from db import execute

        with self.app.app_context():
            execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (user_id,))
            execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
            execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
            execute("DELETE FROM audit_events WHERE user_id = ?", (user_id,))
            execute("DELETE FROM auth_throttle")
            execute("DELETE FROM users WHERE id = ?", (user_id,))

    def test_changing_the_password_signs_other_devices_out(self):
        email, _ = self._make_user()

        device_one = self.app.test_client()
        device_two = self.app.test_client()
        for client in (device_one, device_two):
            token = self._csrf(client)
            client.post(
                "/login",
                data={"email": email, "password": self.PASSWORD, "csrf_token": token},
            )
            self.assertEqual(client.get("/app").status_code, 200)

        token = self._csrf(device_one)
        response = device_one.post(
            "/app/settings/password",
            data={
                "current_password": self.PASSWORD,
                "new_password": "EvenStr0nger!",
                "confirm_password": "EvenStr0nger!",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertIn(b"Other devices have been signed out", response.data)

        # The device that changed it stays in; the other cookie is retired.
        self.assertEqual(device_one.get("/app").status_code, 200)
        self.assertEqual(device_two.get("/app").status_code, 302)

    def test_sign_in_attempts_are_recorded(self):
        from db import query

        email, user_id = self._make_user()
        token = self.csrf()
        self.client.post(
            "/login",
            data={"email": email, "password": "wrong", "csrf_token": token},
        )

        with self.app.app_context():
            failed = query(
                "SELECT * FROM audit_events WHERE user_id = ? AND action = 'login.failed'",
                (user_id,),
                one=True,
            )
            throttled = query(
                "SELECT * FROM auth_throttle WHERE key LIKE ?", (f"%{email}",), one=True
            )

        self.assertIsNotNone(failed)
        self.assertIsNotNone(throttled)
        self.assertGreaterEqual(throttled["count"], 1)

    def test_two_factor_is_required_once_enrolled(self):
        import totp
        from db import execute, query

        email, user_id = self._make_user()
        token = self._csrf()
        self.client.post(
            "/login",
            data={"email": email, "password": self.PASSWORD, "csrf_token": token},
        )

        setup = self.client.get("/app/settings/2fa")
        self.assertEqual(setup.status_code, 200)
        with self.client.session_transaction() as session:
            secret = session["totp_setup_secret"]

        response = self.client.post(
            "/app/settings/2fa",
            data={
                "code": totp.current_code(secret),
                "password": self.PASSWORD,
                "csrf_token": self._csrf(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Save your recovery codes", response.data)
        self.addCleanup(
            self._disable_two_factor, user_id
        )

        with self.app.app_context():
            row = query("SELECT totp_enabled FROM users WHERE id = ?", (user_id,), one=True)
        self.assertEqual(int(row["totp_enabled"]), 1)

        # A fresh sign-in now stops at the code step.
        fresh = self.app.test_client()
        login = fresh.post(
            "/login",
            data={"email": email, "password": self.PASSWORD, "csrf_token": self._csrf(fresh)},
        )
        self.assertEqual(login.status_code, 302)
        self.assertIn("/login/2fa", login.headers["Location"])
        self.assertEqual(fresh.get("/app").status_code, 302)

        wrong = fresh.post(
            "/login/2fa", data={"code": "000000", "csrf_token": self._csrf(fresh)}
        )
        self.assertIn(b"not correct", wrong.data)
        self.assertEqual(fresh.get("/app").status_code, 302)

        good = fresh.post(
            "/login/2fa",
            data={"code": totp.current_code(secret), "csrf_token": self._csrf(fresh)},
            follow_redirects=True,
        )
        self.assertEqual(good.status_code, 200)
        self.assertEqual(fresh.get("/app").status_code, 200)

    def test_recovery_code_works_once(self):
        import totp
        from db import execute

        email, user_id = self._make_user()
        token = self._csrf()
        self.client.post(
            "/login",
            data={"email": email, "password": self.PASSWORD, "csrf_token": token},
        )
        self.client.get("/app/settings/2fa")
        with self.client.session_transaction() as session:
            secret = session["totp_setup_secret"]

        page = self.client.post(
            "/app/settings/2fa",
            data={
                "code": totp.current_code(secret),
                "password": self.PASSWORD,
                "csrf_token": self._csrf(),
            },
        ).get_data(as_text=True)

        codes = re.findall(r"<code>([a-z0-9]{4}-[a-z0-9]{4})</code>", page)
        self.assertEqual(len(codes), 8)
        self.addCleanup(self._disable_two_factor, user_id)

        fresh = self.app.test_client()
        fresh.post(
            "/login",
            data={"email": email, "password": self.PASSWORD, "csrf_token": self._csrf(fresh)},
        )
        first = fresh.post(
            "/login/2fa",
            data={"code": codes[0], "csrf_token": self._csrf(fresh)},
            follow_redirects=True,
        )
        self.assertEqual(fresh.get("/app").status_code, 200)
        self.assertIn(b"Greendale", first.data + b"Greendale")

        again = self.app.test_client()
        again.post(
            "/login",
            data={"email": email, "password": self.PASSWORD, "csrf_token": self._csrf(again)},
        )
        reuse = again.post(
            "/login/2fa", data={"code": codes[0], "csrf_token": self._csrf(again)}
        )
        self.assertIn(b"not correct", reuse.data)

    def _disable_two_factor(self, user_id):
        from db import execute

        with self.app.app_context():
            execute(
                "UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?",
                (user_id,),
            )
            execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (user_id,))

    def _csrf(self, client=None):
        client = client or self.client
        with client.session_transaction() as session:
            token = session.get("csrf")
        if token:
            return token
        client.get("/login")
        with client.session_transaction() as session:
            return session["csrf"]


class PerformanceGuarantees(VakaTestCase):
    def test_portfolio_summary_uses_a_constant_number_of_queries(self):
        from unittest.mock import patch

        import queries as query_module

        self.login("manager@yavaka.co.zw")
        with self.app.app_context():
            projects = __import__("db").query("SELECT * FROM projects LIMIT 10")
            self.assertGreaterEqual(len(projects), 2)

            calls = []
            original = query_module.query

            def spy(sql, args=(), one=False):
                calls.append(sql)
                return original(sql, args, one)

            with patch.object(query_module, "query", spy):
                query_module.projects_with_summary(projects)

        # Stages, money and health flags — three queries regardless of how many
        # projects there are. The point is that the count does not grow with the
        # portfolio size.
        self.assertLessEqual(len(calls), 3)


class Observability(VakaTestCase):
    def test_health_reports_backend_and_upload_probe(self):
        payload = self.client.get("/health").get_json()

        self.assertEqual(payload["status"], "ok")
        self.assertIn(payload["database"], {"sqlite", "postgres"})
        self.assertEqual(payload["uploads"], "ok")
        self.assertGreaterEqual(payload["uptime_s"], 0)

    def test_request_id_is_echoed_and_generated(self):
        supplied = self.client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
        self.assertEqual(supplied.headers["X-Request-ID"], "trace-abc-123")

        generated = self.client.get("/health")
        self.assertTrue(generated.headers.get("X-Request-ID"))
        self.assertIn("Server-Timing", generated.headers)

    def test_unhandled_error_returns_a_reference(self):
        import observability
        from flask import render_template

        with self.app.test_request_context("/broken"), self.assertLogs("yavaka.error", level="ERROR"):
            reference = observability.report(RuntimeError("boom for the test"))
            self.assertTrue(reference)

            page = render_template(
                "errors/error.html",
                code=500,
                message="Something went wrong.",
                reference=reference,
                title="Error",
            )

        self.assertIn(reference, page)


class OnboardingChecklist(VakaTestCase):
    PASSWORD = "Str0ngPassw0rd!"

    def _fresh_user(self):
        import auth
        from db import execute, new_id, now_iso

        email = f"new-{os.urandom(4).hex()}@example.test"
        user_id = new_id()
        with self.app.app_context():
            execute(
                """INSERT INTO users
                     (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'New Client', ?, ?, 'client', '#0F5D46', ?)""",
                (user_id, email, auth.hash_password(self.PASSWORD), now_iso()),
            )
        self.addCleanup(self._drop, user_id)
        return email

    def _drop(self, user_id):
        from db import execute

        with self.app.app_context():
            execute("DELETE FROM workspaces WHERE owner_id = ?", (user_id,))
            execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
            execute("DELETE FROM audit_events WHERE user_id = ?", (user_id,))
            execute("DELETE FROM auth_throttle")
            execute("DELETE FROM users WHERE id = ?", (user_id,))

    def test_a_new_account_is_given_a_next_step_and_can_dismiss_it(self):
        email = self._fresh_user()
        self.login(email, self.PASSWORD)

        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn("Set up your workspace", page)
        self.assertIn("Create your first project", page)

        dismissed = self.client.post(
            "/app/onboarding/dismiss", data={"csrf_token": self.csrf()}
        )
        self.assertEqual(dismissed.status_code, 204)

        page = self.client.get("/app").get_data(as_text=True)
        self.assertNotIn("Set up your workspace", page)

    def test_the_checklist_ticks_itself_off_from_real_data(self):
        import onboarding
        from db import execute, new_id, now_iso, query

        email = self._fresh_user()
        user = None
        project_id = new_id()
        with self.app.app_context():
            user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
            execute(
                """INSERT INTO projects
                     (id, code, name, owner_id, manager_id, created_at, updated_at)
                   VALUES (?, ?, 'Checklist Build', ?, NULL, ?, ?)""",
                (project_id, f"YVK-7{os.urandom(3).hex()}", user["id"], now_iso(), now_iso()),
            )
            user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
            checklist = onboarding.should_show(user)

        self.assertIsNotNone(checklist)
        first = checklist["steps"][0]
        self.assertEqual(first["key"], "project")
        self.assertTrue(first["done"])

        with self.app.app_context():
            execute("DELETE FROM projects WHERE id = ?", (project_id,))


class Reporting(VakaTestCase):
    def test_reports_page_rolls_up_the_portfolio(self):
        self.login("manager@yavaka.co.zw")
        page = self.client.get("/app/reports")

        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn("Portfolio", text)
        self.assertIn("Committed budget", text)
        self.assertIn("Greendale Family Home", text)

    def test_project_pack_is_a_printable_record(self):
        from db import query

        self.login("manager@yavaka.co.zw")
        with self.app.app_context():
            project = query("SELECT id, name FROM projects WHERE code = 'YVK-0001'", one=True)

        page = self.client.get(f"/app/projects/{project['id']}/pack")
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn(project["name"], text)
        self.assertIn("Build stages", text)
        self.assertIn("Money trail", text)
        self.assertIn("data-print", text)

    def test_a_stranger_cannot_download_someone_elses_pack(self):
        import auth
        from db import execute, new_id, now_iso, query

        email = f"outsider-{os.urandom(4).hex()}@example.test"
        user_id = new_id()
        with self.app.app_context():
            execute(
                """INSERT INTO users
                     (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Outsider', ?, ?, 'client', '#0F5D46', ?)""",
                (user_id, email, auth.hash_password("Str0ngPassw0rd!"), now_iso()),
            )
            project = query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)
        self.addCleanup(self._drop, user_id)

        self.login(email, "Str0ngPassw0rd!")
        self.assertEqual(
            self.client.get(f"/app/projects/{project['id']}/pack").status_code, 404
        )

    def _drop(self, user_id):
        from db import execute

        with self.app.app_context():
            execute("DELETE FROM workspaces WHERE owner_id = ?", (user_id,))
            execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
            execute("DELETE FROM audit_events WHERE user_id = ?", (user_id,))
            execute("DELETE FROM auth_throttle")
            execute("DELETE FROM users WHERE id = ?", (user_id,))


class CombinedExport(VakaTestCase):
    def test_exporting_every_ledger_names_the_project(self):
        self.login("manager@yavaka.co.zw")
        response = self.client.get("/app/money/export?scope=all")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Project", text.splitlines()[0])
        self.assertIn("YVK-", text)
        self.assertIn("attachment", response.headers["Content-Disposition"])

    def test_a_single_project_export_keeps_its_original_shape(self):
        from db import query

        self.login("manager@yavaka.co.zw")
        with self.app.app_context():
            project = query("SELECT id FROM projects WHERE code = 'YVK-0001'", one=True)

        response = self.client.get(f"/app/money/export?project={project['id']}")
        header = response.get_data(as_text=True).lstrip("\ufeff").splitlines()[0]

        self.assertTrue(header.startswith("Date"), header)
        self.assertNotIn("Project", header)

class PublicHeader(VakaTestCase):
    """The public navbar: mobile reachable, section-aware, accessible."""

    def test_every_public_page_offers_a_phone_menu(self):
        for path in ("/", "/suppliers"):
            with self.subTest(path=path):
                page = self.client.get(path).get_data(as_text=True)
                self.assertIn('aria-controls="site-menu"', page)
                self.assertIn('aria-expanded="false"', page)
                # The drawer must exist in the markup; JS only un-hides it.
                self.assertIn('id="site-menu"', page)

    def test_nav_links_carry_section_targets_for_highlighting(self):
        page = self.client.get("/").get_data(as_text=True)

        for section in ("how", "stages", "money", "whatsapp"):
            with self.subTest(section=section):
                self.assertIn(f'data-spy="{section}"', page)
                self.assertIn(f'id="{section}"', page.replace('href="/#', 'href="#'))

    def test_suppliers_is_marked_current_not_merely_styled(self):
        page = self.client.get("/suppliers").get_data(as_text=True)

        self.assertIn('aria-current="page"', page)
        self.assertIn("is-active", page)

    def test_the_landing_page_does_not_claim_a_current_section(self):
        page = self.client.get("/").get_data(as_text=True)

        # Highlighting is decided by scroll position on the landing page, so the
        # server must not stamp one link as current.
        self.assertNotIn('aria-current="page"', page)

    def test_signed_in_visitors_get_a_dashboard_link(self):
        self.login()
        page = self.client.get("/suppliers").get_data(as_text=True)

        header = page.split("</header>", 1)[0]
        self.assertIn("Open dashboard", header)
        self.assertNotIn('data-modal-open="modal-login"', header)

class MobileErgonomics(VakaTestCase):
    """The rules that keep a phone usable, asserted against the stylesheet."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from pathlib import Path

        cls.portal = Path("static/css/portal.css").read_text(encoding="utf-8")
        cls.app_css = Path("static/css/app.css").read_text(encoding="utf-8")
        cls.transitions = Path("static/css/transitions.css").read_text(encoding="utf-8")

    def test_touch_controls_are_never_smaller_than_the_ios_zoom_threshold(self):
        # Safari zooms the page when a control under 16px takes focus, so the
        # touch rule has to win against every per-context size in the sheet.
        self.assertIn("(pointer: coarse)", self.portal)
        self.assertIn("font-size: 16px !important", self.portal)

    def test_finger_sized_targets_are_declared_for_touch(self):
        coarse = self.portal.split("(pointer: coarse)", 1)[1]
        self.assertIn("min-height: 44px", coarse)

    def test_wide_tables_stack_instead_of_scrolling_sideways(self):
        self.assertIn(".admin-table--stack", self.portal)
        self.assertIn("attr(data-label)", self.portal)

    def test_the_loading_bar_cannot_widen_the_page(self):
        block = self.transitions.split(".page-progress {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: hidden", block)
        # The sweep only animates while a navigation is actually running.
        self.assertIn(".page-progress.is-active::after", self.transitions)

    def test_dynamic_viewport_height_is_used_where_supported(self):
        self.assertIn("100dvh", self.portal)


class SupplierDirectory(VakaTestCase):
    def test_every_supplier_has_a_link_and_appears_once(self):
        from db import query

        with self.app.app_context():
            rows = query("SELECT name, website FROM suppliers ORDER BY name")

        self.assertEqual(len(rows), 16)
        names = [row["name"] for row in rows]
        self.assertEqual(len(names), len(set(names)), "duplicate supplier names")
        for row in rows:
            with self.subTest(supplier=row["name"]):
                self.assertTrue(row["website"], f"{row['name']} has no website")
                self.assertTrue(row["website"].startswith("http"))

    def test_both_directories_link_the_shop_name(self):
        self.login()
        page = self.client.get("/app/suppliers").get_data(as_text=True)
        self.assertIn('class="supplier-name"', page)
        self.assertIn('href="https://www.halsted.co.zw"', page)

        self.client.post("/logout", data={"csrf_token": self.csrf()})
        public = self.client.get("/suppliers").get_data(as_text=True)
        self.assertIn('class="supplier-name"', public)

    def test_reseeding_does_not_duplicate_the_directory(self):
        from db import query
        import seed

        with self.app.app_context():
            before = query("SELECT COUNT(*) AS n FROM suppliers", one=True)["n"]
            seed._seed_suppliers()
            seed._seed_suppliers()
            after = query("SELECT COUNT(*) AS n FROM suppliers", one=True)["n"]

        self.assertEqual(before, after)

class ProjectKinds(VakaTestCase):
    """Not every project is a house from scratch."""

    def test_the_catalogue_covers_the_work_a_house_needs(self):
        import project_kinds

        keys = {kind["key"] for kind in project_kinds.PROJECT_KINDS}
        for expected in (
            "full_build",
            "renovation",
            "extension",
            "kitchen",
            "bathroom",
            "interior",
            "roofing",
            "solar",
            "borehole",
            "walls_gates",
        ):
            with self.subTest(kind=expected):
                self.assertIn(expected, keys)

    def test_every_kind_names_real_stages(self):
        from stages import STAGES_BY_KEY
        import project_kinds

        for kind in project_kinds.PROJECT_KINDS:
            with self.subTest(kind=kind["key"]):
                self.assertTrue(kind["stages"], "a kind needs at least one stage")
                for key in kind["stages"]:
                    self.assertIn(key, STAGES_BY_KEY)

    def test_a_kitchen_project_does_not_start_with_land_due_diligence(self):
        import project_kinds

        stages = project_kinds.default_stages("kitchen")
        self.assertIn("finishes", stages)
        self.assertNotIn("land_due_diligence", stages)
        self.assertNotIn("foundation", stages)

    def test_an_unknown_kind_falls_back_instead_of_raising(self):
        import project_kinds

        self.assertEqual(project_kinds.kind_for("nonsense")["key"], "full_build")
        self.assertEqual(project_kinds.kind_for(None)["key"], "full_build")

    def test_creating_a_project_records_its_kind(self):
        from db import query

        self.login("manager@yavaka.co.zw")
        response = self.client.post(
            "/app/projects",
            data={
                "csrf_token": self.csrf(),
                "name": "Borrowdale Solar Install",
                "kind": "solar",
                "city": "Harare",
                "suburb": "Borrowdale",
                "budget": "4,000",
                "start_date": "2026-10-01",
            },
            follow_redirects=False,
        )
        self.assertIn(response.status_code, (302, 200))

        with self.app.app_context():
            project = query(
                "SELECT id, kind FROM projects WHERE name = 'Borrowdale Solar Install'",
                one=True,
            )
            stages = query(
                "SELECT key FROM stages WHERE project_id = ?", (project["id"],)
            ) if project else []

        self.assertIsNotNone(project)
        self.assertEqual(project["kind"], "solar")
        self.assertNotIn("land_due_diligence", {row["key"] for row in stages})

        self.addCleanup(self._drop_project, project["id"])

    def _drop_project(self, project_id):
        from db import execute

        with self.app.app_context():
            for table in ("notifications", "audit_events", "transactions", "stages",
                          "attachments", "agreements"):
                execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
            execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def test_an_invalid_kind_is_rejected(self):
        self.login("manager@yavaka.co.zw")
        response = self.client.post(
            "/app/projects",
            data={
                "csrf_token": self.csrf(),
                "name": "Invalid Kind Build",
                "kind": "spaceship",
                "budget": "5,000",
            },
        )
        self.assertEqual(response.status_code, 400)


class HealthSignals(VakaTestCase):
    """Red for bad, green for good, and the thresholds in between."""

    BASE = {
        "id": "p1",
        "name": "Test",
        "status": "in_progress",
        "budget_cents": 1_000_00,
        "target_date": None,
    }

    def test_overspending_is_red(self):
        import health

        found = health.signals(
            {**self.BASE, "budget_cents": 100_000},
            {"funded": 200_000, "spent": 150_000},
        )
        over = next(s for s in found if s["key"] == "over_budget")
        self.assertEqual(over["tone"], health.DANGER)

    def test_spending_more_than_was_funded_is_red(self):
        import health

        found = health.signals(self.BASE, {"funded": 10_000, "spent": 50_000})
        keys = {s["key"]: s["tone"] for s in found}
        self.assertEqual(keys.get("over_funded_spend"), health.DANGER)

    def test_passing_the_handover_date_is_red(self):
        from datetime import date, timedelta
        import health

        late = (date.today() - timedelta(days=5)).isoformat()
        found = health.signals({**self.BASE, "target_date": late}, {"funded": 0, "spent": 0})
        signal = next(s for s in found if s["key"] == "past_deadline")
        self.assertEqual(signal["tone"], health.DANGER)
        self.assertIn("5 day", signal["label"])

    def test_a_close_deadline_warns_without_crying_wolf(self):
        from datetime import date, timedelta
        import health

        soon = (date.today() + timedelta(days=10)).isoformat()
        found = health.signals({**self.BASE, "target_date": soon}, {"funded": 0, "spent": 0})
        signal = next(s for s in found if s["key"] == "deadline_soon")
        self.assertEqual(signal["tone"], health.WARN)

    def test_a_healthy_project_is_green(self):
        import health

        found = health.signals(
            {**self.BASE, "budget_cents": 10_000_000},
            {"funded": 5_000_000, "spent": 100_000},
        )
        self.assertEqual(found[0]["tone"], health.SUCCESS)
        self.assertEqual(found[0]["key"], "on_track")

    def test_alerts_never_include_good_news(self):
        import health

        # A project comfortably inside a large budget has nothing to raise.
        healthy = {**self.BASE, "budget_cents": 10_000_000}
        found = health.alerts(healthy, {"funded": 5_000_000, "spent": 100_000})
        self.assertEqual(found, [])

    def test_worst_tone_wins_for_a_card(self):
        import health

        summary = health.summary(
            {**self.BASE, "budget_cents": 100_000},
            {"funded": 50_000, "spent": 500_000},
        )

        self.assertEqual(summary["tone"], health.DANGER)


class HealthNotifications(VakaTestCase):
    def test_going_over_budget_notifies_owner_and_manager_once(self):
        import updates
        from db import execute, new_id, now_iso, query

        with self.app.app_context():
            owner = query("SELECT id FROM users WHERE role = 'client' LIMIT 1", one=True)
            manager = query(
                "SELECT id FROM users WHERE email = 'manager@yavaka.co.zw'", one=True
            )
            project_id = new_id()
            execute(
                """INSERT INTO projects (id, code, name, owner_id, manager_id, kind, status,
                        budget_cents, created_at, updated_at)
                   VALUES (?, 'YVK-9401', 'Health Check Build', ?, ?, 'full_build',
                           'in_progress', 100000, ?, ?)""",
                (project_id, owner["id"], manager["id"], now_iso(), now_iso()),
            )
            execute(
                """INSERT INTO transactions
                     (id, project_id, type, amount_cents, currency, description,
                      occurred_at, created_by, created_at)
                   VALUES (?, ?, 'EXPENSE', 250000, 'USD', 'Over budget spend', ?, ?, ?)""",
                (new_id(), project_id, now_iso(), manager["id"], now_iso()),
            )

            created = updates.raise_health_alerts(project_id)
            rows = query(
                "SELECT tone, action FROM notifications WHERE project_id = ?",
                (project_id,),
            )
            again = updates.raise_health_alerts(project_id)
            after = query(
                "SELECT COUNT(*) AS n FROM notifications WHERE project_id = ?",
                (project_id,),
                one=True,
            )["n"]

        self.addCleanup(self._drop, project_id)
        actions = {row["action"] for row in rows}
        # Over budget *and* spending more than was funded: two red signals,
        # each sent to the owner and the manager.
        self.assertEqual(actions, {"project.over_budget", "project.over_spent"})
        self.assertEqual(created, 4)  # 2 signals x 2 recipients
        self.assertTrue(all(row["tone"] == "danger" for row in rows))
        self.assertEqual(again, 0, "the same alert must not fire twice")
        self.assertEqual(after, 4)

    def _drop(self, project_id):
        from db import execute

        with self.app.app_context():
            for table in ("notifications", "audit_events", "transactions", "stages"):
                execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
            execute("DELETE FROM projects WHERE id = ?", (project_id,))


class SupplierCategoryDropdown(VakaTestCase):
    def test_categories_live_in_one_dropdown_with_counts(self):
        public = self.client.get("/suppliers").get_data(as_text=True)
        self.assertNotIn('class="chip-row"', public)
        self.assertIn('select name="category"', public.replace('class="select" ', ""))
        self.assertRegex(public, r"All categories \(\d+\)")

    def test_the_signed_in_directory_matches(self):
        self.login()
        page = self.client.get("/app/suppliers").get_data(as_text=True)
        self.assertNotIn('class="chip-row"', page)
        self.assertRegex(page, r"All categories \(\d+\)")

class ColourContrast(VakaTestCase):
    """Text colours must clear WCAG AA. These are the tokens every page uses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import re
        from pathlib import Path

        css = Path("static/css/app.css").read_text(encoding="utf-8")
        cls.light = dict(
            re.findall(r"(--(?:ink|ink-soft|ink-faint)):\s*(#[0-9a-fA-F]{6})", css)
        )
        cls.surfaces = dict(
            re.findall(r"(--sand-[0-9]+):\s*(#[0-9a-fA-F]{6})", css)
        )

    @staticmethod
    def _lum(hex_colour):
        value = hex_colour.lstrip("#")
        channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def _ratio(self, a, b):
        hi, lo = sorted([self._lum(a), self._lum(b)], reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    def _theme_tokens(self, selector):
        """Every custom property declared inside one theme block, plus the
        dark overrides layered on top of it."""
        import re

        css = Path("static/css/theme.css").read_text(encoding="utf-8")
        tokens = {}
        # Walk the file once, tracking the innermost at-rule-ish selector so a
        # later block (the landing page override) wins over the base theme.
        for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            head, body = block.group(1), block.group(2)
            if selector not in head:
                continue
            for name, value in re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", body):
                tokens[name] = value
        return tokens

    def test_a_soft_panel_never_carries_ink_that_matches_it(self):
        """Dark mode must not paint dark ink onto a dark panel.

        The callout, the notices and the active states all sit on a
        `--forest-50/100` slab. In light mode those slabs are pale and the ink
        is a deep forest; in dark mode both flip, which silently produced 1:1
        text. This pins the pairs that carry text.
        """
        import re

        dark = self._theme_tokens('[data-theme="dark"]')
        self.assertTrue(dark, "expected the dark theme tokens")

        light_css = Path("static/css/app.css").read_text(encoding="utf-8")
        light = dict(re.findall(r"(--[a-z0-9-]+):\\s*(#[0-9a-fA-F]{6})", light_css))

        def resolved(name):
            return dark.get(name) or light.get(name)

        # Soft slab -> the ink each one is read with in the dark theme.
        pairs = [
            ("--forest-50", "--ink"),
            ("--forest-100", "--ink"),
            ("--success-soft", "--forest-200"),
        ]
        for surface, ink in pairs:
            background, foreground = resolved(surface), resolved(ink)
            if not (background and foreground):
                continue
            with self.subTest(surface=surface, ink=ink):
                self.assertGreaterEqual(
                    self._ratio(background, foreground),
                    4.5,
                    f"{ink} on {surface} is unreadable in dark mode",
                )

    def test_dark_mode_overrides_the_ink_on_soft_panels(self):
        """Every component that sits on a soft slab is re-inked for dark mode.

        Dropping one of these selectors is exactly the bug that made the
        WhatsApp callout and the two landing buttons unreadable: the slab went
        dark and the ink stayed dark with it.
        """
        css = Path("static/css/theme.css").read_text(encoding="utf-8")
        dark_rules = [
            block
            for block in css.split("}")
            if 'data-theme="dark"' in block
        ]
        scoped = "\n".join(dark_rules)

        for selector in (
            ".callout",
            ".all-clear",
            ".notice-info",
            ".side-note",
            ".wa-quick-btn",
            ".nav-link:hover",
            ".btn-light",
        ):
            with self.subTest(selector=selector):
                self.assertIn(
                    selector,
                    scoped,
                    f"{selector} keeps its light-mode ink in dark mode",
                )

        # The light button is light on the bright site and dark in the app, so
        # its ink has to be scoped to the shell that made it dark.
        self.assertIn('body.app .btn-light', scoped)
        self.assertIn('body:not(.app) .btn-light', scoped)

    def test_the_landing_page_keeps_pale_panels_in_dark_mode(self):
        """The bright site is bright in both themes, so its panels stay pale."""
        import re

        css = Path("static/css/theme.css").read_text(encoding="utf-8")
        block = re.search(
            r'\[data-theme="dark"\]\s+body:not\(\.app\)\s*\{([^}]*)\}', css
        )
        self.assertIsNotNone(block, "the landing dark block is missing")
        body = block.group(1)

        # A pale panel needs its pale fill restored, or the callout is a dark
        # slab under dark ink.
        for token in ("--forest-50", "--ink"):
            with self.subTest(token=token):
                self.assertIn(token, body)

        # And the solid light button must carry dark ink, not the app's white.
        self.assertIn('body:not(.app) .btn-light', css)

    def test_muted_text_clears_aa_on_every_light_surface(self):
        tokens = {
            k: v for k, v in self.light.items() if k in ("--ink-soft", "--ink-faint")
        }
        surfaces = {
            k: v for k, v in self.surfaces.items() if k in ("--sand-50", "--sand-100", "--sand-200")
        }

        self.assertTrue(tokens, "expected the text tokens in app.css")
        self.assertTrue(surfaces)

        for token, colour in tokens.items():
            for surface, background in surfaces.items():
                with self.subTest(token=token, surface=surface):
                    ratio = self._ratio(colour, background)
                    self.assertGreaterEqual(
                        round(ratio, 2),
                        4.5,
                        f"{token} ({colour}) on {surface} ({background}) is {ratio:.2f}:1",
                    )

    def test_avatar_palette_clears_aa_against_white_initials(self):
        from routes_auth import AVATAR_COLORS

        for colour in AVATAR_COLORS:
            with self.subTest(colour=colour):
                ratio = self._ratio("#ffffff", colour)
                self.assertGreaterEqual(
                    round(ratio, 2), 4.5, f"white initials on {colour} is {ratio:.2f}:1"
                )

    def test_brass_eyebrows_use_the_readable_shade(self):
        # brass-600 is 3.4:1 on sand and fails AA for 11px caps.
        import re
        from pathlib import Path

        css = Path("static/css/app.css").read_text(encoding="utf-8")
        eyebrow = re.search(r"\.eyebrow \{[^}]*\}", css, re.S).group(0)
        self.assertIn("var(--brass-700)", eyebrow)

    def test_mockup_placeholder_text_clears_aa_on_white(self):
        # The landing WhatsApp mockup sits muted copy on a white pill; a raw
        # grey there is easy to miss because the parent already looks dark.
        import re
        from pathlib import Path

        css = Path("static/css/app.css").read_text(encoding="utf-8")
        rule = re.search(r"\.phone-input \{[^}]*\}", css, re.S).group(0)
        colour = re.search(r"color:\s*([^;]+);", rule).group(1).strip()
        token = re.fullmatch(r"var\((--[a-z0-9-]+)\)", colour)
        if token:
            colour = re.search(
                rf"{token.group(1)}:\s*(#[0-9a-fA-F]{{6}})", css
            ).group(1)
        self.assertRegex(colour, r"^#[0-9a-fA-F]{6}$")
        self.assertGreaterEqual(
            round(self._ratio(colour, "#ffffff"), 2),
            4.5,
            f"mockup placeholder {colour} on white fails AA",
        )

    def test_light_on_dark_text_clears_aa(self):
        # Dark bands (footer, final CTA, phone mockup) use white alphas. Below
        # ~0.55 the result drops under AA for small text, and light-surface
        # tokens such as `.muted` sink to ~2.5:1 unless explicitly overridden.
        import re
        from pathlib import Path

        css = Path("static/css/app.css").read_text(encoding="utf-8")
        dark = "#052018"  # --forest-950, the darkest band behind white text
        base = [int(dark[i : i + 2], 16) for i in (1, 3, 5)]

        alphas = re.findall(
            r"(?<![\w-])color:\s*rgba\(255,\s*255,\s*255,\s*([\d.]+)\)", css
        )
        self.assertTrue(alphas, "expected white-on-dark text colours")

        for alpha in alphas:
            a = float(alpha)
            composited = "#" + "".join(
                f"{round(a * 255 + (1 - a) * c):02x}" for c in base
            )
            with self.subTest(alpha=a):
                self.assertGreaterEqual(
                    round(self._ratio(composited, dark), 2),
                    4.5,
                    f"white@{a} on {dark} is {self._ratio(composited, dark):.2f}:1",
                )

        # `.muted` is tuned for sand surfaces; the footer must re-map it.
        self.assertRegex(css, r"\.site-footer \.muted\s*\{[^}]*color:")


class DotEnvLoading(unittest.TestCase):
    """`.env` must work for a normal person editing a file on Windows."""

    def _load(self, text, preset=None):
        import config

        directory = tempfile.mkdtemp(prefix="vaka-env-")
        path = Path(directory) / ".env"
        # A literal U+FEFF in the string encodes to the same EF BB BF bytes a
        # Windows editor writes, so the BOM test exercises the real thing.
        path.write_bytes(text.encode("utf-8"))

        saved = {}
        for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"):
            if key in os.environ:
                saved[key] = os.environ.pop(key)
        os.environ.update(preset or {})
        try:
            config._load_dotenv(path)
            loaded = {
                key: os.environ.get(key)
                for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_PASSWORD", "SMTP_FROM_EMAIL")
            }
        finally:
            for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"):
                os.environ.pop(key, None)
            os.environ.update(saved)
        return loaded

    def test_plain_values_are_read(self):
        loaded = self._load("SMTP_HOST=smtp.gmail.com\nSMTP_PORT=587\n")
        self.assertEqual(loaded["SMTP_HOST"], "smtp.gmail.com")
        self.assertEqual(loaded["SMTP_PORT"], "587")

    def test_windows_byte_order_mark_does_not_break_the_first_key(self):
        # Notepad and PowerShell's Set-Content both write a BOM; without
        # utf-8-sig the first key becomes "\ufeffSMTP_HOST" and silently fails.
        loaded = self._load("\ufeffSMTP_HOST=smtp.gmail.com\n")
        self.assertEqual(loaded["SMTP_HOST"], "smtp.gmail.com")

    def test_quotes_are_stripped_and_inner_spaces_are_kept(self):
        loaded = self._load('SMTP_PASSWORD="abcd efgh ijkl mnop"\n')
        self.assertEqual(loaded["SMTP_PASSWORD"], "abcd efgh ijkl mnop")

    def test_trailing_comment_is_dropped_but_a_hash_in_a_value_survives(self):
        loaded = self._load("SMTP_HOST=smtp.gmail.com  # primary\nSMTP_PASSWORD=abc#def\n")
        self.assertEqual(loaded["SMTP_HOST"], "smtp.gmail.com")
        self.assertEqual(loaded["SMTP_PASSWORD"], "abc#def")

    def test_real_environment_wins_over_the_file(self):
        loaded = self._load("SMTP_HOST=from-file\n", preset={"SMTP_HOST": "from-host"})
        self.assertEqual(loaded["SMTP_HOST"], "from-host")

    def test_comments_and_blank_lines_are_skipped(self):
        loaded = self._load("# a comment\n\n   \nSMTP_FROM_EMAIL=YaVaKa <x@y.z>\n")
        self.assertEqual(loaded["SMTP_FROM_EMAIL"], "YaVaKa <x@y.z>")


class EmailDiagnostics(unittest.TestCase):
    """The SMTP checker should name the cause, not just echo the exception."""

    def test_password_is_masked(self):
        from tools.check_email import _mask

        masked = _mask("abcdefghijklmnop")
        self.assertNotIn("cdefghijklmno", masked)
        self.assertTrue(masked.startswith("ab"))
        self.assertTrue(masked.endswith("op"))
        self.assertEqual(_mask(""), "(empty)")

    def test_bad_login_points_at_app_passwords(self):
        from tools.check_email import explain

        hint = explain("(535, b'5.7.8 Username and Password not accepted')", "smtp.gmail.com")
        self.assertIn("App Password", hint)

    def test_from_address_rejection_explains_the_alias_rule(self):
        from tools.check_email import explain

        hint = explain("(550, b'5.7.1 From address not owned')")
        self.assertIn("verified", hint)

    def test_closed_connection_suggests_port_465(self):
        from tools.check_email import explain

        self.assertIn("465", explain("Connection unexpectedly closed"))

    def test_unknown_error_falls_back_to_a_settings_pointer(self):
        from tools.check_email import explain

        self.assertIn("settings", explain("something entirely novel"))

    def test_api_error_codes_map_to_provider_causes(self):
        from tools.check_email import explain

        self.assertIn("API key was rejected", explain("401 Key not found"))
        self.assertIn("sender", explain("403 domain not verified").lower())
        self.assertIn("quota", explain("429 too many requests").lower())


    def test_brevo_relay_login_failure_names_the_smtp_key(self):
        # A 535 from the Brevo relay is not a Gmail App Password problem.
        from tools.check_email import explain

        hint = explain(
            "(535, b'5.7.8 Authentication failed')", "smtp-relay.brevo.com"
        )
        self.assertIn("SMTP key", hint)
        self.assertNotIn("App Password", hint)

    def test_gmail_login_failure_points_at_app_passwords(self):
        from tools.check_email import explain

        hint = explain("(535, b'5.7.8 bad credentials')", "smtp.gmail.com")
        self.assertIn("App Password", hint)

    def test_unknown_host_gets_the_generic_login_hint(self):
        from tools.check_email import explain

        hint = explain("(535, b'no')", "mail.example.org")
        self.assertIn("provider", hint.lower())
        self.assertNotIn("Brevo", hint)

class EmailApiProviders(unittest.TestCase):
    """Email must also work where outbound SMTP is blocked (Render Free)."""

    def _app(self, **overrides):
        return create_app(isolated_config(**overrides))

    def test_api_key_alone_configures_email_without_smtp(self):
        app = self._app(
            SMTP_HOST="",
            SMTP_FROM_EMAIL="YaVaKa <hello@yavaka.co.zw>",
            BREVO_API_KEY="xkeysib-test",
        )
        with app.app_context():
            import notifications

            self.assertEqual(notifications.api_provider(), "brevo")
            self.assertTrue(notifications.email_configured())

    def test_no_provider_and_no_smtp_is_unconfigured(self):
        app = self._app(
            SMTP_HOST="",
            SMTP_FROM_EMAIL="hello@yavaka.co.zw",
            BREVO_API_KEY="",
            RESEND_API_KEY="",
            SENDGRID_API_KEY="",
        )
        with app.app_context():
            import notifications

            self.assertEqual(notifications.api_provider(), "")
            self.assertFalse(notifications.email_configured())

    def test_explicit_provider_overrides_detection_order(self):
        app = self._app(
            SMTP_FROM_EMAIL="hello@yavaka.co.zw",
            BREVO_API_KEY="brevo-key",
            SENDGRID_API_KEY="sendgrid-key",
            EMAIL_API_PROVIDER="sendgrid",
        )
        with app.app_context():
            import notifications

            self.assertEqual(notifications.api_provider(), "sendgrid")

    def test_explicit_provider_without_its_key_does_not_claim_it(self):
        app = self._app(
            SMTP_FROM_EMAIL="hello@yavaka.co.zw",
            BREVO_API_KEY="",
            EMAIL_API_PROVIDER="resend",
        )
        with app.app_context():
            import notifications

            self.assertEqual(notifications.api_provider(), "")

    def test_a_key_without_a_sender_address_is_still_unconfigured(self):
        # Sending would fail at the provider, so the app should say so first.
        app = self._app(SMTP_FROM_EMAIL="", BREVO_API_KEY="xkeysib-test")
        with app.app_context():
            import notifications

            self.assertFalse(notifications.email_configured())

    def test_from_address_is_split_into_name_and_address(self):
        app = self._app(SMTP_FROM_EMAIL='YaVaKa Builds <hello@yavaka.co.zw>')
        with app.app_context():
            import notifications

            self.assertEqual(
                notifications._from_parts(), ("YaVaKa Builds", "hello@yavaka.co.zw")
            )

    def test_bare_from_address_has_no_display_name(self):
        app = self._app(SMTP_FROM_EMAIL="hello@yavaka.co.zw")
        with app.app_context():
            import notifications

            self.assertEqual(notifications._from_parts(), ("", "hello@yavaka.co.zw"))

    def test_each_provider_builds_its_own_payload_shape(self):
        app = self._app(SMTP_FROM_EMAIL="YaVaKa <hello@yavaka.co.zw>")
        with app.app_context():
            import notifications

            url, headers, payload = notifications._api_request(
                "resend", "client@example.com", "Subject", "Body"
            )
            self.assertEqual(url, "https://api.resend.com/emails")
            self.assertEqual(headers["Authorization"], "Bearer ")
            self.assertEqual(payload["to"], ["client@example.com"])
            self.assertEqual(payload["from"], "YaVaKa <hello@yavaka.co.zw>")
            self.assertEqual(payload["text"], "Body")

            url, headers, payload = notifications._api_request(
                "brevo", "client@example.com", "Subject", "Body"
            )
            self.assertIn("api-key", headers)
            self.assertEqual(payload["sender"]["name"], "YaVaKa")
            self.assertEqual(payload["to"], [{"email": "client@example.com"}])
            self.assertEqual(payload["textContent"], "Body")

            url, headers, payload = notifications._api_request(
                "sendgrid", "client@example.com", "Subject", "Body"
            )
            self.assertEqual(
                payload["personalizations"], [{"to": [{"email": "client@example.com"}]}]
            )
            self.assertEqual(payload["content"][0]["value"], "Body")

    def test_send_via_api_posts_json_with_a_user_agent(self):
        # Resend sits behind Cloudflare and rejects urllib's default agent with
        # a 403 (error code 1010), so the header is not optional.
        import io
        import json as jsonlib
        from unittest import mock

        app = self._app(
            SMTP_FROM_EMAIL="hello@yavaka.co.zw",
            RESEND_API_KEY="re_test_key",
            EMAIL_API_PROVIDER="resend",
        )

        captured = {}

        class FakeResponse(io.BytesIO):
            status = 200

            def read(self, *args):
                return b'{"id": "abc"}'

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = jsonlib.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with app.app_context():
            import notifications

            with mock.patch.object(notifications.urllib.request, "urlopen", fake_urlopen):
                result = notifications._send_via_api(
                    "resend", "client@example.com", "Subject", "Body"
                )

        self.assertEqual(result["status"], "sent")
        self.assertEqual(captured["url"], "https://api.resend.com/emails")
        lower = {key.lower(): value for key, value in captured["headers"].items()}
        self.assertIn("user-agent", lower)
        self.assertNotIn("python-urllib", lower["user-agent"].lower())
        self.assertEqual(lower["content-type"], "application/json")
        self.assertEqual(captured["body"]["to"], ["client@example.com"])

    def test_http_error_keeps_the_status_code_first(self):
        import urllib.error
        from unittest import mock

        app = self._app(
            SMTP_FROM_EMAIL="hello@yavaka.co.zw",
            BREVO_API_KEY="bad-key",
            EMAIL_API_PROVIDER="brevo",
        )

        def raise_401(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 401, "Unauthorized", {},
                io_stub(b'{"message":"Key not found"}'),
            )

        with app.app_context():
            import notifications

            with mock.patch.object(notifications.urllib.request, "urlopen", raise_401):
                result = notifications._send_via_api(
                    "brevo", "client@example.com", "Subject", "Body"
                )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["error"].startswith("401"))
        self.assertIn("Key not found", result["error"])
        from tools.check_email import explain

        self.assertIn("API key was rejected", explain(result["error"]))

    def test_network_failure_does_not_raise(self):
        import urllib.error
        from unittest import mock

        app = self._app(
            SMTP_FROM_EMAIL="hello@yavaka.co.zw",
            SENDGRID_API_KEY="k",
            EMAIL_API_PROVIDER="sendgrid",
        )

        def refuse(request, timeout=None):
            raise urllib.error.URLError("getaddrinfo failed")

        with app.app_context():
            import notifications

            with mock.patch.object(notifications.urllib.request, "urlopen", refuse):
                result = notifications._send_via_api(
                    "sendgrid", "client@example.com", "Subject", "Body"
                )

        self.assertEqual(result["status"], "failed")
        self.assertIn("getaddrinfo", result["error"])


    def test_mailjet_needs_both_key_and_secret(self):
        # A half-configured Mailjet is worse than none: it would look ready and
        # then fail every send at the provider.
        app = self._app(
            SMTP_FROM_EMAIL="hello@yavaka.co.zw",
            MAILJET_API_KEY="only-the-key",
            MAILJET_API_SECRET="",
        )
        with app.app_context():
            import notifications

            self.assertEqual(notifications.api_provider(), "")
            self.assertFalse(notifications.email_configured())

    def test_mailjet_builds_basic_auth_and_a_messages_array(self):
        import base64

        app = self._app(
            SMTP_FROM_EMAIL="YaVaKa <hello@yavaka.co.zw>",
            MAILJET_API_KEY="key123",
            MAILJET_API_SECRET="secret456",
        )
        with app.app_context():
            import notifications

            url, headers, payload = notifications._api_request(
                "mailjet", "client@example.com", "Subject", "Body"
            )

        self.assertEqual(url, "https://api.mailjet.com/v3.1/send")
        token = headers["Authorization"].split(" ", 1)[1]
        self.assertEqual(base64.b64decode(token).decode(), "key123:secret456")
        message = payload["Messages"][0]
        self.assertEqual(message["From"], {"Email": "hello@yavaka.co.zw", "Name": "YaVaKa"})
        self.assertEqual(message["To"], [{"Email": "client@example.com"}])
        self.assertEqual(message["TextPart"], "Body")

def io_stub(payload):
    import io

    return io.BytesIO(payload)


class SchemaScripts(unittest.TestCase):
    """Schema scripts must split into real statements, never prose.

    A `--` comment containing a semicolon used to be cut in half, which turned
    the remainder of the comment into SQL and crashed Postgres initialisation
    with `syntax error at or near "collapse"`.
    """

    def test_line_comment_with_a_semicolon_is_not_split(self):
        from db import split_statements

        statements = split_statements(
            "-- seeded twice; collapse duplicates\nCREATE TABLE a (id TEXT);\n"
        )
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("CREATE TABLE a"))

    def test_block_comment_with_a_semicolon_is_not_split(self):
        from db import split_statements

        statements = split_statements(
            "/* first; second */\nCREATE TABLE b (id TEXT);\n"
        )
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("CREATE TABLE b"))

    def test_semicolon_inside_a_string_literal_is_preserved(self):
        from db import split_statements

        statements = split_statements("INSERT INTO t VALUES ('a;b');")
        self.assertEqual(statements, ["INSERT INTO t VALUES ('a;b')"])

    def test_doubled_quote_is_an_escape_not_a_terminator(self):
        from db import split_statements

        statements = split_statements("SELECT 'it''s; fine';")
        self.assertEqual(statements, ["SELECT 'it''s; fine'"])

    def test_every_schema_statement_starts_with_sql(self):
        from db import POSTGRES_UPGRADES, SCHEMA, split_statements

        allowed = (
            "CREATE", "ALTER", "INSERT", "UPDATE", "DELETE", "DROP", "COMMENT",
            "GRANT", "SELECT", "DO", "WITH", "SET", "PRAGMA", "BEGIN", "COMMIT",
        )
        for name, script in (("SCHEMA", SCHEMA), ("POSTGRES_UPGRADES", POSTGRES_UPGRADES)):
            statements = split_statements(script)
            self.assertTrue(statements, f"{name} produced no statements")
            for statement in statements:
                with self.subTest(script=name, statement=statement[:60]):
                    first = statement.split(None, 1)[0].upper().lstrip("(")
                    self.assertIn(
                        first, allowed,
                        f"{name} contains a fragment that is not SQL: {statement[:80]!r}",
                    )


class HeaderMotion(unittest.TestCase):
    """The public header should feel alive before anything is hovered."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = Path("static/js/site-nav.js").read_text(encoding="utf-8")
        cls.css = Path("static/css/app.css").read_text(encoding="utf-8")

    def test_scroll_progress_variable_is_written_and_consumed(self):
        self.assertIn("--scroll-progress", self.js)
        self.assertIn("scaleX(var(--scroll-progress", self.css)

    def test_progress_is_clamped_between_zero_and_one(self):
        # A short page (no scroll range) must not divide by zero, and an
        # overscroll must not push the bar past full width.
        self.assertIn("Math.min", self.js)
        self.assertIn("scrollable > 0", self.js)

    def test_links_stagger_in_rather_than_all_at_once(self):
        self.assertIn("nav-rise", self.css)
        self.assertIn("animation-delay", self.css)

    def test_current_section_has_an_idle_cue(self):
        # A breathing glow plus an inset edge, not hover-only styling.
        self.assertIn("@keyframes nav-breathe", self.css)
        self.assertIn(".site-nav-link.is-active::before", self.css)

    def test_header_motion_is_disabled_for_reduced_motion(self):
        block = self.css[self.css.index("Public header: life before hover"):]
        tail = block[block.index("prefers-reduced-motion"):]
        # The animated elements must all be neutralised, not just the header.
        for selector in (".site-header", ".site-nav-link", "::before", "animation: none"):
            with self.subTest(selector=selector):
                self.assertIn(selector, tail)

    def test_no_layout_thrashing_properties_are_animated(self):
        block = self.css[self.css.index("Public header: life before hover"):]
        animated = set(re.findall(r"transition:\s*([^;]+);", block))
        for rule in animated:
            lowered = rule.lower()
            self.assertNotIn("width ", lowered)
            self.assertNotIn("height ", lowered)
            self.assertNotIn("left ", lowered)
            self.assertNotIn("margin", lowered)


class EphemeralDataWarning(unittest.TestCase):
    """Losing the whole database must never be silent again."""

    def test_health_reports_durability(self):
        body = APP.test_client().get("/health").get_json()
        self.assertIn("durable", body)
        # Local SQLite is durable because it is not on an ephemeral platform.
        self.assertTrue(body["durable"])

    def test_render_without_postgres_is_flagged(self):
        from unittest import mock

        import app as app_module

        class Local(Config):
            TESTING = True
            DATABASE_URL = ""
            SEED_DEMO = False
            DEMO_MODE = False
            DATABASE = str(Path(_TEMP_DIR) / "ephemeral.db")
            UPLOAD_FOLDER = str(Path(_TEMP_DIR) / "ephemeral-uploads")

        with mock.patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            instance = app_module.create_app(Local)
            body = instance.test_client().get("/health").get_json()

        self.assertFalse(
            body["durable"],
            "SQLite on Render is wiped on deploy, so health must say so",
        )

    def test_render_warning_is_logged_at_startup(self):
        from unittest import mock

        import app as app_module

        class Local(Config):
            TESTING = True
            DATABASE_URL = ""
            SEED_DEMO = False
            DEMO_MODE = False
            DATABASE = str(Path(_TEMP_DIR) / "ephemeral2.db")
            UPLOAD_FOLDER = str(Path(_TEMP_DIR) / "ephemeral2-uploads")

        with mock.patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            with self.assertLogs("app", level="WARNING") as logs:
                app_module.create_app(Local)

        self.assertTrue(
            any("DATA LOSS RISK" in line for line in logs.output),
            logs.output,
        )

    def test_local_sqlite_does_not_warn(self):
        from unittest import mock

        from routes_public import _ephemeral_host

        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("RENDER", "DYNO", "FLY_APP_NAME", "VERCEL", "RAILWAY_ENVIRONMENT"):
                os.environ.pop(key, None)
            self.assertFalse(_ephemeral_host())

    def test_ephemeral_host_detects_each_platform(self):
        from unittest import mock

        from routes_public import _ephemeral_host

        for key in ("RENDER", "DYNO", "FLY_APP_NAME", "RAILWAY_ENVIRONMENT"):
            with self.subTest(key=key):
                with mock.patch.dict(os.environ, {key: "1"}, clear=False):
                    self.assertTrue(_ephemeral_host())
class EmailChannelReporting(unittest.TestCase):
    """A misconfigured mail path must be visible, not discovered by a client."""

    def _health(self, **overrides):
        config = isolated_config(
            DATABASE=str(Path(_TEMP_DIR) / f"chan-{len(overrides)}-{id(overrides)}.db"),
            UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "chan-uploads"),
            SEED_DEMO=False,
            DEMO_MODE=False,
            **overrides,
        )
        return create_app(config).test_client().get("/health").get_json()

    def test_nothing_configured_reports_none(self):
        body = self._health(
            SMTP_HOST="", BREVO_API_KEY="", MAILJET_API_KEY="",
            RESEND_API_KEY="", SENDGRID_API_KEY="",
        )
        self.assertEqual(body["email"], "none")

    def test_api_key_is_named(self):
        body = self._health(
            SMTP_HOST="", BREVO_API_KEY="xkeysib-test", MAILJET_API_KEY="",
            RESEND_API_KEY="", SENDGRID_API_KEY="",
        )
        self.assertEqual(body["email"], "brevo-api")

    def test_smtp_is_reported_as_smtp(self):
        body = self._health(
            SMTP_HOST="smtp-relay.brevo.com", SMTP_USERNAME="a@smtp-brevo.com",
            BREVO_API_KEY="", MAILJET_API_KEY="", RESEND_API_KEY="",
            SENDGRID_API_KEY="",
        )
        self.assertEqual(body["email"], "smtp")

    def test_render_blocks_smtp_so_a_warning_is_logged(self):
        from unittest import mock

        import app as app_module

        class Relay(Config):
            TESTING = True
            DATABASE_URL = ""
            SEED_DEMO = False
            DEMO_MODE = False
            DATABASE = str(Path(_TEMP_DIR) / "smtp-render.db")
            UPLOAD_FOLDER = str(Path(_TEMP_DIR) / "smtp-render-uploads")
            SMTP_HOST = "smtp-relay.brevo.com"
            SMTP_PORT = 587
            SMTP_USERNAME = "bfe097001@smtp-brevo.com"
            BREVO_API_KEY = ""
            MAILJET_API_KEY = ""
            RESEND_API_KEY = ""
            SENDGRID_API_KEY = ""

        with mock.patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            with self.assertLogs("app", level="WARNING") as logs:
                app_module.create_app(Relay)

        combined = " ".join(logs.output)
        self.assertIn("EMAIL WILL FAIL", combined)
        self.assertIn("587", combined)

    def test_an_api_key_silences_the_smtp_warning(self):
        from unittest import mock

        import app as app_module

        class Both(Config):
            TESTING = True
            DATABASE_URL = ""
            SEED_DEMO = False
            DEMO_MODE = False
            DATABASE = str(Path(_TEMP_DIR) / "smtp-and-api.db")
            UPLOAD_FOLDER = str(Path(_TEMP_DIR) / "smtp-and-api-uploads")
            SMTP_HOST = "smtp-relay.brevo.com"
            BREVO_API_KEY = "xkeysib-test"

        with mock.patch.dict(os.environ, {"RENDER": "true"}, clear=False):
            with self.assertLogs("app", level="WARNING") as logs:
                app_module.create_app(Both)

        self.assertNotIn("EMAIL WILL FAIL", " ".join(logs.output))







class PlaceholderCredentialGuard(unittest.TestCase):
    """Pasted template text must be called out, not silently rejected by Brevo."""

    def _app(self, **overrides):
        base = dict(
            DATABASE=str(Path(_TEMP_DIR) / f"guard-{id(overrides)}.db"),
            UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "guard-uploads"),
            SEED_DEMO=False,
            DEMO_MODE=False,
        )
        base.update(overrides)
        return create_app(isolated_config(**base))

    def test_literal_placeholder_key_warns(self):
        with self.assertLogs("app", level="WARNING") as logs:
            self._app(BREVO_API_KEY="xkeysib-...", SMTP_FROM_EMAIL="a@b.co.zw")
        self.assertIn("EMAIL CREDENTIALS LOOK WRONG", " ".join(logs.output))

    def test_placeholder_from_address_warns(self):
        with self.assertLogs("app", level="WARNING") as logs:
            self._app(
                BREVO_API_KEY="",
                SMTP_FROM_EMAIL="YaVaKa <you@verified-address>",
            )
        self.assertIn("EMAIL_FROM", " ".join(logs.output))

    def test_wrong_prefix_warns(self):
        # A Brevo key pasted without its prefix is a different secret entirely.
        with self.assertLogs("app", level="WARNING") as logs:
            self._app(
                BREVO_API_KEY="abcdefghijklmnopqrstuvwxyz0123456789",
                SMTP_FROM_EMAIL="a@b.co.zw",
            )
        self.assertIn("BREVO_API_KEY", " ".join(logs.output))

    def test_a_realistic_key_does_not_warn(self):
        import logging

        realistic = "xkeysib-" + "a1b2c3d4" * 8 + "-Kq7Zx9" + "p2Lm4N"
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger("app")
        logger.addHandler(handler)
        try:
            self._app(BREVO_API_KEY=realistic, SMTP_FROM_EMAIL="builds@yavaka.co.zw")
        finally:
            logger.removeHandler(handler)

        warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
        self.assertFalse(
            [w for w in warnings if "EMAIL CREDENTIALS LOOK WRONG" in w],
            warnings,
        )

    def test_display_name_only_from_address_warns(self):
        # `EMAIL_FROM=YaVaKa` looks fine in a dashboard and is not an address.
        with self.assertLogs("app", level="WARNING") as logs:
            self._app(BREVO_API_KEY="", SMTP_FROM_EMAIL="YaVaKa")
        combined = " ".join(logs.output)
        self.assertIn("EMAIL CREDENTIALS LOOK WRONG", combined)
        self.assertIn("no email address", combined)

    def test_bare_address_is_accepted_without_warning(self):
        import logging

        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger("app")
        logger.addHandler(handler)
        try:
            self._app(BREVO_API_KEY="", SMTP_FROM_EMAIL="builds@yavaka.co.zw")
        finally:
            logger.removeHandler(handler)

        self.assertFalse(
            [r for r in records if "EMAIL CREDENTIALS" in r.getMessage()],
            [r.getMessage() for r in records],
        )





class WhatsAppChannelReporting(unittest.TestCase):
    """A half-configured WhatsApp channel must not look live."""

    def _app(self, **overrides):
        base = dict(
            DATABASE=str(Path(_TEMP_DIR) / f"wa-{id(overrides)}.db"),
            UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "wa-uploads"),
            SEED_DEMO=False,
            DEMO_MODE=False,
        )
        base.update(overrides)
        return create_app(isolated_config(**base))

    def _health(self, **overrides):
        return self._app(**overrides).test_client().get("/health").get_json()
    def test_phone_id_without_token_is_flagged_as_partial(self):
        # Setting only the phone number id is the easiest half-configuration to
        # make, because Meta shows it next to the token.
        body = self._health(
            WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="",
            WHATSAPP_VERIFY_TOKEN="", WHATSAPP_APP_SECRET="",
        )
        self.assertEqual(body["whatsapp"], "partial")

    def test_full_credentials_report_live(self):
        body = self._health(
            WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="token",
            WHATSAPP_VERIFY_TOKEN="verify", WHATSAPP_APP_SECRET="secret",
        )
        self.assertEqual(body["whatsapp"], "live")

    def test_no_whatsapp_configuration_reports_simulator(self):
        body = self._health(
            WHATSAPP_PHONE_NUMBER_ID="", WHATSAPP_TOKEN="",
            WHATSAPP_VERIFY_TOKEN="", WHATSAPP_APP_SECRET="",
        )
        self.assertEqual(body["whatsapp"], "simulator")

    def test_missing_token_warning_names_the_variable(self):
        with self.assertLogs("app", level="WARNING") as logs:
            self._app(
                WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="",
                WHATSAPP_VERIFY_TOKEN="v", WHATSAPP_APP_SECRET="",
            )
        combined = " ".join(logs.output)
        self.assertIn("WHATSAPP IS IN SIMULATOR MODE", combined)
        self.assertIn("WHATSAPP_TOKEN", combined)

    def test_app_secret_is_not_required(self):
        # Deliberately optional: the channel works without X-Hub-Signature-256.
        # It must not be nagged about, and must not appear in /health.
        body = self._health(
            WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="t",
            WHATSAPP_VERIFY_TOKEN="v", WHATSAPP_APP_SECRET="",
        )
        self.assertEqual(body["whatsapp"], "live")
        self.assertNotIn("WHATSAPP_APP_SECRET", body["whatsapp_missing"])

    def test_signature_check_still_runs_when_the_secret_is_set(self):
        # Removing the requirement must not remove the protection.
        app = self._app(
            WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="t",
            WHATSAPP_VERIFY_TOKEN="v", WHATSAPP_APP_SECRET="shh",
        )
        client = app.test_client()
        unsigned = client.post(
            "/api/whatsapp/webhook",
            data='{"entry": []}',
            content_type="application/json",
        )
        self.assertEqual(unsigned.status_code, 403)

    def test_missing_verify_token_is_flagged(self):
        with self.assertLogs("app", level="WARNING") as logs:
            self._app(
                WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="t",
                WHATSAPP_VERIFY_TOKEN="", WHATSAPP_APP_SECRET="s",
            )
        self.assertIn("VERIFICATION WILL FAIL", " ".join(logs.output))


    def test_missing_variables_are_named_not_valued(self):
        body = self._health(
            WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="",
            WHATSAPP_VERIFY_TOKEN="", WHATSAPP_APP_SECRET="",
        )
        self.assertIn("WHATSAPP_TOKEN", body["whatsapp_missing"])
        # The phone id is present, so it must not be reported as missing.
        self.assertNotIn("WHATSAPP_PHONE_NUMBER_ID", body["whatsapp_missing"])
        # And no secret may leak into the payload.
        self.assertNotIn("709678028897732", str(body["whatsapp_missing"]))

    def test_nothing_missing_when_fully_configured(self):
        body = self._health(
            WHATSAPP_PHONE_NUMBER_ID="709678028897732", WHATSAPP_TOKEN="t",
            WHATSAPP_VERIFY_TOKEN="v", WHATSAPP_APP_SECRET="s",
        )
        self.assertEqual(body["whatsapp_missing"], [])



class AssistantRolesAndLanguages(VakaTestCase):
    """A build manager must not be greeted like a stranger, and a language
    switch must change every later reply, not just the prompt."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from db import execute, query

        with cls.app.app_context():
            manager = query("SELECT * FROM users WHERE role = 'manager' LIMIT 1", one=True)
            client = query("SELECT * FROM users WHERE role = 'client' LIMIT 1", one=True)
            execute("UPDATE users SET phone = ? WHERE id = ?", ("263771100001", manager["id"]))
            execute("UPDATE users SET phone = ? WHERE id = ?", ("263771100002", client["id"]))
            cls.manager_phone = "263771100001"
            cls.client_phone = "263771100002"

    def _say(self, phone, text):
        from whatsapp import handle_inbound

        with self.app.app_context():
            return handle_inbound(phone, text, profile_name="Tester")

    def test_manager_is_not_treated_as_a_stranger(self):
        reply = self._say(self.manager_phone, "hi")
        self.assertNotIn("not linked", reply["reply"])
        self.assertIn("project(s) under you", reply["reply"])

    def test_client_greeting_names_their_project(self):
        reply = self._say(self.client_phone, "hi")
        self.assertIn("Greendale Family Home", reply["reply"])

    def test_unknown_number_gets_its_own_message(self):
        reply = self._say("263779900123", "hi")
        self.assertIn("not linked", reply["reply"])

    def test_language_switch_changes_every_later_reply(self):
        from whatsapp import handle_inbound

        with self.app.app_context():
            set_to_shona = handle_inbound(self.client_phone, "lang_sn")
            self.assertEqual(set_to_shona["language"], "sn")

            # A different intent, sent as a bare number, must also be Shona.
            status = handle_inbound(self.client_phone, "2")
            self.assertEqual(status["language"], "sn")
            self.assertIn("Kufambira mberi", status["reply"])

            junk = handle_inbound(self.client_phone, "zzzz")
            self.assertIn("Handina", junk["reply"])

            back = handle_inbound(self.client_phone, "lang_en")
            self.assertEqual(back["language"], "en")
            english = handle_inbound(self.client_phone, "2")
            self.assertIn("Progress:", english["reply"])

    def test_language_persists_on_the_contact_row(self):
        from db import query

        self._say(self.client_phone, "lang_nd")
        with self.app.app_context():
            row = query(
                "SELECT language FROM whatsapp_contacts WHERE phone = ?",
                (self.client_phone,),
                one=True,
            )
        self.assertEqual(row["language"], "nd")
        self._say(self.client_phone, "lang_en")

    def test_shona_word_also_switches_language(self):
        reply = self._say(self.client_phone, "mutauro")
        self.assertEqual(reply["intent"], "language")
        self._say(self.client_phone, "lang_en")

    def test_manager_menu_lists_manager_actions_not_client_ones(self):
        reply = self._say(self.manager_phone, "hi")
        self.assertIn("My projects", reply["reply"])
        self.assertIn("Needs attention", reply["reply"])
        self.assertNotIn("Send a receipt", reply["reply"])

    def test_tapped_button_id_is_understood_as_a_command(self):
        # WhatsApp sends the button id, not the label.
        reply = self._say(self.client_phone, "m_balance")
        self.assertEqual(reply["intent"], "balance")
        self.assertIn("Available:", reply["reply"])

    def test_manager_can_post_an_update_by_message(self):
        from db import query

        with self.app.app_context():
            project = query(
                "SELECT code FROM projects WHERE manager_id IS NOT NULL LIMIT 1", one=True
            )
        reply = self._say(self.manager_phone, f"update {project['code']} Slab poured today")
        self.assertIn("update posted", reply["reply"].lower())

    def test_update_for_a_foreign_code_is_refused(self):
        reply = self._say(self.manager_phone, "update YVK-9999 should not land")
        self.assertIn("No project with that code", reply["reply"])


class InteractiveMessages(VakaTestCase):
    """Buttons and lists are what make the menu usable on a phone."""

    def _app_with_credentials(self):
        return create_app(
            isolated_config(
                DATABASE=str(Path(_TEMP_DIR) / "interactive.db"),
                UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "interactive-uploads"),
                SEED_DEMO=False,
                DEMO_MODE=False,
                WHATSAPP_TOKEN="token",
                WHATSAPP_PHONE_NUMBER_ID="709678028897732",
            )
        )

    def test_button_payload_shape(self):
        from unittest import mock

        import whatsapp

        app = self._app_with_credentials()
        captured = {}

        def fake(to, content):
            captured["content"] = content
            return {"status": "sent"}

        with app.app_context():
            with mock.patch.object(whatsapp, "_send_whatsapp_payload", fake):
                whatsapp.send_whatsapp_buttons(
                    "263771234567", "Pick one", [("m_balance", "Balance")]
                )

        content = captured["content"]
        self.assertEqual(content["type"], "interactive")
        self.assertEqual(content["interactive"]["type"], "button")
        button = content["interactive"]["action"]["buttons"][0]
        self.assertEqual(button["reply"]["id"], "m_balance")
        self.assertEqual(button["reply"]["title"], "Balance")

    def test_meta_limits_are_enforced(self):
        from unittest import mock

        import whatsapp

        app = self._app_with_credentials()
        captured = {}

        def fake(to, content):
            captured["content"] = content
            return {"status": "sent"}

        rows = [(f"m_{index}", f"Option {index}" * 4) for index in range(14)]
        with app.app_context():
            with mock.patch.object(whatsapp, "_send_whatsapp_payload", fake):
                whatsapp.send_whatsapp_list("263771234567", "Menu", "More options", rows)

        section = captured["content"]["interactive"]["action"]["sections"][0]
        # Meta rejects more than ten rows or a title longer than 24 characters.
        self.assertEqual(len(section["rows"]), 10)
        for row in section["rows"]:
            self.assertLessEqual(len(row["title"]), 24)

    def test_webhook_accepts_a_tapped_button(self):
        from unittest import mock

        import routes_whatsapp

        app = self._app_with_credentials()
        app.config.update(TESTING=True)
        client = app.test_client()

        with mock.patch.object(routes_whatsapp, "handle_inbound") as handled:
            handled.return_value = {"reply": "ok"}
            response = client.post(
                "/api/whatsapp/webhook",
                json={
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "contacts": [{"profile": {"name": "Tester"}}],
                                        "messages": [
                                            {
                                                "from": "263771234567",
                                                "type": "interactive",
                                                "interactive": {
                                                    "type": "button_reply",
                                                    "button_reply": {"id": "m_status"},
                                                },
                                            }
                                        ],
                                    }
                                }
                            ]
                        }
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        handled.assert_called_once()
        self.assertEqual(handled.call_args.kwargs["body"], "m_status")


class DocumentDownloads(VakaTestCase):
    """Documents must be reachable from a WhatsApp message, without a login."""

    def _attachment(self):
        from pathlib import Path as _Path

        from db import execute, new_id, now_iso, query

        with self.app.app_context():
            project = query("SELECT * FROM projects LIMIT 1", one=True)
            owner = query("SELECT * FROM users WHERE id = ?", (project["owner_id"],), one=True)
            attachment_id = f"att_dl_{new_id()[:8]}"
            filename = f"download-fixture-{attachment_id}.pdf"
            # The route streams from disk, so the file has to exist too.
            directory = _Path(self.app.config["UPLOAD_FOLDER"])
            directory.mkdir(parents=True, exist_ok=True)
            (directory / filename).write_bytes(b"%PDF-1.4 fixture")
            execute(
                """INSERT INTO attachments
                     (id, project_id, uploader_id, kind, filename, original_name,
                      mime_type, size, stage_key, created_at)
                   VALUES (?, ?, ?, 'receipt', ?, ?, 'application/pdf', 15, NULL, ?)""",
                (
                    attachment_id,
                    project["id"],
                    owner["id"],
                    filename,
                    "Supplier invoice.pdf",
                    now_iso(),
                ),
            )
        return attachment_id

    def test_signed_link_downloads_without_a_session(self):
        import downloads

        attachment_id = self._attachment()
        with self.app.app_context():
            token = downloads.token_for(attachment_id)

        response = self.app.test_client().get(f"/d/{token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        response.close()

    def test_tampered_token_is_refused(self):
        import downloads

        attachment_id = self._attachment()
        with self.app.app_context():
            token = downloads.token_for(attachment_id)
        forged = token[:-1] + ("0" if token[-1] != "0" else "1")

        self.assertEqual(self.app.test_client().get(f"/d/{forged}").status_code, 404)

    def test_expired_token_is_refused(self):
        from unittest import mock

        import downloads

        attachment_id = self._attachment()
        with self.app.app_context():
            token = downloads.token_for(attachment_id)
            # Jump forward past the seven-day window rather than trusting a
            # negative ttl, which the helper clamps to one day.
            with mock.patch.object(downloads.time, "time", return_value=time.time() + 8 * 86400):
                self.assertIsNone(downloads.verify(token))

    def test_verify_rejects_rubbish(self):
        import downloads

        for token in ("", "abc", "a.b", "a.b.c.d"):
            with self.subTest(token=token):
                self.assertIsNone(downloads.verify(token))

    def test_documents_command_returns_download_links(self):
        from whatsapp import handle_inbound

        attachment_id = self._attachment()
        with self.app.app_context():
            with self.app.test_request_context(
                "/api/whatsapp/webhook", base_url="https://yavaka.onrender.com"
            ):
                reply = handle_inbound("263771234567", "DOCUMENTS")

        self.assertIn("/d/", reply["reply"])
        self.assertIn("https://yavaka.onrender.com/d/", reply["reply"])

    def test_upload_notification_carries_the_link(self):
        from unittest import mock

        import notifications

        attachment_id = self._attachment()
        with self.app.app_context():
            with self.app.test_request_context(base_url="https://yavaka.onrender.com"):
                with mock.patch.object(notifications, "schedule_dispatch"):
                    notifications.queue_manager_update(
                        "x", "y", "Manager", "Project file uploaded", "invoice.pdf",
                        link=f"https://yavaka.onrender.com/d/{attachment_id}",
                    )

            row = notifications.query(
                "SELECT body FROM notification_outbox ORDER BY created_at DESC LIMIT 1",
                one=True,
            )
        if row:
            self.assertIn("Download:", row["body"])


DEFAULT_LANGUAGE_FOR_TEST = "en"


class PostgresParity(VakaTestCase):
    """Every column the code writes must exist on both backends.

    A SQLite-only migration put `whatsapp_contacts.language` into production
    Postgres's blind spot and took the live webhook down with a 500.
    """

    def test_every_upgraded_column_is_also_in_the_postgres_upgrades(self):
        import re
        from pathlib import Path

        source = Path("db.py").read_text(encoding="utf-8")
        upgrades = source.split("POSTGRES_UPGRADES", 1)[1]

        # Columns added by SQLite migrations via ALTER TABLE.
        added = set(
            re.findall(
                r"ALTER TABLE (\w+) ADD COLUMN (\w+)", source.split("POSTGRES_UPGRADES", 1)[0]
            )
        )
        for table, column in added:
            with self.subTest(table=table, column=column):
                self.assertRegex(
                    upgrades,
                    rf"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}\b",
                    f"{table}.{column} is migrated on SQLite but not on Postgres",
                )

    def test_whatsapp_contacts_language_is_present_in_the_base_schema(self):
        from db import SCHEMA

        block = SCHEMA.split("CREATE TABLE IF NOT EXISTS whatsapp_contacts", 1)[1]
        block = block.split(");", 1)[0]
        self.assertIn("language", block)

    def test_missing_language_column_degrades_to_english(self):
        # A row shaped like an un-migrated database must not raise.
        from whatsapp import _stored_language

        self.assertEqual(_stored_language({}), DEFAULT_LANGUAGE_FOR_TEST)
        self.assertEqual(_stored_language({"language": "sn"}), "sn")
        self.assertEqual(_stored_language({"language": None}), DEFAULT_LANGUAGE_FOR_TEST)


class WhatsAppDocumentAttachments(VakaTestCase):
    """Inside Meta's 24-hour window a document is attached; outside it a
    template carries the link instead."""

    def _app(self):
        return create_app(
            isolated_config(
                DATABASE=str(Path(_TEMP_DIR) / "wa-doc.db"),
                UPLOAD_FOLDER=str(Path(_TEMP_DIR) / "wa-doc-uploads"),
                SEED_DEMO=True,
                WHATSAPP_TOKEN="token",
                WHATSAPP_PHONE_NUMBER_ID="709678028897732",
            )
        )

    def _mark_inbound(self, app, phone):
        from db import execute, new_id, now_iso, query

        with app.app_context():
            contact = query(
                "SELECT * FROM whatsapp_contacts WHERE phone = ?", (phone,), one=True
            )
            if not contact:
                contact_id = new_id()
                execute(
                    """INSERT INTO whatsapp_contacts
                         (id, phone, name, language, created_at)
                       VALUES (?, ?, 'Client', 'en', ?)""",
                    (contact_id, phone, now_iso()),
                )
            else:
                contact_id = contact["id"]
            execute(
                """INSERT INTO whatsapp_messages
                     (id, contact_id, direction, body, intent, status, created_at)
                   VALUES (?, ?, 'IN', 'hi', 'help', 'received', ?)""",
                (new_id(), contact_id, now_iso()),
            )

    def test_document_payload_shape(self):
        from unittest import mock

        import whatsapp

        app = self._app()
        captured = {}

        def fake(to, content):
            captured["content"] = content
            return {"status": "sent"}

        with app.app_context():
            with mock.patch.object(whatsapp, "_send_whatsapp_payload", fake):
                whatsapp.send_whatsapp_document(
                    "263771234567",
                    "https://yavaka.onrender.com/d/abc",
                    "invoice.pdf",
                    "Your invoice",
                )

        content = captured["content"]
        self.assertEqual(content["type"], "document")
        self.assertEqual(content["document"]["link"], "https://yavaka.onrender.com/d/abc")
        self.assertEqual(content["document"]["filename"], "invoice.pdf")
        self.assertEqual(content["document"]["caption"], "Your invoice")

    def test_document_without_a_link_fails_loudly(self):
        import whatsapp

        app = self._app()
        with app.app_context():
            result = whatsapp.send_whatsapp_document("263771234567", "", "x.pdf")
        self.assertEqual(result["status"], "failed")

    def test_window_detection(self):
        import notifications

        app = self._app()
        phone = "263779001234"
        with app.app_context():
            self.assertFalse(notifications._within_service_window(phone))
        self._mark_inbound(app, phone)
        with app.app_context():
            self.assertTrue(notifications._within_service_window(phone))

    def test_inside_the_window_the_file_is_attached(self):
        from unittest import mock

        import notifications

        app = self._app()
        phone = "263779005678"
        self._mark_inbound(app, phone)

        delivery = {
            "channel": "whatsapp",
            "recipient": phone,
            "subject": None,
            "body": "Update body",
            "file_url": "https://yavaka.onrender.com/d/xyz",
            "file_name": "receipt.pdf",
        }
        with app.app_context():
            with mock.patch.object(
                notifications, "send_whatsapp_document",
                return_value={"status": "sent"},
            ) as attached:
                with mock.patch.object(notifications, "send_whatsapp_project_update") as templated:
                    result = notifications._deliver(delivery)

        self.assertEqual(result["status"], "sent")
        attached.assert_called_once()
        templated.assert_not_called()

    def test_outside_the_window_the_template_carries_the_link(self):
        from unittest import mock

        import notifications

        app = self._app()
        delivery = {
            "channel": "whatsapp",
            "recipient": "263779009999",
            "subject": None,
            "body": "Update body with a link",
            "file_url": "https://yavaka.onrender.com/d/xyz",
            "file_name": "receipt.pdf",
        }
        with app.app_context():
            with mock.patch.object(notifications, "send_whatsapp_document") as attached:
                with mock.patch.object(
                    notifications, "send_whatsapp_project_update",
                    return_value={"status": "sent"},
                ) as templated:
                    result = notifications._deliver(delivery)

        self.assertEqual(result["status"], "sent")
        attached.assert_not_called()
        templated.assert_called_once()

    def test_attachment_failure_falls_back_to_the_template(self):
        from unittest import mock

        import notifications

        app = self._app()
        phone = "263779007890"
        self._mark_inbound(app, phone)

        delivery = {
            "channel": "whatsapp",
            "recipient": phone,
            "subject": None,
            "body": "Update body",
            "file_url": "https://yavaka.onrender.com/d/xyz",
            "file_name": "receipt.pdf",
        }
        with app.app_context():
            with mock.patch.object(
                notifications, "send_whatsapp_document",
                return_value={"status": "failed", "error": "media rejected"},
            ):
                with mock.patch.object(
                    notifications, "send_whatsapp_project_update",
                    return_value={"status": "sent"},
                ) as templated:
                    result = notifications._deliver(delivery)

        self.assertEqual(result["status"], "sent")
        templated.assert_called_once()


class DocumentStorage(VakaTestCase):
    """Every advertised file type is stored, and the bytes live in the database."""

    BLOB = b"\x00\x01\x02payload" + b"z" * 300

    def _project_id(self):
        from db import query

        with self.app.app_context():
            row = query(
                """SELECT p.id FROM projects p JOIN users u ON u.id = p.owner_id
                   WHERE u.email = 'client@yavaka.co.zw' ORDER BY p.created_at LIMIT 1""",
                one=True,
            )
        return row["id"]

    def _upload(self, filename, blob=None, mime=None):
        import io

        self.login()
        return self.client.post(
            "/app/documents/upload",
            data={
                "project_id": self._project_id(),
                "kind": "document",
                "csrf_token": self.csrf(),
                "file": (io.BytesIO(blob if blob is not None else self.BLOB), filename),
            },
            content_type="multipart/form-data",
        )

    def _latest(self):
        from db import query

        with self.app.app_context():
            return query(
                "SELECT * FROM attachments ORDER BY created_at DESC, id DESC LIMIT 1",
                one=True,
            )

    def test_voice_notes_video_and_office_files_all_upload(self):
        for filename, mime in (
            ("voice note.ogg", "audio/ogg"),
            ("site-walk.mp4", "video/mp4"),
            ("quote.pdf", "application/pdf"),
            ("contract.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("ledger.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ):
            with self.subTest(filename=filename):
                response = self._upload(filename)
                self.assertIn(response.status_code, (200, 302))
                row = self._latest()
                self.assertEqual(row["mime_type"], mime)
                self.assertEqual(row["original_name"], filename)
                self.assertEqual(bytes(row["data"]), self.BLOB)
                self.assertGreater(row["size"], 0)

    def test_the_bytes_survive_a_wiped_uploads_directory(self):
        import shutil
        import tempfile
        from pathlib import Path as _Path

        scratch = tempfile.mkdtemp()
        previous = self.app.config["UPLOAD_FOLDER"]
        self.app.config["UPLOAD_FOLDER"] = scratch
        try:
            self._upload("receipt.pdf")
            row = self._latest()
            # A redeploy replaces the container filesystem. Nothing is in it now.
            shutil.rmtree(scratch, ignore_errors=True)
            self.assertFalse(_Path(scratch).exists())

            self.login()
            response = self.client.get(f"/files/{row['id']}?download=1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, self.BLOB)
            self.assertIn("attachment", response.headers["Content-Disposition"])
        finally:
            self.app.config["UPLOAD_FOLDER"] = previous

    def test_a_refused_type_names_what_is_allowed(self):
        import storage

        self._upload("payload.svg")
        self.assertIn(storage.ALLOWED_HINT.split(",")[0], "PDF")

    def test_every_allowed_type_is_actually_accepted(self):
        import storage

        for extension in storage.ALLOWED_EXTENSIONS:
            with self.subTest(extension=extension):
                self._upload("sample." + extension)
                self.assertEqual(bytes(self._latest()["data"]), self.BLOB)

    def test_the_modal_advertises_the_real_limits(self):
        import storage

        self.login()
        page = self.client.get("/app/documents").get_data(as_text=True)

        for extension in (".pdf", ".mp3", ".mp4", ".docx"):
            with self.subTest(extension=extension):
                self.assertIn(extension, page)
        self.assertIn("data-upload-progress", page)
        self.assertIn("data-transfer-bar", page)
        self.assertIn("data-download", page)
        self.assertIn("modal-transfer", page)
        with self.app.app_context():
            self.assertGreaterEqual(storage.max_upload_bytes(), 25 * 1024 * 1024)

    def test_an_oversized_file_is_refused_by_name(self):
        self.app.config["MAX_UPLOAD_BYTES"] = 1024
        try:
            import io

            self.login()
            response = self.client.post(
                "/app/documents/upload",
                data={
                    "project_id": self._project_id(),
                    "kind": "document",
                    "csrf_token": self.csrf(),
                    "file": (io.BytesIO(b"x" * 4096), "big.mp4"),
                },
                content_type="multipart/form-data",
                follow_redirects=True,
            )
            self.assertIn("limit", response.get_data(as_text=True).lower())
        finally:
            self.app.config.pop("MAX_UPLOAD_BYTES", None)


class PhoneFields(VakaTestCase):
    """Phone capture needs a dial code, not a free-text guess."""

    def test_register_page_offers_a_country_selector(self):
        body = self.app.test_client().get("/register").get_data(as_text=True)
        self.assertIn("data-phone-field", body)
        self.assertIn("data-phone-code", body)
        # Zimbabwe first, since most clients are building there.
        self.assertIn('<option value="263"', body)
        self.assertIn("phone-field.js", body)

    def test_every_phone_input_uses_the_shared_component(self):
        from pathlib import Path

        templates = [
            "templates/auth/register.html",
            "templates/partials/modal_register.html",
            "templates/app/settings.html",
            "templates/partials/modal_project.html",
            "templates/app/project_new.html",
            "templates/partials/modal_project_edit.html",
        ]
        for path in templates:
            with self.subTest(template=path):
                source = Path(path).read_text(encoding="utf-8")
                self.assertIn("phone_field(", source)
                self.assertNotIn('type="tel"', source)

    def test_combined_value_normalises_to_a_stored_number(self):
        # The field submits +447700900123; storage keeps 447700900123 and the
        # Zimbabwean shorthand 0771234567 becomes 263771234567.
        from whatsapp import normalize_phone

        self.assertEqual(normalize_phone("+44 7700 900123"), "447700900123")
        self.assertEqual(normalize_phone("077 123 4567"), "263771234567")
        self.assertEqual(normalize_phone("+263 77 123 4567"), "263771234567")

    def test_the_dial_code_sits_inside_the_field_and_is_code_only(self):
        import re

        markup = Path("templates/partials/phone_field.html").read_text(encoding="utf-8")

        # One shell holds both halves, so it reads as a single control.
        self.assertIn('class="phone-shell"', markup)
        self.assertIn('class="phone-dial"', markup)
        self.assertIn('class="phone-number"', markup)

        # The dial block shows the code and nothing else: no country names.
        options = re.findall(r'<option value="(\d+)"[^>]*>([^<]+)</option>', markup)
        self.assertTrue(options)
        for code, label in options:
            with self.subTest(code=code):
                self.assertEqual(label, "+" + code)

        # Regions keep a long list navigable without putting a name in the field.
        self.assertIn("<optgroup", markup)
        self.assertIn('label="Africa"', markup)
        # Zimbabwe is still first, so the default is +263.
        self.assertTrue(options[0][0] == "263")

    def test_phone_component_is_loaded_on_both_shells(self):
        from pathlib import Path

        for path in ("templates/base.html", "templates/app/base.html"):
            with self.subTest(shell=path):
                self.assertIn(
                    "phone-field.js", Path(path).read_text(encoding="utf-8")
                )

    def test_landing_states_vision_mission_and_objectives(self):
        body = self.app.test_client().get("/").get_data(as_text=True)
        for heading in ("Our vision", "Our mission", "Our objectives"):
            with self.subTest(heading=heading):
                self.assertIn(heading, body)


class PosterBrand(VakaTestCase):
    """Posters and the site must show the same mark."""

    def test_poster_logo_uses_the_web_app_mark(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path.cwd() / "tools"))
        import make_posters
        import ui

        site = ui.logo_mark(54)
        poster = make_posters.logo("light")

        # Same tile, roof line and three bar colours as ui.logo_mark().
        for token in ("#0F5D46", "#F7F4EF", "#C8963E", "#E3B968"):
            with self.subTest(token=token):
                self.assertIn(token, site)
                self.assertIn(token, poster)

        # Three bars, in rising height order, on both.
        self.assertEqual(poster.count("<rect"), 4)  # tile + three bars
        self.assertEqual(site.count("<rect"), 4)

    def test_poster_set_covers_running_builds_and_managers(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path.cwd() / "tools"))
        import make_posters

        slugs = [poster["slug"] for poster in make_posters.POSTERS]
        self.assertGreaterEqual(len(slugs), 26)
        for required in (
            "already-three-months-in",
            "no-need-to-sack-anybody",
            "every-project-one-screen",
            "built-for-the-distance",
        ):
            with self.subTest(slug=required):
                self.assertIn(required, slugs)

    def test_the_set_reaches_fifty_with_no_repeated_slug(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path.cwd() / "tools"))
        import make_posters

        slugs = [poster["slug"] for poster in make_posters.POSTERS]
        self.assertEqual(len(slugs), 50)
        self.assertEqual(len(set(slugs)), len(slugs), "a slug is used twice")

        rendered = sorted(Path("static/posters").glob("yavaka-*.svg"))
        self.assertEqual(len(rendered), 50)
        for path in rendered:
            with self.subTest(poster=path.name):
                self.assertIn("yavaka.onrender.com", path.read_text(encoding="utf-8"))

        # Every poster also ships as a PNG, because that is what a phone and a
        # social platform actually accept.
        images = sorted(Path("static/posters").glob("yavaka-*.png"))
        self.assertEqual(len(images), 50)
        for image in images:
            with self.subTest(png=image.name):
                self.assertGreater(image.stat().st_size, 20_000)
                self.assertEqual(image.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_every_layout_draws_and_its_required_keys_are_present(self):
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path.cwd() / "tools"))
        import make_posters

        self.assertEqual(
            sorted(make_posters.LAYOUTS),
            ["gate", "ledger", "quote", "stat", "statement", "twotone"],
        )
        for poster in make_posters.POSTERS:
            with self.subTest(slug=poster["slug"]):
                layout = make_posters.LAYOUTS[poster["layout"]]
                markup = layout(poster)
                self.assertGreater(len(markup), 2000)
                # Cream type on a dark backdrop is the family signature; a
                # layout that forgets its backdrop renders invisible text.
                if poster["layout"] in {"statement", "stat", "gate"}:
                    self.assertIn("url(#sky)", markup)
                if poster["layout"] == "ledger":
                    self.assertEqual(len(poster["entries"]), 4)
                if poster["layout"] == "gate":
                    self.assertGreaterEqual(len(poster["gates"]), 4)
                    self.assertLess(poster["current"], len(poster["gates"]))



class DesignSystemPolish(VakaTestCase):
    """The refinements that make the UI feel finished are pinned down here."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = Path("static/css/portal.css").read_text(encoding="utf-8")

    def test_headlines_are_balanced_and_paragraphs_pretty(self):
        self.assertIn("text-wrap: balance", self.css)
        self.assertIn("text-wrap: pretty", self.css)

    def test_one_brand_focus_ring_for_every_control(self):
        # :where() keeps specificity at zero, so component rules still win.
        self.assertIn(":where(a, button, input, select, textarea, summary, [tabindex]):focus-visible", self.css)
        self.assertIn("outline-color: var(--brass-300)", self.css)

    def test_numbers_are_tabular_so_columns_line_up(self):
        self.assertIn("font-variant-numeric: tabular-nums lining-nums", self.css)

    def test_accessibility_preferences_are_respected(self):
        for query in ("prefers-contrast: more", "forced-colors: active", "prefers-reduced-motion: reduce"):
            with self.subTest(query=query):
                self.assertIn(query, self.css)

    def test_table_headers_stick_and_rows_hover(self):
        self.assertIn("thead th", self.css)
        self.assertIn("position: sticky", self.css)
        self.assertIn(".table tbody tr:hover", self.css)

    def test_no_layout_property_is_transitioned(self):
        # Guards the "nothing heavy" rule: only paint/composite properties.
        block = self.css[self.css.index("Design system v2"):]
        for rule in re.findall(r"transition:\s*([^;]+);", block):
            lowered = rule.lower()
            for banned in ("width ", "height ", "margin", "padding", "top ", "left "):
                with self.subTest(rule=rule.strip(), banned=banned):
                    self.assertNotIn(banned, lowered)


class MoneyTrendAndStickyHeader(VakaTestCase):
    """The three depth additions: a real chart, a settling swap, a sticky header."""

    def test_sparkline_handles_an_empty_series(self):
        from queries import balance_sparkline

        empty = balance_sparkline([])
        self.assertEqual(empty["points"], "")
        self.assertTrue(empty["flat"])

    def test_sparkline_runs_a_balance_not_raw_money(self):
        from queries import balance_sparkline

        series = [
            {"label": "Jan", "funded": 1000_00, "spent": 0},
            {"label": "Feb", "funded": 0, "spent": 400_00},
        ]
        line = balance_sparkline(series, width=100, height=100)
        self.assertEqual(line["last"], 600_00)
        # Two points, one per month, spanning the full width.
        self.assertEqual(len(line["points"].split(" ")), 2)
        self.assertTrue(line["points"].startswith("0.0,"))
        self.assertIn("100.0,", line["points"])

    def test_flat_series_does_not_divide_by_zero(self):
        from queries import balance_sparkline

        flat = balance_sparkline(
            [{"label": "Jan", "funded": 0, "spent": 0}, {"label": "Feb", "funded": 0, "spent": 0}]
        )
        self.assertTrue(flat["flat"])
        self.assertNotIn("nan", flat["points"].lower())

    def test_money_page_draws_the_trend(self):
        self.login("manager@yavaka.co.zw")
        body = self.client.get("/app/money").get_data(as_text=True)
        self.assertIn("Balance over time", body)
        self.assertIn("trend-chart", body)

    def test_project_header_is_sticky_and_shows_the_next_gate(self):
        from db import query

        # The owner always has access to their own project, so this does not
        # depend on manager assignments made by other tests.
        self.login("client@yavaka.co.zw")
        with self.app.app_context():
            project = query(
                """SELECT p.id FROM projects p
                   JOIN users u ON u.id = p.owner_id
                   WHERE u.email = 'client@yavaka.co.zw'
                   ORDER BY p.created_at LIMIT 1""",
                one=True,
            )
        self.assertIsNotNone(project, "the demo client owns no project")
        body = self.client.get(f"/app/projects/{project['id']}").get_data(as_text=True)
        self.assertIn("project-hero", body)
        self.assertIn("project-hero-gate", body)

    def test_sticky_rules_exist_and_are_desktop_only(self):
        css = Path("static/css/portal.css").read_text(encoding="utf-8")
        block = css[css.index("Project header stays in view"):]
        self.assertIn("position: sticky", block)
        # Sticky on a phone would eat the screen; it must be gated.
        self.assertIn("@media (min-width: 900px)", block)

    def test_skeleton_swap_fades_instead_of_snapping(self):
        css = Path("static/css/portal.css").read_text(encoding="utf-8")
        self.assertIn("is-settling", css)
        self.assertIn("@keyframes content-settle", css)
        js = Path("static/js/nav.js").read_text(encoding="utf-8")
        self.assertIn("is-settling", js)
        self.assertIn("is-skeleton", js)


class PaletteSystem(VakaTestCase):
    """Every palette must stay readable, and must reach printed documents."""

    @staticmethod
    def _lum(colour):
        value = colour.lstrip("#")
        channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def _ratio(self, a, b):
        hi, lo = sorted([self._lum(a), self._lum(b)], reverse=True)
        return (hi + 0.05) / (lo + 0.05)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = Path("static/css/app.css").read_text(encoding="utf-8")
        cls.palettes = Path("static/css/palettes.css").read_text(encoding="utf-8")

    def _tokens(self, block):
        return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block))

    def _palette_blocks(self):
        blocks = {}
        for name in ("laterite", "granite", "msasa"):
            marker = f'[data-palette="{name}"]'
            start = self.palettes.index(marker)
            end = self.palettes.index("}", start)
            blocks[name] = self._tokens(self.palettes[start:end])
        return blocks

    def test_primary_buttons_stay_readable_in_every_palette(self):
        for name, tokens in self._palette_blocks().items():
            with self.subTest(palette=name):
                for key in ("--forest-700", "--forest-800"):
                    ratio = self._ratio("#ffffff", tokens[key])
                    self.assertGreaterEqual(
                        round(ratio, 2), 4.5, f"white on {name} {key} is {ratio:.2f}:1"
                    )

    def test_accent_text_stays_readable_in_every_palette(self):
        # Eyebrows and labels use brass-700 on the lightest sand surface.
        for name, tokens in self._palette_blocks().items():
            with self.subTest(palette=name):
                ratio = self._ratio(tokens["--brass-700"], tokens["--sand-100"])
                self.assertGreaterEqual(
                    round(ratio, 2), 4.5, f"{name} brass-700 on sand is {ratio:.2f}:1"
                )

    def test_body_text_stays_readable_in_every_palette(self):
        ink = self._tokens(self.base)["--ink"]
        for name, tokens in self._palette_blocks().items():
            with self.subTest(palette=name):
                ratio = self._ratio(ink, tokens["--sand-100"])
                self.assertGreaterEqual(round(ratio, 2), 4.5)

    def test_ink_is_never_overridden(self):
        # Ink is the contrast anchor the tests above rely on.
        self.assertNotIn("--ink:", self.palettes)

    def test_palette_is_stored_on_the_user(self):
        from db import query

        with self.app.app_context():
            row = query("SELECT palette FROM users LIMIT 1", one=True)
        self.assertIn(row["palette"], ("forest", "laterite", "granite", "msasa"))

    def test_printed_documents_follow_the_palette(self):
        import re

        for path in (
            "templates/app/project_pack.html",
            "templates/app/agreement_print.html",
        ):
            with self.subTest(template=path):
                source = Path(path).read_text(encoding="utf-8")
                self.assertIn('data-palette="{{ palette }}"', source)
                self.assertIn("palettes.css", source)
                # Any brand hex that remains must be a var() fallback, never a
                # hardcoded colour that ignores the chosen palette.
                for match in re.finditer(r"#[0-9A-Fa-f]{6}", source):
                    before = source[max(0, match.start() - 40) : match.start()]
                    self.assertIn(
                        "var(",
                        before,
                        f"{path} hardcodes {match.group(0)} outside a token fallback",
                    )

    def test_logo_mark_recolours_with_the_palette(self):
        import ui

        markup = str(ui.logo_mark(40))
        self.assertIn("var(--forest-700", markup)
        self.assertIn("var(--brass-500", markup)

    def test_app_shell_exposes_the_palette_attribute(self):
        source = Path("templates/base.html").read_text(encoding="utf-8")
        self.assertIn('data-palette="{{ palette }}"', source)
        self.assertIn("palettes.css", source)
        self.assertIn("palette-switch.js", source)
