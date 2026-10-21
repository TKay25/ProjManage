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

    # Always run: project codes carry the current company initials. Rewriting
    # only old-prefix rows keeps this safe to repeat, and catches codes that
    # arrive from a restored backup.
    connection.execute(
        "UPDATE OR IGNORE projects SET code = 'YVK-' || substr(code, 4) "
        "WHERE code LIKE 'VK-%' AND code NOT LIKE 'YVK-%'"
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
    execute(
        "INSERT INTO audit_events (id, user_id, project_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (new_id(), user_id, project_id, action, detail, now_iso()),
    )
