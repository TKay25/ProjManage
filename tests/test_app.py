"""Smoke tests for YaVaKa. Run with: python -m unittest discover -s tests -v"""

import os
import re
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


class PasswordReset(VakaTestCase):
    EMAIL = "client@yavaka.co.zw"

    def setUp(self):
        super().setUp()
        from db import execute, query
        import routes_auth

        routes_auth.ATTEMPTS.clear()
        with self.app.app_context():
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
        self.assertIn("+263 77 123 4567", page)
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
        import routes_auth

        routes_auth.ATTEMPTS.clear()

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
        self.assertIn("Receipts to chase", page)

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

    def test_the_topbar_and_sidebar_link_to_attention(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)

        self.assertIn('class="icon-btn topbar-alert"', page)
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
