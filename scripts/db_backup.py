#!/usr/bin/env python3
"""Back up the firm database before a migration touches it (§30.1 rule 3).

Uses SQLite's online backup API — safe against a live WAL connection, unlike
copying the file. The backup is verified by opening it and running an
integrity check plus a row-count comparison, because an unverified backup is
a hope, not a rollback path (§30.18: the database can be restored to the
pre-migration backup).

    python3 scripts/db_backup.py [--db database/firm.sqlite]

Prints the backup path on success; exits non-zero on any failure.
"""

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "database" / "firm.sqlite"
BACKUP_DIR = REPO / "database" / "backups"


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def backup(db_path: Path, backup_dir: Path = BACKUP_DIR) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"no database at {db_path}; nothing to back up")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"{db_path.stem}-{stamp}.sqlite"

    source = sqlite3.connect(str(db_path))
    try:
        target = sqlite3.connect(str(destination))
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
        # Verify: integrity plus identical row counts, table by table.
        check = sqlite3.connect(str(destination))
        try:
            status = check.execute("PRAGMA integrity_check").fetchone()[0]
            if status != "ok":
                raise RuntimeError(f"backup failed integrity_check: {status}")
            if table_counts(check) != table_counts(source):
                raise RuntimeError("backup row counts differ from source")
        finally:
            check.close()
    finally:
        source.close()
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    try:
        destination = backup(args.db)
    except (FileNotFoundError, RuntimeError, sqlite3.Error) as err:
        print(f"FAIL: {err}")
        return 1
    print(f"OK: verified backup at {destination.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
