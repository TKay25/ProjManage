"""Copy a local SQLite database into Postgres.

    python tools/migrate_to_postgres.py \
        --sqlite instance/vaka.db \
        --postgres postgresql://vaka:secret@host:5432/vaka

Run it from the repo root with the app's virtualenv. The target schema is
created first, rows are copied in foreign-key order, and existing primary keys
are skipped so the tool is safe to re-run after a partial import.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db import DUMP_ORDER, POSTGRES_UPGRADES, SCHEMA, split_statements  # noqa: E402

SKIP_TABLES = {"_healthcheck"}


def sqlite_tables(connection) -> list[str]:
    rows = connection.execute(
        """SELECT name FROM sqlite_master
           WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
           ORDER BY name"""
    ).fetchall()
    return [row[0] for row in rows if row[0] not in SKIP_TABLES]


def create_schema(connection):
    for statement in split_statements(SCHEMA):
        connection.execute(statement)
    for statement in split_statements(POSTGRES_UPGRADES):
        connection.execute(statement)


def copy_table(source, target, table: str) -> int:
    rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
    if not rows:
        return 0

    columns = list(rows[0].keys())
    column_sql = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("%s" for _ in columns)
    statement = (
        f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders}) '
        "ON CONFLICT DO NOTHING"
    )
    with target.cursor() as cursor:
        cursor.executemany(statement, [tuple(row) for row in rows])
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy SQLite data into Postgres.")
    parser.add_argument("--sqlite", required=True, help="Path to the SQLite database file.")
    parser.add_argument("--postgres", required=True, help="Postgres connection string.")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_file():
        print(f"SQLite database not found: {sqlite_path}", file=sys.stderr)
        return 1

    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1

    source = sqlite3.connect(str(sqlite_path))
    source.row_factory = sqlite3.Row
    target = psycopg.connect(args.postgres)

    try:
        create_schema(target)
        present = sqlite_tables(source)
        ordered = [name for name in DUMP_ORDER if name in present]
        ordered += sorted(name for name in present if name not in DUMP_ORDER)

        total = 0
        for table in ordered:
            copied = copy_table(source, target, table)
            total += copied
            print(f"{table:<22} {copied:>6} rows")
        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()

    print(f"Done — {total} rows copied into Postgres.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
