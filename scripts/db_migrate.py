#!/usr/bin/env python3
"""Create and/or migrate the firm database, explicitly (§10, §30.1).

The storage layer has existed since Phase 2 and the GMIS migration since
GMIS-001, but nothing ever CREATED `database/firm.sqlite`: `sqlite3.connect`
creates on first touch, and no runtime code path calls it. This script is that
missing explicit step, so database creation is a deliberate operator action
with a printed record — never a side effect of some other process starting.

Thin by design: migration logic lives in `trading_firm.audit.apply_migrations`
(deterministic filename order, `schema_migrations` ledger, idempotent) and is
reused, not duplicated. The audit package imports nothing but the standard
library — no supervisor, no broker transport, no surveillance runtime, no
notification path — and `tests/unit/test_db_migrate.py` pins that with the
same AST check the no-order-path acceptance tests use.

Fail-closed behaviour: each migration script commits only after it completes,
and its ledger row is written in the same transaction, so a failing migration
leaves the database at the last fully-applied migration and this process exits
non-zero. Re-running after a fix resumes from exactly the failed script.

    python3 scripts/db_migrate.py                       # database/firm.sqlite
    python3 scripts/db_migrate.py --db /tmp/probe.sqlite
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_firm.audit import apply_migrations, connect  # noqa: E402

DEFAULT_DB = REPO / "database" / "firm.sqlite"


def applied_migrations(conn: sqlite3.Connection) -> list[str]:
    """Rows in the ledger, or [] when the ledger itself does not exist yet."""
    ledger_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not ledger_exists:
        return []
    return [row[0] for row in conn.execute("SELECT name FROM schema_migrations ORDER BY name")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"database path (default: {DEFAULT_DB})"
    )
    args = parser.parse_args(argv)

    db_path = args.db.resolve()
    existed = db_path.exists()
    print(f"database : {db_path}")
    print(f"existed  : {'yes' if existed else 'no — will be created'}")

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = None
    try:
        conn = connect(db_path)
        before = applied_migrations(conn)
        print(f"applied  : {', '.join(before) if before else '(none)'}")

        newly = apply_migrations(conn)

        after = applied_migrations(conn)
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error as error:
        # Fail closed: the ledger records only fully-committed migrations, so
        # the database is at the last good migration and the exit is non-zero.
        # The message never includes file contents — only the sqlite error.
        print(f"FAIL: migration error: {error}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    print(f"newly    : {', '.join(newly) if newly else '(none)'}")
    print(f"state    : {', '.join(after) if after else '(none)'}")
    print(f"integrity: {integrity}")
    if integrity != "ok":
        print("FAIL: integrity_check did not return ok", file=sys.stderr)
        return 1
    print(f"result   : {'no-op — already fully migrated' if not newly else 'migrated'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
