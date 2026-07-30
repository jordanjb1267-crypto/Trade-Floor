"""SQLite storage layer (§10): WAL mode, ordered migrations, aware-UTC text timestamps."""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "database" / "migrations"


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def apply_migrations(
    conn: sqlite3.Connection, migrations_dir: str | Path = MIGRATIONS_DIR
) -> list[str]:
    """Apply pending .sql migrations in filename order. Idempotent."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  name TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
        ")"
    )
    applied = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    newly_applied: list[str] = []
    for script in sorted(Path(migrations_dir).glob("*.sql")):
        if script.name in applied:
            continue
        conn.executescript(script.read_text())
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (script.name,))
        conn.commit()
        newly_applied.append(script.name)
    return newly_applied
