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
                "email": "client@vaka.co.zw",
                "password": "Vaka2026!",
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

        self.assertNotIn("Vaka2026!", body)
        self.assertNotIn("client@vaka.co.zw", body)

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
                "email": "client@vaka.co.zw",
                "password": "Vaka2026!",
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
                "email": "client@vaka.co.zw",
                "password": password,
                "csrf_token": self.csrf(),
            },
        )

    def test_repeated_successful_logins_are_never_throttled(self):
        for _ in range(12):
            self.assertEqual(self._post("Vaka2026!").status_code, 302)

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
            # Export defaults to the newest project, so target that one explicitly.
            project = query("SELECT id FROM projects ORDER BY created_at DESC LIMIT 1", one=True)
            user = query("SELECT id FROM users WHERE role = 'client' LIMIT 1", one=True)
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
        self.login("admin@vaka.co.zw")
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

    def test_public_pages_carry_the_dialog_but_register_page_does_not(self):
        for path in ["/", "/login", "/suppliers"]:
            page = self.client.get(path).get_data(as_text=True)
            self.assertIn('id="modal-register"', page, path)
            self.assertIn('data-modal-open="modal-register"', page, path)

        register = self.client.get("/register").get_data(as_text=True)
        self.assertNotIn('id="modal-register"', register)

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

    def test_successful_signup_returns_a_redirect_instead_of_a_page(self):
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
        self.assertEqual(payload["redirect"], "/app/projects/new")
        # The dialog hands off to a real page load, so the welcome flash must
        # survive the hop and land on the destination page.
        landing = client.get("/app/projects/new")
        self.assertEqual(landing.status_code, 200)
        self.assertIn(b"Welcome to YaVaKa", landing.data)

    def test_signup_without_javascript_still_redirects(self):
        response = self.client.post(
            "/register",
            data={"csrf_token": self._csrf(), "name": "Plain Signup",
                  "email": f"plain-{os.urandom(4).hex()}@example.com",
                  "password": "Str0ngPassw0rd!", "terms": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/app/projects/new", response.headers["Location"])


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
