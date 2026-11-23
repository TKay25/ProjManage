"""The conversation: what it reads, what it writes, and what it refuses."""

import os
import sys
import unittest
from pathlib import Path

import chat
import chat_nlu
from db import execute, new_id, now_iso, query

# `discover -s tests` already puts this folder on the path; naming the module
# directly does not, so make both ways work.
sys.path.insert(0, str(Path(__file__).parent))
from test_app import APP, VakaTestCase  # noqa: E402

PROPERTY_EMAIL = "rentals@yavaka.co.zw"
PASSWORD = "YaVaKa2026!"


class Talk(VakaTestCase):
    """Shared helpers for talking to the two conversations."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = APP

    def setUp(self):
        super().setUp()
        # Every test starts with an empty transcript, so a half-finished flow
        # left by one test can never answer for the next.
        with self.app.app_context():
            execute("DELETE FROM chat_events")
            execute("DELETE FROM chat_threads")

    def property_login(self, email=PROPERTY_EMAIL, password=PASSWORD):
        token = self.csrf()
        return self.client.post(
            "/login",
            data={"email": email, "password": password, "csrf_token": token, "portal": "property"},
            follow_redirects=True,
        )

    def say(self, text, *, portal="project"):
        path = "/app/chat" if portal == "project" else "/property/chat"
        response = self.client.post(
            path,
            data={"text": text, "csrf_token": self.csrf()},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
        return response.get_json()["html"]

    def choose_project(self, name="Greendale Family Home"):
        """Select a build the way the page's switcher does, then return its id."""
        project_id = self.project_id(name)
        self.client.get("/app")
        response = self.client.post(
            "/app/chat/project",
            data={"project": project_id, "csrf_token": self.csrf()},
            headers={"X-Requested-With": "fetch", "Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
        return project_id

    def project_id(self, name="Greendale Family Home"):
        with self.app.app_context():
            row = query("SELECT id FROM projects WHERE name = ?", (name,), one=True)
        self.assertIsNotNone(row, f"seed project {name} is missing")
        return row["id"]

    def property_row(self):
        """The portfolio's first property — the one a named sentence must hit."""
        with self.app.app_context():
            row = query(
                "SELECT id, name FROM properties ORDER BY created_at LIMIT 1", one=True
            )
        self.assertIsNotNone(row, "seed property is missing")
        return row

    def count(self, sql, args=()):
        with self.app.app_context():
            return query(sql, args, one=True)["count"]


class HomeIsTheConversation(Talk):
    def test_the_build_home_opens_a_conversation(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn("data-chat", page)
        self.assertIn("chat-composer", page)
        self.assertIn("All commands", page)
        self.assertIn("Record money", page)

    def test_the_property_home_opens_its_own_conversation(self):
        self.property_login()
        page = self.client.get("/property").get_data(as_text=True)
        self.assertIn("data-chat", page)
        self.assertIn("Your portfolio", page)

    def test_the_home_page_does_not_repeat_the_floating_assistant(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        self.assertNotIn("data-aide-open", page)
        # The fifth tab is the rest of the workspace, not a second assistant.
        self.assertIn('data-drawer-open', page)
        self.assertIn(">More<", page)

    def test_the_screens_are_still_reachable(self):
        self.login()
        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn('href="/app/dashboard"', page)
        self.assertIn('href="/app/money"', page)


class ReadingAndWriting(Talk):
    def test_a_sentence_is_understood_before_anything_is_written(self):
        self.login()
        project_id = self.choose_project()
        before = self.count(
            "SELECT COUNT(*) AS count FROM transactions WHERE project_id = ?", (project_id,)
        )

        html = self.say("spent 340 on cement")
        self.assertIn("$340.00", html)
        self.assertIn("cement", html.lower())
        self.assertEqual(
            self.count(
                "SELECT COUNT(*) AS count FROM transactions WHERE project_id = ?", (project_id,)
            ),
            before,
            "nothing may be written before the confirmation",
        )

        html = self.say("yes")
        self.assertIn("recorded", html)
        with self.app.app_context():
            row = query(
                """SELECT * FROM transactions WHERE project_id = ?
                    ORDER BY created_at DESC LIMIT 1""",
                (project_id,),
                one=True,
            )
        self.assertEqual(row["type"], "EXPENSE")
        self.assertEqual(row["amount_cents"], 34000)
        self.assertIn("cement", row["description"].lower())
        self.assertEqual(row["category"], "materials")

    def test_cancelling_writes_nothing(self):
        self.login()
        project_id = self.choose_project()
        before = self.count(
            "SELECT COUNT(*) AS count FROM transactions WHERE project_id = ?", (project_id,)
        )
        self.say("spent 340 on cement")
        html = self.say("cancel")
        self.assertIn("Cancelled", html)
        self.assertEqual(
            self.count(
                "SELECT COUNT(*) AS count FROM transactions WHERE project_id = ?", (project_id,)
            ),
            before,
        )

    def test_a_correction_changes_the_figure_before_it_is_recorded(self):
        self.login()
        project_id = self.choose_project()
        self.say("spent 340 on cement")
        self.say("actually 400")
        self.say("yes")
        with self.app.app_context():
            row = query(
                """SELECT * FROM transactions WHERE project_id = ?
                    ORDER BY created_at DESC LIMIT 1""",
                (project_id,),
                one=True,
            )
        self.assertEqual(row["amount_cents"], 40000)

    def test_money_in_is_recognised(self):
        self.login()
        project_id = self.choose_project()
        self.say("received $1,500 from the client")
        self.say("yes")
        with self.app.app_context():
            row = query(
                """SELECT * FROM transactions WHERE project_id = ?
                    ORDER BY created_at DESC LIMIT 1""",
                (project_id,),
                one=True,
            )
        self.assertEqual(row["type"], "FUNDING")
        self.assertEqual(row["amount_cents"], 150000)

    def test_one_sentence_can_carry_two_instructions(self):
        self.login()
        project_id = self.choose_project()
        audit_before = self.count(
            "SELECT COUNT(*) AS count FROM audit_events WHERE action = 'project.update'",
        )

        html = self.say("record 500 for cement and post an update that the slab is done")
        self.assertIn("$500.00", html)
        self.say("yes")  # records the money, then asks about the update
        html = self.say("yes")  # records the update
        self.assertIn("Update posted", html)

        with self.app.app_context():
            row = query(
                """SELECT * FROM transactions WHERE project_id = ?
                    ORDER BY created_at DESC LIMIT 1""",
                (project_id,),
                one=True,
            )
        self.assertEqual(row["amount_cents"], 50000)
        self.assertEqual(
            self.count("SELECT COUNT(*) AS count FROM audit_events WHERE action = 'project.update'"),
            audit_before + 1,
        )

    def test_undo_takes_the_entry_back(self):
        self.login()
        project_id = self.choose_project()
        self.say("spent 275 on transport")
        self.say("yes")
        self.assertEqual(
            self.count(
                """SELECT COUNT(*) AS count FROM transactions
                    WHERE project_id = ? AND amount_cents = 27500""",
                (project_id,),
            ),
            1,
        )
        html = self.say("undo that")
        self.assertIn("Removed", html)
        self.assertEqual(
            self.count(
                """SELECT COUNT(*) AS count FROM transactions
                    WHERE project_id = ? AND amount_cents = 27500""",
                (project_id,),
            ),
            0,
        )

    def test_a_question_is_answered_from_the_ledger(self):
        self.login()
        self.choose_project()
        self.say("spent 90 on cement")
        self.say("yes")
        html = self.say("How much have I spent on cement?")
        self.assertIn("$90.00", html)
        self.assertIn("cement", html.lower())

    def test_asking_never_writes_anything(self):
        self.login()
        project_id = self.choose_project()
        before = self.count(
            "SELECT COUNT(*) AS count FROM transactions WHERE project_id = ?", (project_id,)
        )
        self.say("How much have I spent?")
        self.say("What needs attention?")
        self.assertEqual(
            self.count(
                "SELECT COUNT(*) AS count FROM transactions WHERE project_id = ?", (project_id,)
            ),
            before,
        )

    def test_the_transcript_survives_a_reload(self):
        self.login()
        self.choose_project()
        self.say("spent 12 on a padlock")
        page = self.client.get("/app").get_data(as_text=True)
        self.assertIn("padlock", page)

    def test_a_post_without_a_token_is_refused(self):
        self.login()
        response = self.client.post("/app/chat", data={"text": "spent 10 on sand"})
        self.assertEqual(response.status_code, 400)

    def test_several_builds_with_no_selection_make_the_conversation_ask(self):
        """Writing to a guessed build would be worse than one extra question."""
        import auth

        email = f"multi-{os.urandom(4).hex()}@example.com"
        user_id = new_id()
        with self.app.app_context():
            execute(
                """INSERT INTO users (id, name, email, password_hash, role, avatar_color, created_at)
                   VALUES (?, 'Multi Builder', ?, ?, 'client', '#0F5D46', ?)""",
                (user_id, email, auth.hash_password(PASSWORD), now_iso()),
            )
            for index in (1, 2):
                execute(
                    """INSERT INTO projects (id, code, name, owner_id, city, status, budget_cents,
                                             created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'Harare', 'planning', 1000, ?, ?)""",
                    (
                        new_id(),
                        f"YVK-M{index}-{os.urandom(3).hex().upper()}",
                        f"Multi Build {index}",
                        user_id,
                        now_iso(),
                        now_iso(),
                    ),
                )
        self.addCleanup(self._drop_user_and_projects, user_id)

        self.login(email, PASSWORD)
        # The page normally pins the build it greeted with. Clear it, so this is
        # the "several builds, nothing chosen" case the question exists for.
        with self.app.app_context():
            execute("UPDATE chat_threads SET project_id = NULL WHERE user_id = ?", (user_id,))

        html = self.say("spent 100 on sand")
        self.assertIn("Which build?", html)
        self.assertIn("Multi Build 1", html)
        self.assertIn("Multi Build 2", html)

        with self.app.app_context():
            written = query(
                "SELECT COUNT(*) AS count FROM transactions WHERE project_id IN "
                "(SELECT id FROM projects WHERE owner_id = ?)",
                (user_id,),
                one=True,
            )["count"]
        self.assertEqual(written, 0, "asking must not write anything")

    def test_the_chosen_build_is_the_one_written_to(self):
        self.login()
        chosen = self.choose_project()
        self.say("spent 60 on nails")
        self.say("yes")
        with self.app.app_context():
            row = query(
                "SELECT project_id FROM transactions ORDER BY created_at DESC LIMIT 1", one=True
            )
        self.assertEqual(row["project_id"], chosen)

    def _drop_user_and_projects(self, user_id):
        with self.app.app_context():
            execute(
                "DELETE FROM chat_events WHERE thread_id IN "
                "(SELECT id FROM chat_threads WHERE user_id = ?)",
                (user_id,),
            )
            execute("DELETE FROM chat_threads WHERE user_id = ?", (user_id,))
            execute("DELETE FROM audit_events WHERE user_id = ?", (user_id,))
            execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
            execute("DELETE FROM workspaces WHERE owner_id = ?", (user_id,))
            execute("DELETE FROM projects WHERE owner_id = ?", (user_id,))
            execute("DELETE FROM users WHERE id = ?", (user_id,))


class PropertyConversation(Talk):
    def test_rent_is_receipted_through_the_conversation(self):
        self.property_login()
        row = self.property_row()
        before = self.count("SELECT COUNT(*) AS count FROM property_payments")

        html = self.say(f"tenant at {row['name']} paid 450 rent", portal="property")
        # The property, the amount and the invoice-free route are known; only
        # the method is still missing.
        self.assertIn("How was it paid", html)
        html = self.say("ecocash", portal="property")
        self.assertIn("$450.00", html)
        html = self.say("yes", portal="property")
        self.assertIn("Receipt", html)
        self.assertEqual(
            self.count("SELECT COUNT(*) AS count FROM property_payments"), before + 1
        )
        with self.app.app_context():
            payment = query(
                "SELECT * FROM property_payments ORDER BY created_at DESC LIMIT 1", one=True
            )
        self.assertEqual(payment["amount_cents"], 45000)
        self.assertEqual(payment["property_id"], row["id"])

    def test_a_property_cost_is_recorded_with_its_bucket(self):
        self.property_login()
        row = self.property_row()
        html = self.say(f"paid 90 for water at {row['name']}", portal="property")
        self.assertIn("$90.00", html)
        self.say("yes", portal="property")
        with self.app.app_context():
            expense = query(
                "SELECT * FROM property_expenses ORDER BY created_at DESC LIMIT 1", one=True
            )
        self.assertEqual(expense["amount_cents"], 9000)
        self.assertEqual(expense["category"], "water")
        self.assertEqual(expense["property_id"], row["id"])

    def test_the_two_doors_keep_separate_threads(self):
        self.login("admin@yavaka.co.zw")
        self.client.get("/app")
        with self.app.app_context():
            admin = query(
                "SELECT id FROM users WHERE email = ?", ("admin@yavaka.co.zw",), one=True
            )
            project_threads = query(
                "SELECT * FROM chat_threads WHERE user_id = ?", (admin["id"],)
            )
        self.assertEqual(len(project_threads), 1)
        self.assertEqual(project_threads[0]["portal"], "project")

        self.client.get("/property")
        with self.app.app_context():
            threads = query("SELECT * FROM chat_threads WHERE user_id = ?", (admin["id"],))
        self.assertEqual({row["portal"] for row in threads}, {"project", "property"})

    def test_a_build_account_cannot_open_the_property_conversation(self):
        self.login()
        response = self.client.post(
            "/property/chat",
            data={"text": "tenant paid 450 rent", "csrf_token": self.csrf()},
        )
        self.assertEqual(response.status_code, 403)


class Understanding(unittest.TestCase):
    """The language layer on its own — no database, no request."""

    def test_money_words(self):
        self.assertEqual(chat_nlu.parse_amount("spent 1.5k on fuel"), 150000)
        self.assertEqual(chat_nlu.parse_amount("paid twenty five thousand for bricks"), 2500000)
        self.assertEqual(chat_nlu.parse_amount("received $1,250.50"), 125050)
        self.assertEqual(chat_nlu.parse_amount("450 usd"), 45000)

    def test_two_numbers_prefer_the_one_next_to_the_money_word(self):
        self.assertEqual(chat_nlu.parse_amount("spent 340 on 2 bags of cement"), 34000)

    def test_a_question_is_never_an_instruction(self):
        project = {"id": "p1", "name": "Greendale Duplex", "code": "YVK-1"}
        context = chat_nlu.Context(projects=[project])
        self.assertEqual(
            chat_nlu.detect("how much have I spent on cement", context, portal="project"), []
        )
        self.assertTrue(chat_nlu.looks_like_question("what is my balance?"))

    def test_a_sentence_becomes_a_flow_with_its_slots_filled(self):
        project = {"id": "p1", "name": "Greendale Duplex", "code": "YVK-1"}
        intents = chat_nlu.detect(
            "spent 340 on cement at Greendale",
            chat_nlu.Context(projects=[project]),
            portal="project",
        )
        self.assertEqual(intents[0].kind, "record_money")
        self.assertEqual(intents[0].slots["amount"], 34000)
        self.assertEqual(intents[0].slots["type"], "EXPENSE")
        self.assertEqual(intents[0].slots["category"], "materials")
        self.assertEqual(intents[0].slots["project"], "p1")

    def test_a_stage_move_is_recognised(self):
        stages = [{"key": "foundation", "name": "Foundation"}, {"key": "roof", "name": "Roof"}]
        intents = chat_nlu.detect(
            "block the foundation because the sand never arrived",
            chat_nlu.Context(),
            portal="project",
            stages=stages,
        )
        self.assertEqual(intents[0].kind, "change_stage")
        self.assertEqual(intents[0].slots["stage"], "foundation")
        self.assertEqual(intents[0].slots["change"], "blocked")
        self.assertIn("sand", intents[0].slots["note"])

    def test_a_half_remembered_property_still_matches(self):
        rows = [{"id": "h1", "name": "12 Acacia Road, Avondale", "code": "PROP-1"}]
        intents = chat_nlu.detect(
            "receipt 450 rent for acacia", chat_nlu.Context(properties=rows), portal="property"
        )
        self.assertEqual(intents[0].kind, "receipt_rent")
        self.assertEqual(intents[0].slots["property"], "h1")

    def test_a_description_keeps_its_own_words_together(self):
        self.assertEqual(chat_nlu.split_clauses("sand and cement"), ["sand and cement"])

    def test_ordinary_purchases_land_in_the_right_bucket(self):
        self.assertEqual(chat_nlu.guess_project_category("spent 25 on a padlock"), "materials")
        self.assertEqual(chat_nlu.guess_project_category("paid the crew 200"), "labour")
        self.assertEqual(chat_nlu.guess_project_category("40 for diesel"), "transport")
        self.assertEqual(chat_nlu.guess_project_category("hired a mixer for 60"), "equipment")
        self.assertEqual(chat_nlu.guess_property_category("paid for a burst pipe"), "repairs")
        self.assertEqual(chat_nlu.guess_property_category("council rates"), "rates")

    def test_navigation_names_a_screen(self):
        found = chat_nlu.detect_navigation("open documents", chat.OPEN_ACTIONS["project"])
        self.assertEqual(found["href"], "/app/documents")

    def test_an_ordinal_picks_a_choice(self):
        self.assertEqual(chat_nlu.ordinal_index("the second one", 4), 1)
        self.assertEqual(chat_nlu.ordinal_index("last", 4), 3)


if __name__ == "__main__":
    unittest.main()
