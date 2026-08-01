#!/usr/bin/env python3
"""Restore the firm database from a verified backup (§30.18 rollback path).

The primary rollback for the surveillance amendment is configuration —
`surveillance.enabled: false` leaves every 0002 table empty and inert. This
script is the second path: return the database file itself to a
pre-migration backup taken by scripts/db_backup.py.

Refuses to overwrite an existing database unless --force is given, and moves
the current file aside (never deletes it) before restoring.

    python3 scripts/db_restore.py database/backups/firm-<stamp>.sqlite \
        [--db database/firm.sqlite] [--force]
"""

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "database" / "firm.sqlite"


def restore(backup_path: Path, db_path: Path, force: bool = False) -> Path | None:
    if not backup_path.exists():
        raise FileNotFoundError(f"no backup at {backup_path}")
    check = sqlite3.connect(str(backup_path))
    try:
        status = check.execute("PRAGMA integrity_check").fetchone()[0]
        if status != "ok":
            raise RuntimeError(f"refusing to restore a corrupt backup: {status}")
    finally:
        check.close()

    displaced = None
    if db_path.exists():
        if not force:
            raise RuntimeError(
                f"{db_path} exists; pass --force to displace it (the current file "
                f"is moved aside, never deleted)"
            )
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        displaced = db_path.with_name(f"{db_path.stem}-displaced-{stamp}.sqlite")
        db_path.rename(displaced)

    source = sqlite3.connect(str(backup_path))
    try:
        target = sqlite3.connect(str(db_path))
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
    finally:
        source.close()
    return displaced


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        displaced = restore(args.backup, args.db, force=args.force)
    except (FileNotFoundError, RuntimeError, sqlite3.Error) as err:
        print(f"FAIL: {err}")
        return 1
    if displaced is not None:
        print(f"note: previous database moved aside to {displaced.name}")
    print(f"OK: restored {args.backup.name} to {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
