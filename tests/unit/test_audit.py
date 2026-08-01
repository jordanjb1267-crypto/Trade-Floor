"""Audit service tests (§21 'Audit completeness' foundations; §17 tamper evidence)."""

import json
from pathlib import Path

from trading_firm.audit import AuditLog, apply_migrations, connect


class TestHashChain:
    def test_append_and_verify(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path / "audit.jsonl")
        log.append("config_loaded", {"sha256": "abc"})
        log.append("risk_decision", {"approved": True, "allowed": "2.81"})
        log.append("session_state", {"window": "ACTIVE"})
        ok, bad_seq = log.verify()
        assert ok and bad_seq is None
        assert log.head_hash() != "0" * 64

    def test_tampering_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = AuditLog(path)
        log.append("a", {"v": 1})
        log.append("b", {"v": 2})
        log.append("c", {"v": 3})

        lines = path.read_text().splitlines()
        doctored = json.loads(lines[1])
        doctored["payload"]["v"] = 999  # silent edit, hash left as-is
        lines[1] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n")

        ok, bad_seq = log.verify()
        assert not ok
        assert bad_seq == 2

    def test_deletion_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.jsonl"
        log = AuditLog(path)
        log.append("a", {"v": 1})
        log.append("b", {"v": 2})
        lines = path.read_text().splitlines()
        path.write_text(lines[1] + "\n")  # drop the first record
        ok, bad_seq = log.verify()
        assert not ok


class TestSqlite:
    def test_wal_mode_and_migrations(self, tmp_path: Path) -> None:
        conn = connect(tmp_path / "firm.db")
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        first = apply_migrations(conn)
        assert first == ["0001_init.sql", "0002_surveillance.sql"]
        assert apply_migrations(conn) == []  # idempotent

    def test_decision_trail_roundtrip(self, tmp_path: Path) -> None:
        conn = connect(tmp_path / "firm.db")
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO candidates (created_at, expires_at, instrument, strategy_id,"
            " strategy_version, direction, entry_price, stop_price, edge_score, payload_json)"
            " VALUES ('2026-07-29T08:05:00Z','2026-07-29T08:35:00Z','GBP_USD',"
            " 'london_breakout','0.0.1','LONG','1.3298','1.3273',97,'{}')"
        )
        candidate_id = conn.execute("SELECT id FROM candidates").fetchone()[0]
        conn.execute(
            "INSERT INTO risk_decisions (candidate_id, ts, approved, tier, allowed_risk_usd,"
            " binding_constraint, reasons_json)"
            " VALUES (?, '2026-07-29T08:05:01Z', 1, 'EXCEPTIONAL', '2.81',"
            " 'margin-safe capacity', '[]')",
            (candidate_id,),
        )
        row = conn.execute(
            "SELECT c.instrument, r.allowed_risk_usd FROM risk_decisions r"
            " JOIN candidates c ON c.id = r.candidate_id"
        ).fetchone()
        assert row == ("GBP_USD", "2.81")
