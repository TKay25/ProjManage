"""SQLite access layer for YaVaKa (standard library only)."""

import sqlite3
import uuid
from datetime import datetime, timezone

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'client',
  phone TEXT,
  country TEXT,
  avatar_color TEXT NOT NULL DEFAULT '#0F5D46',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  manager_id TEXT REFERENCES users(id),
  city TEXT DEFAULT 'Harare',
  suburb TEXT,
  stand_number TEXT,
  client_email TEXT,
  client_whatsapp TEXT,
  status TEXT NOT NULL DEFAULT 'planning',
  budget_cents INTEGER NOT NULL DEFAULT 0,
  start_date TEXT,
  target_date TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_manager ON projects(manager_id);

CREATE TABLE IF NOT EXISTS stages (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  name TEXT NOT NULL,
  position INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  budget_cents INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  started_at TEXT,
  completed_at TEXT,
  UNIQUE(project_id, key)
);
CREATE INDEX IF NOT EXISTS idx_stages_project ON stages(project_id);

CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  category TEXT,
  stage_key TEXT,
  description TEXT NOT NULL,
  method TEXT DEFAULT 'BANK_TRANSFER',
  reference TEXT,
  occurred_at TEXT NOT NULL,
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_project ON transactions(project_id);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(occurred_at);

CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
  transaction_id TEXT REFERENCES transactions(id) ON DELETE CASCADE,
  uploader_id TEXT NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL DEFAULT 'receipt',
  filename TEXT NOT NULL,
  original_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_att_project ON attachments(project_id);
CREATE INDEX IF NOT EXISTS idx_att_tx ON attachments(transaction_id);

CREATE TABLE IF NOT EXISTS agreements (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  type TEXT NOT NULL DEFAULT 'build_contract',
  title TEXT NOT NULL,
  contract_value_cents INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'USD',
  scope TEXT NOT NULL,
  terms TEXT NOT NULL,
  payment_schedule TEXT NOT NULL DEFAULT '[]',
  client_name TEXT NOT NULL,
  client_signature TEXT,
  signed_at TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agreements_project ON agreements(project_id);

CREATE TABLE IF NOT EXISTS suppliers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  city TEXT NOT NULL,
  website TEXT,
  phone TEXT,
  address TEXT,
  description TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '',
  verified INTEGER NOT NULL DEFAULT 0,
  position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS whatsapp_contacts (
  id TEXT PRIMARY KEY,
  phone TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  user_id TEXT REFERENCES users(id),
  project_id TEXT REFERENCES projects(id),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wa_contact_user ON whatsapp_contacts(user_id);

CREATE TABLE IF NOT EXISTS whatsapp_messages (
  id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL REFERENCES whatsapp_contacts(id) ON DELETE CASCADE,
  direction TEXT NOT NULL,
  body TEXT NOT NULL,
  intent TEXT,
  status TEXT NOT NULL DEFAULT 'received',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wa_msg_contact ON whatsapp_messages(contact_id, created_at);

CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id),
  project_id TEXT,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_events(project_id, created_at);

CREATE TABLE IF NOT EXISTS notification_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  channel TEXT NOT NULL,
  recipient TEXT NOT NULL,
  subject TEXT,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  claimed_at TEXT,
  UNIQUE(event_key, channel)
);
CREATE INDEX IF NOT EXISTS idx_notification_pending
  ON notification_outbox(status, created_at);
"""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        connection = sqlite3.connect(
            current_app.config["DATABASE"],
            timeout=15,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        g.db = connection
    return g.db


def close_db(_exception=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    connection = get_db()
    connection.executescript(SCHEMA)
    connection.commit()
    run_migrations(connection)


def run_migrations(connection):
    """Idempotent data migrations, tracked with PRAGMA user_version.

    Runs on every boot, so a deploy can move existing rows. Anything here must
    be safe to run against a fresh database as well as a populated one.
    """
    version = connection.execute("PRAGMA user_version").fetchone()[0]

    if version < 1:
        # The brand moved from Vaka to YaVaKa. Move the demo accounts with it,
        # otherwise the sign-in page would advertise addresses and a password
        # that no longer exist. OR IGNORE skips a row whose new address is
        # already taken.
        connection.execute(
            "UPDATE OR IGNORE users "
            "SET email = replace(email, '@vaka.co.zw', '@yavaka.co.zw') "
            "WHERE email LIKE '%@vaka.co.zw'"
        )

        # Imported here to keep db.py free of an import cycle at module load.
        from auth import hash_password
        from seed import DEMO_ACCOUNTS, DEMO_PASSWORD

        for address in DEMO_ACCOUNTS:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE email = ?",
                (hash_password(DEMO_PASSWORD), address),
            )

        connection.execute("PRAGMA user_version = 1")

    if version < 2:
        # Archiving hides a project from the pickers and the list without
        # touching its ledger, so the money history stays intact.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
        if "archived_at" not in columns:
            connection.execute("ALTER TABLE projects ADD COLUMN archived_at TEXT")
        connection.execute("PRAGMA user_version = 2")

    if version < 3:
        # Workspaces group several projects under one banner. They are an
        # organisational filter: project-level permissions still decide who can
        # see a build.
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workspace_owner ON workspaces(owner_id);
            """
        )

        columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
        if "workspace_id" not in columns:
            connection.execute("ALTER TABLE projects ADD COLUMN workspace_id TEXT")

        # Give every existing project owner a workspace and adopt their builds.
        connection.execute(
            """INSERT INTO workspaces (id, name, owner_id, created_at)
               SELECT lower(hex(randomblob(10))), COALESCE(u.name, 'My') || ' workspace',
                      p.owner_id, '2026-01-01T00:00:00+00:00'
               FROM (SELECT DISTINCT owner_id FROM projects WHERE workspace_id IS NULL) p
               JOIN users u ON u.id = p.owner_id"""
        )
        connection.execute(
            """UPDATE projects SET workspace_id = (
                 SELECT w.id FROM workspaces w
                 WHERE w.owner_id = projects.owner_id
                 ORDER BY w.created_at LIMIT 1
               )
               WHERE workspace_id IS NULL"""
        )
        connection.execute("PRAGMA user_version = 3")

    # Always run: adopts any project that has no workspace yet, including rows
    # created by the seed after the version bump above. Idempotent.
    connection.execute(
        """INSERT INTO workspaces (id, name, owner_id, created_at)
           SELECT lower(hex(randomblob(10))), COALESCE(u.name, 'My') || ' workspace',
                  p.owner_id, '2026-01-01T00:00:00+00:00'
           FROM (SELECT DISTINCT owner_id FROM projects WHERE workspace_id IS NULL) p
           JOIN users u ON u.id = p.owner_id"""
    )
    connection.execute(
        """UPDATE projects SET workspace_id = (
             SELECT w.id FROM workspaces w
             WHERE w.owner_id = projects.owner_id
             ORDER BY w.created_at LIMIT 1
           )
           WHERE workspace_id IS NULL"""
    )

    if version < 4:
        # A file can belong to a build stage as well as a project, so a
        # statutory approval sits next to the stage it satisfies and still
        # shows up in the document vault.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(attachments)")}
        if "stage_key" not in columns:
            connection.execute("ALTER TABLE attachments ADD COLUMN stage_key TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_att_stage ON attachments(project_id, stage_key)"
        )
        connection.execute("PRAGMA user_version = 4")

    if version < 5:
        connection.execute("PRAGMA user_version = 5")

    if version < 6:
        # Project codes are now sequential from the first project: YVK-0001,
        # YVK-0002, ... Renumbered once, in creation order.
        rows = connection.execute(
            "SELECT id FROM projects ORDER BY created_at, rowid"
        ).fetchall()
        for index, row in enumerate(rows, start=1):
            connection.execute(
                "UPDATE projects SET code = ? WHERE id = ?",
                (f"YVK-{index:04d}", row[0]),
            )
        connection.execute("PRAGMA user_version = 6")

    if version < 7:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(notification_outbox)")
        }
        if "claimed_at" not in columns:
            connection.execute("ALTER TABLE notification_outbox ADD COLUMN claimed_at TEXT")
        connection.execute(
            """UPDATE notification_outbox SET status = 'pending'
               WHERE status = 'sending' AND claimed_at IS NULL"""
        )
        connection.execute("PRAGMA user_version = 7")

    if version < 8:
        # A build manager can run a project for a client who has no YaVaKa
        # account yet. Keep that client's email and WhatsApp on the project so
        # updates and the weekly digest have somewhere to go.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
        if "client_email" not in columns:
            connection.execute("ALTER TABLE projects ADD COLUMN client_email TEXT")
        if "client_whatsapp" not in columns:
            connection.execute("ALTER TABLE projects ADD COLUMN client_whatsapp TEXT")
        connection.execute("PRAGMA user_version = 8")

    if version < 9:
        # The assistant now offers tap-to-send quick replies, so the old
        # "Reply BALANCE/STATUS" trailers are noise. Strip them from messages
        # that are already stored.
        for trailer in (
            "\n\nReply *STATUS* for the current stage.",
            "\n\nReply *BALANCE* for the money position.",
            "\n\nReply *BALANCE* to see the updated position.",
        ):
            connection.execute(
                "UPDATE whatsapp_messages SET body = REPLACE(body, ?, '') WHERE body LIKE ?",
                (trailer, f"%{trailer}%"),
            )
        connection.execute("PRAGMA user_version = 9")

    if version < 10:
        # Display preferences live on the user, not in localStorage, so a
        # compact ledger follows the person across devices. The defaults match
        # the look the app already had.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        if "density" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN density TEXT NOT NULL DEFAULT 'comfortable'"
            )
        if "page_size" not in columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN page_size INTEGER NOT NULL DEFAULT 25"
            )
        connection.execute("PRAGMA user_version = 10")

    if version < 11:
        # Per-recipient notifications, derived from audit events. A client sees
        # what their build manager did without reading the raw log, and read
        # state is per person, not per project.
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS notifications (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
              event_id TEXT,
              actor_id TEXT REFERENCES users(id),
              action TEXT NOT NULL,
              title TEXT NOT NULL,
              body TEXT,
              href TEXT,
              created_at TEXT NOT NULL,
              read_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_user
              ON notifications(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_notifications_unread
              ON notifications(user_id, read_at);
            """
        )
        connection.execute("PRAGMA user_version = 11")

    if version < 12:
        # A build manager can be attached to a client, not just to one project:
        # the link grants access to every project that client owns, including
        # ones created later. That is what makes an invitation possible before
        # the client has created anything.
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS manager_links (
              id TEXT PRIMARY KEY,
              client_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              manager_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              created_by TEXT REFERENCES users(id),
              created_at TEXT NOT NULL,
              UNIQUE(client_id, manager_id)
            );
            CREATE INDEX IF NOT EXISTS idx_manager_links_client ON manager_links(client_id);
            CREATE INDEX IF NOT EXISTS idx_manager_links_manager ON manager_links(manager_id);

            CREATE TABLE IF NOT EXISTS invitations (
              id TEXT PRIMARY KEY,
              token TEXT NOT NULL UNIQUE,
              inviter_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              client_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
              email TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'manager',
              status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL,
              accepted_at TEXT,
              accepted_by TEXT REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_invitations_email ON invitations(email, status);
            CREATE INDEX IF NOT EXISTS idx_invitations_client ON invitations(client_id, status);
            """
        )
        connection.execute("PRAGMA user_version = 12")

    # Always run: adopt the current prefix. Rewriting only old-prefix rows keeps
    # this safe to repeat, and catches codes that arrive from a restored backup.
    connection.execute(
        "UPDATE OR IGNORE projects SET code = 'YVK-' || substr(code, 4) "
        "WHERE code LIKE 'VK-%' AND code NOT LIKE 'YVK-%'"
    )

    # Always run: an assignment made before team links existed still means the
    # manager works with that client, so keep links in step with assignments.
    connection.execute(
        """INSERT OR IGNORE INTO manager_links
               (id, client_id, manager_id, created_by, created_at)
           SELECT lower(hex(randomblob(10))), p.owner_id, p.manager_id, p.owner_id, ?
             FROM projects p
            WHERE p.manager_id IS NOT NULL
              AND p.owner_id <> p.manager_id
              AND EXISTS (SELECT 1 FROM users u WHERE u.id = p.owner_id)
              AND EXISTS (SELECT 1 FROM users m WHERE m.id = p.manager_id)
            GROUP BY p.owner_id, p.manager_id""",
        (now_iso(),),
    )

    connection.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


def query(sql: str, args=(), one: bool = False):
    """Return rows as plain dicts so templates and JSON stay simple."""
    cursor = get_db().execute(sql, args)
    rows = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, args=()) -> int:
    connection = get_db()
    cursor = connection.execute(sql, args)
    connection.commit()
    last_id = cursor.lastrowid
    cursor.close()
    return last_id


def executescript(script: str):
    connection = get_db()
    connection.executescript(script)
    connection.commit()


def new_id() -> str:
    return uuid.uuid4().hex[:20]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def touch_project(project_id: str):
    execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now_iso(), project_id))


def log_event(user_id, project_id, action, detail=""):
    event_id = new_id()
    execute(
        "INSERT INTO audit_events (id, user_id, project_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (event_id, user_id, project_id, action, detail, now_iso()),
    )

    # The audit log is the record; notifications are the "tell the people who
    # own this build" side effect. Imported here to keep db.py import-cycle free.
    import updates

    updates.record(user_id, project_id, action, detail, event_id=event_id)
