"""Database access layer for YaVaKa (SQLite locally, Postgres in production).

Set ``DATABASE_URL`` to a Postgres connection string to use Postgres; otherwise
the app keeps using the SQLite file in ``DATABASE_FILE``. Queries are written in
SQLite style (``?`` placeholders, case-insensitive ``LIKE``) and translated for
Postgres by this module, so callers do not need two dialects.
"""

import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone

from flask import current_app, g, has_app_context

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
  density TEXT NOT NULL DEFAULT 'comfortable',
  page_size INTEGER NOT NULL DEFAULT 25,
  session_epoch INTEGER NOT NULL DEFAULT 0,
  onboarded_at TEXT,
  totp_secret TEXT,
  totp_enabled INTEGER NOT NULL DEFAULT 0,
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
  archived_at TEXT,
  workspace_id TEXT,
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
  stage_key TEXT,
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
  handoff_at TEXT,
  handoff_by TEXT REFERENCES users(id),
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

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workspace_owner ON workspaces(owner_id);

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

CREATE TABLE IF NOT EXISTS password_resets (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_password_resets_user
  ON password_resets(user_id, created_at);

CREATE TABLE IF NOT EXISTS totp_recovery_codes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL UNIQUE,
  used_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_totp_codes_user ON totp_recovery_codes(user_id, used_at);

-- Failed-attempt counters live in the database, not process memory, so every
-- worker sees the same window and a restart cannot reset an attacker's budget.
CREATE TABLE IF NOT EXISTS auth_throttle (
  key TEXT PRIMARY KEY,
  window_start TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action, created_at);
CREATE INDEX IF NOT EXISTS idx_tx_type_date ON transactions(project_id, type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_stages_status ON stages(project_id, status);
CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects(archived_at);
CREATE INDEX IF NOT EXISTS idx_wa_contact_project ON whatsapp_contacts(project_id);
"""

# Columns added by the SQLite migrations below also need to exist on a Postgres
# database that was created before they were folded into SCHEMA.
POSTGRES_UPGRADES = """
ALTER TABLE users ADD COLUMN IF NOT EXISTS density TEXT NOT NULL DEFAULT 'comfortable';
ALTER TABLE users ADD COLUMN IF NOT EXISTS page_size INTEGER NOT NULL DEFAULT 25;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS client_email TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS client_whatsapp TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS archived_at TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS workspace_id TEXT;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS stage_key TEXT;
ALTER TABLE notification_outbox ADD COLUMN IF NOT EXISTS claimed_at TEXT;
ALTER TABLE whatsapp_contacts ADD COLUMN IF NOT EXISTS handoff_at TEXT;
ALTER TABLE whatsapp_contacts ADD COLUMN IF NOT EXISTS handoff_by TEXT REFERENCES users(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS session_epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarded_at TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action, created_at);
CREATE INDEX IF NOT EXISTS idx_tx_type_date ON transactions(project_id, type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_stages_status ON stages(project_id, status);
CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects(archived_at);
CREATE INDEX IF NOT EXISTS idx_wa_contact_project ON whatsapp_contacts(project_id);
"""


def postgres_url() -> str:
    """The configured Postgres DSN, normalised for psycopg."""
    url = (current_app.config.get("DATABASE_URL") or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url if url.startswith("postgresql://") else ""


def is_postgres() -> bool:
    return bool(postgres_url())


def get_db():
    if "db" not in g:
        url = postgres_url()
        if url:
            import psycopg
            from psycopg.rows import dict_row

            connection = psycopg.connect(
                url,
                row_factory=dict_row,
                autocommit=True,
                connect_timeout=10,
            )
        else:
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


def _translate_sql(sql: str, args) -> str:
    """SQLite-style SQL to Postgres SQL.

    Converts ``?`` placeholders to ``%s``, doubles literal percent signs when
    parameters are supplied (psycopg uses %-formatting), and maps ``LIKE`` to
    ``ILIKE`` so the case-insensitive search behaviour is preserved.
    """
    if not is_postgres():
        return sql

    if args:
        sql = sql.replace("%", "%%")

    out = []
    quote = None
    for char in sql:
        if quote:
            out.append(char)
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
            out.append(char)
        elif char == "?":
            out.append("%s")
        else:
            out.append(char)

    return re.sub(r"\bLIKE\b", "ILIKE", "".join(out), flags=re.IGNORECASE)


def split_statements(script: str):
    """Split a schema script on semicolons, ignoring quoted ones."""
    statements = []
    current = []
    quote = None
    for char in script:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


SCHEMA_LOCK_KEY = 842_317_501


def init_db():
    if is_postgres():
        # Several gunicorn workers boot at once; serialise the DDL so two of
        # them cannot race on CREATE TABLE / ALTER TABLE.
        connection = get_db()
        connection.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK_KEY,))
        try:
            executescript(SCHEMA)
            executescript(POSTGRES_UPGRADES)
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK_KEY,))
        return

    executescript(SCHEMA)
    run_migrations(get_db())


def run_migrations(connection):
    """Idempotent SQLite migrations, tracked with PRAGMA user_version.

    Postgres databases are created from the complete ``SCHEMA`` instead, so
    this only runs on the SQLite backend.
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

    if version < 13:
        # A build manager can take a conversation over from the assistant.
        # While handoff_at is set, inbound messages are still stored but the
        # bot stays quiet until the conversation is returned to it.
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(whatsapp_contacts)")
        }
        if "handoff_at" not in columns:
            connection.execute("ALTER TABLE whatsapp_contacts ADD COLUMN handoff_at TEXT")
        if "handoff_by" not in columns:
            connection.execute(
                "ALTER TABLE whatsapp_contacts ADD COLUMN handoff_by TEXT REFERENCES users(id)"
            )
        connection.execute("PRAGMA user_version = 13")

    if version < 14:
        # Security and onboarding columns: a session epoch so a password change
        # can sign other devices out, per-user onboarding state, and TOTP.
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        for name, definition in (
            ("session_epoch", "INTEGER NOT NULL DEFAULT 0"),
            ("onboarded_at", "TEXT"),
            ("totp_secret", "TEXT"),
            ("totp_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        connection.execute("PRAGMA user_version = 14")

    # Always run: indexes for the hot filters, and tables added after the
    # original schema. Both are idempotent on every backend.
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_tx_type_date ON transactions(project_id, type, occurred_at)",
        "CREATE INDEX IF NOT EXISTS idx_stages_status ON stages(project_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_projects_archived ON projects(archived_at)",
        "CREATE INDEX IF NOT EXISTS idx_wa_contact_project ON whatsapp_contacts(project_id)",
        """CREATE TABLE IF NOT EXISTS totp_recovery_codes (
             id TEXT PRIMARY KEY,
             user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
             code_hash TEXT NOT NULL UNIQUE,
             used_at TEXT,
             created_at TEXT NOT NULL
           )""",
        "CREATE INDEX IF NOT EXISTS idx_totp_codes_user ON totp_recovery_codes(user_id, used_at)",
        """CREATE TABLE IF NOT EXISTS auth_throttle (
             key TEXT PRIMARY KEY,
             window_start TEXT NOT NULL,
             count INTEGER NOT NULL DEFAULT 0
           )""",
    ):
        connection.execute(statement)

    # Always run: adopt the current prefix. Rewriting only old-prefix rows keeps
    # this safe to repeat, and catches codes that arrive from a restored backup.
    connection.execute(
        "UPDATE OR IGNORE projects SET code = 'YVK-' || substr(code, 4) "
        "WHERE code LIKE 'VK-%' AND code NOT LIKE 'YVK-%'"
    )

    connection.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


def _note_query(sql: str, started: float):
    """Counts queries per request and logs the ones that cross the threshold."""
    if not has_app_context():
        return
    elapsed_ms = (time.perf_counter() - started) * 1000
    g.query_count = getattr(g, "query_count", 0) + 1
    g.query_ms = getattr(g, "query_ms", 0.0) + elapsed_ms

    threshold = current_app.config.get("SLOW_QUERY_MS", 150)
    if not threshold or elapsed_ms < threshold:
        return

    compact = " ".join(sql.split())
    current_app.logger.warning(
        "slow query %.0fms: %s",
        elapsed_ms,
        compact[:300] + ("…" if len(compact) > 300 else ""),
        extra={"slow_query_ms": round(elapsed_ms, 1)},
    )


def query(sql: str, args=(), one: bool = False):
    """Return rows as plain dicts so templates and JSON stay simple."""
    args = tuple(args or ())
    connection = get_db()
    prepared = _translate_sql(sql, args)
    started = time.perf_counter()
    cursor = connection.execute(prepared, args) if args else connection.execute(prepared)
    rows = [dict(row) for row in cursor.fetchall()]
    cursor.close()
    _note_query(sql, started)
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql: str, args=()) -> int:
    args = tuple(args or ())
    connection = get_db()
    prepared = _translate_sql(sql, args)
    started = time.perf_counter()
    cursor = connection.execute(prepared, args) if args else connection.execute(prepared)
    if not is_postgres():
        connection.commit()
    last_id = getattr(cursor, "lastrowid", None)
    cursor.close()
    _note_query(sql, started)
    return last_id


def executescript(script: str):
    connection = get_db()
    if is_postgres():
        for statement in split_statements(script):
            connection.execute(statement)
        return
    connection.executescript(script)
    connection.commit()


DUMP_ORDER = [
    "users",
    "workspaces",
    "projects",
    "stages",
    "transactions",
    "attachments",
    "agreements",
    "suppliers",
    "whatsapp_contacts",
    "whatsapp_messages",
    "audit_events",
    "notification_outbox",
    "notifications",
    "manager_links",
    "invitations",
    "password_resets",
]


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def dump_sql() -> str:
    """A logical Postgres dump, ordered so foreign keys survive a restore."""
    if not is_postgres():
        raise RuntimeError("dump_sql() is only available for the Postgres backend.")

    connection = get_db()
    present = [
        row["table_name"]
        for row in connection.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"""
        ).fetchall()
    ]
    ordered = [name for name in DUMP_ORDER if name in present]
    ordered += sorted(name for name in present if name not in DUMP_ORDER)

    lines = [
        "-- YaVaKa Postgres backup",
        f"-- generated {now_iso()}",
        "-- restore into an empty database",
        "",
        SCHEMA,
        "",
        "BEGIN;",
    ]
    for name in ordered:
        if name == "_healthcheck":
            continue
        rows = connection.execute(f'SELECT * FROM "{name}"').fetchall()
        if not rows:
            continue
        lines.append(f"-- {name}")
        for row in rows:
            columns = ", ".join(f'"{column}"' for column in row.keys())
            values = ", ".join(_sql_literal(value) for value in row.values())
            lines.append(f'INSERT INTO "{name}" ({columns}) VALUES ({values});')
        lines.append("")
    lines.append("COMMIT;")
    return "\n".join(lines)


def new_id() -> str:
    return uuid.uuid4().hex[:20]


def now_iso() -> str:
    # Microsecond precision keeps ordering stable when two rows share a second.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


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
