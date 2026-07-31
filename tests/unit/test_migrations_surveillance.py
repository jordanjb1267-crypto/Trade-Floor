"""Migration 0002 (§30.17 migration rows): empty database, copy of the
current database, rerun detection, old rows valid, backup and restore, and
the feature-disable rollback posture."""

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pytest

from trading_firm.audit.db import apply_migrations, connect

# The backup/restore scripts are operational tooling, not package members;
# they are imported here exactly as launchd runs them — as files.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from trading_firm.surveillance.events import EventType, SurveillanceEvent, record_event
from trading_firm.surveillance.schemas import DataQualityStatus

NOW = dt.datetime(2026, 7, 29, 7, 30, tzinfo=dt.UTC)

SURVEILLANCE_TABLES = {
    "source_health_events", "economic_events", "news_items", "news_item_sources",
    "news_verification_events", "cross_market_observations", "feature_snapshots",
    "market_states", "surveillance_events", "surveillance_alerts",
    "market_state_packets", "thesis_monitoring_plans", "position_contradictions",
    "surveillance_agent_reviews",
}


def tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def pre_amendment_db(path) -> sqlite3.Connection:
    """A database as the owner's laptop has it today: 0001 applied, rows in."""
    conn = connect(path)
    import shutil
    import tempfile
    from pathlib import Path

    from trading_firm.audit import db as audit_db

    with tempfile.TemporaryDirectory() as tmp:
        only_first = Path(tmp) / "migrations"
        only_first.mkdir()
        shutil.copy(audit_db.MIGRATIONS_DIR / "0001_init.sql", only_first)
        apply_migrations(conn, only_first)
    conn.execute(
        "INSERT INTO candidates (created_at, expires_at, instrument, strategy_id, "
        "strategy_version, direction, entry_price, stop_price, edge_score, payload_json) "
        "VALUES ('2026-07-29T08:00:00Z','2026-07-29T08:30:00Z','GBP_USD',"
        "'london_breakout','1.0.0','LONG','1.28500','1.28250',75,'{}')"
    )
    conn.execute(
        "INSERT INTO incidents (ts, trigger, action_taken, details_json) "
        "VALUES ('2026-07-29T09:00:00Z','test','none','{}')"
    )
    conn.commit()
    return conn


class TestEmptyDatabase:
    def test_both_migrations_apply_in_order(self, tmp_path) -> None:
        conn = connect(tmp_path / "empty.sqlite")
        applied = apply_migrations(conn)
        assert applied == ["0001_init.sql", "0002_surveillance.sql"]
        assert SURVEILLANCE_TABLES <= tables(conn)
        conn.close()

    def test_rerun_applies_nothing(self, tmp_path) -> None:
        conn = connect(tmp_path / "empty.sqlite")
        apply_migrations(conn)
        assert apply_migrations(conn) == []
        conn.close()


class TestCopyOfTheCurrentDatabase:
    def test_upgrade_preserves_existing_rows_and_constraints(self, tmp_path) -> None:
        conn = pre_amendment_db(tmp_path / "current.sqlite")
        before_candidates = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        before_incidents = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

        applied = apply_migrations(conn)
        assert applied == ["0002_surveillance.sql"], "0001 must be rerun-detected"

        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == before_candidates
        assert conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == before_incidents
        conn.close()

    def test_old_candidate_rows_read_with_a_null_packet_reference(self, tmp_path) -> None:
        conn = pre_amendment_db(tmp_path / "current.sqlite")
        apply_migrations(conn)
        row = conn.execute(
            "SELECT instrument, market_state_packet_id FROM candidates"
        ).fetchone()
        assert row == ("GBP_USD", None), "§30.14: nullable reference, old rows valid"
        conn.close()

    def test_disable_rollback_posture_every_new_table_is_empty(self, tmp_path) -> None:
        """§30.18: with surveillance.enabled false nothing writes these tables,
        so the config-level rollback leaves them empty and inert."""
        conn = pre_amendment_db(tmp_path / "current.sqlite")
        apply_migrations(conn)
        for table in sorted(SURVEILLANCE_TABLES):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()


class TestOutbox:
    def _event(self, event_id: str = "evt-1") -> SurveillanceEvent:
        return SurveillanceEvent(
            event_id=event_id,
            event_type=EventType.MARKET_STATE_PUBLISHED,
            schema_version="surveillance_event_v1",
            event_time_utc=NOW,
            ingestion_time_utc=NOW,
            producer="test",
            instrument_scope=["GBP_USD"],
            correlation_id="corr-1",
            configuration_version="cfg-1",
            data_quality=DataQualityStatus.HEALTHY,
            payload={"k": "v"},
        )

    def test_record_event_round_trips(self, tmp_path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        apply_migrations(conn)
        record_event(conn, self._event())
        event_type, checksum = conn.execute(
            "SELECT event_type, payload_checksum FROM surveillance_events"
        ).fetchone()
        assert event_type == "market_state.published"
        assert checksum == self._event().payload_checksum
        conn.close()

    def test_a_replayed_event_id_is_a_hard_error(self, tmp_path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        apply_migrations(conn)
        record_event(conn, self._event())
        with pytest.raises(sqlite3.IntegrityError):
            record_event(conn, self._event())
        conn.close()


class TestBackupAndRestore:
    def test_backup_verifies_and_restore_round_trips(self, tmp_path) -> None:
        from db_backup import backup
        from db_restore import restore

        db = tmp_path / "firm.sqlite"
        conn = pre_amendment_db(db)
        apply_migrations(conn)
        conn.close()

        made = backup(db, backup_dir=tmp_path / "backups")
        assert made.exists()

        # Damage the live DB, then restore.
        conn = sqlite3.connect(str(db))
        conn.execute("DELETE FROM candidates")
        conn.commit()
        conn.close()

        with pytest.raises(RuntimeError, match="--force"):
            restore(made, db)
        displaced = restore(made, db, force=True)
        assert displaced is not None and displaced.exists(), "displaced, never deleted"

        conn = sqlite3.connect(str(db))
        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
        conn.close()

    def test_backup_refuses_a_missing_database(self, tmp_path) -> None:
        from db_backup import backup

        with pytest.raises(FileNotFoundError):
            backup(tmp_path / "nothing.sqlite", backup_dir=tmp_path / "backups")
