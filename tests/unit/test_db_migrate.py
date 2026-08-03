"""`scripts/db_migrate.py` — the explicit database creation/migration command.

Every functional test runs the script as a SUBPROCESS against a tmp_path
database, for two reasons: it proves the actual operator command line works
(not a lookalike in-process call), and it makes leaking state into the real
repository structurally impossible — the working directory never matters
because `--db` is always given. A final guard asserts the repository's real
database path stayed absent.
"""

from __future__ import annotations

import ast
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "db_migrate.py"
REAL_DB = REPO / "database" / "firm.sqlite"
# Captured at import, before any test runs, so the guard below compares against
# the state the operator's database was in when the suite started.
REAL_DB_MTIME_AT_IMPORT = REAL_DB.stat().st_mtime if REAL_DB.exists() else None

EXPECTED_MIGRATIONS = ["0001_init.sql", "0002_surveillance.sql"]


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestFreshCreation:
    def test_creates_and_fully_migrates_a_fresh_database(self, tmp_path) -> None:
        db = tmp_path / "firm.sqlite"
        result = run("--db", str(db))
        assert result.returncode == 0, result.stderr
        assert db.exists()
        assert "existed  : no" in result.stdout
        for name in EXPECTED_MIGRATIONS:
            assert name in result.stdout

        ledger = sqlite3.connect(str(db))
        try:
            rows = [
                r[0]
                for r in ledger.execute("SELECT name FROM schema_migrations ORDER BY name")
            ]
        finally:
            ledger.close()
        assert rows == EXPECTED_MIGRATIONS

    def test_0002_tables_actually_exist(self, tmp_path) -> None:
        """Applying 0002 must mean the surveillance tables are queryable, not
        merely that a ledger row was written."""
        db = tmp_path / "firm.sqlite"
        run("--db", str(db))
        conn = sqlite3.connect(str(db))
        try:
            tables = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        assert "audit_events" in tables, "0001 core table missing"
        surveillance = {t for t in tables if "surveillance" in t or "market_state" in t}
        assert surveillance, "0002 applied but no surveillance table exists"

    def test_parent_directory_is_created(self, tmp_path) -> None:
        db = tmp_path / "deep" / "nested" / "firm.sqlite"
        result = run("--db", str(db))
        assert result.returncode == 0
        assert db.exists()


class TestIdempotency:
    def test_a_second_run_is_a_noop(self, tmp_path) -> None:
        db = tmp_path / "firm.sqlite"
        first = run("--db", str(db))
        second = run("--db", str(db))
        assert second.returncode == 0
        assert "existed  : yes" in second.stdout
        assert "newly    : (none)" in second.stdout
        assert "no-op" in second.stdout
        # And the first run must NOT have been one.
        assert "no-op" not in first.stdout

    def test_row_counts_survive_a_rerun(self, tmp_path) -> None:
        """Idempotent must mean data-preserving, not merely error-free."""
        db = tmp_path / "firm.sqlite"
        run("--db", str(db))
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO audit_events (ts, type, payload_json, prev_hash, hash)"
            " VALUES ('2026-07-31T00:00:00Z', 'test', '{}', 'p', 'h')"
        )
        conn.commit()
        conn.close()

        run("--db", str(db))

        conn = sqlite3.connect(str(db))
        try:
            count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        finally:
            conn.close()
        assert count == 1, "a re-run must never touch existing rows"


class TestFailClosed:
    def test_a_corrupt_database_fails_nonzero(self, tmp_path) -> None:
        db = tmp_path / "firm.sqlite"
        db.write_text("this is not a sqlite database")
        result = run("--db", str(db))
        assert result.returncode == 1
        assert "FAIL" in result.stderr

    def test_a_failing_migration_leaves_no_ledger_row(self, tmp_path) -> None:
        """The ledger row commits with its script; a failed script must not be
        recorded as applied. Proven in-process against a broken migrations dir
        because the CLI (correctly) has no flag for overriding migrations."""
        sys.path.insert(0, str(REPO / "src"))
        from trading_firm.audit import apply_migrations, connect

        bad_dir = tmp_path / "migrations"
        bad_dir.mkdir()
        (bad_dir / "0001_boom.sql").write_text("CREATE TABLE t (a);\nSYNTAX ERROR HERE;")

        conn = connect(tmp_path / "x.sqlite")
        try:
            try:
                apply_migrations(conn, bad_dir)
                raise AssertionError("expected the broken migration to raise")
            except sqlite3.Error:
                pass
            rows = [r[0] for r in conn.execute("SELECT name FROM schema_migrations")]
        finally:
            conn.close()
        assert rows == [], "a failed migration must not be recorded as applied"


class TestNoRuntimeReachable:
    """Requirement: the migration command must not be able to start anything.

    Same technique as the no-order-path acceptance tests: the import graph is
    the guarantee, checked by AST so it holds without executing the script.
    """

    FORBIDDEN = (
        "trading_firm.execution",
        "trading_firm.runner",
        "trading_firm.notify",
        "trading_firm.surveillance",
        "trading_firm.strategies",
        "trading_firm.agents",
        "trading_firm.risk",
        "trading_firm.sizing",
        "trading_firm.reconciliation",
    )

    def _imports(self, path: Path) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                found |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
        return found

    def test_the_script_imports_only_the_audit_package(self) -> None:
        project = {i for i in self._imports(SCRIPT) if i.startswith("trading_firm")}
        assert project == {"trading_firm.audit"}

    def test_the_audit_package_reaches_no_runtime_module(self) -> None:
        """Transitive closure: audit/__init__, chain, db import stdlib only."""
        audit_dir = REPO / "src" / "trading_firm" / "audit"
        for module in audit_dir.glob("*.py"):
            for name in self._imports(module):
                assert not name.startswith(self.FORBIDDEN), (
                    f"{module.name} imports {name}: the migration path must not "
                    f"be able to reach a runtime service"
                )

    def test_the_broker_host_never_appears_in_the_script(self) -> None:
        text = SCRIPT.read_text()
        assert "oanda" not in text.lower()
        assert "telegram" not in text.lower()


class TestRepositoryStaysClean:
    def test_the_real_database_is_not_touched_by_the_suite(self) -> None:
        """Every test above used tmp_path; this guards the suite itself — if a
        future test drops the --db argument, this fails the run.

        Originally asserted the real database was ABSENT, which was true only
        until it was legitimately initialized on 2026-08-01. Absence was never
        the property worth protecting: "the tests did not touch the operator's
        database" is, and it keeps holding once the file exists. The mtime is
        captured at import, before any test in this module runs.
        """
        if REAL_DB_MTIME_AT_IMPORT is None:
            assert not REAL_DB.exists(), (
                "database/firm.sqlite was CREATED during the test run: a test "
                "touched the real repository database path"
            )
            return
        assert REAL_DB.exists(), "the real database vanished during the test run"
        assert REAL_DB.stat().st_mtime == REAL_DB_MTIME_AT_IMPORT, (
            "database/firm.sqlite was MODIFIED during the test run: a test "
            "touched the real repository database path"
        )
