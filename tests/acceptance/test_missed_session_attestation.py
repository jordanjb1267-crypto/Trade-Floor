"""A scheduled session never disappears silently (§31.7).

The gap this closes, confirmed during authority acceptance testing: a runtime
suspended through every remaining boundary wakes to `next_event` returning the
NEXT trading day, so the missed session's flatten handler never runs and no
report is ever written. The driven latch keeps authority safe; nothing kept
the audit trail complete.

Every test drives the real `Supervisor`. The durable idempotency guard is the
report file itself, so most assertions are about what exists on disk after —
exactly one terminal artifact per expected session, never two, never zero.
"""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.notify.surface import NotificationKind
from trading_firm.runner.power import SuspensionDetector
from trading_firm.runner.schedule import next_event
from trading_firm.runner.supervisor import HealthReport, Supervisor
from trading_firm.runner.timing import FlatState, SessionAuthority
from trading_firm.sessions import SessionClock

LONDON = ZoneInfo("Europe/London")
FRI = dt.date(2026, 8, 7)
MON = dt.date(2026, 8, 10)
TUE = dt.date(2026, 8, 11)


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def at(day: dt.date, hour: int, minute: int) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=LONDON)


def healthy() -> HealthReport:
    return HealthReport(broker_reachable=True, account_flat=True, open_position_count=0)


THU = dt.date(2026, 8, 6)


class Driver:
    def __init__(self, clock, tmp_path, probe=healthy, start=None, epoch=THU):
        self.sent: list[tuple[NotificationKind, str]] = []
        self.moment = start or at(FRI, 6, 0)
        self.clock = clock
        self.tmp_path = tmp_path
        self.supervisor = Supervisor(
            clock=clock,
            probe=probe,
            notify=lambda kind, body: (self.sent.append((kind, body)), True)[1],
            report_dir=tmp_path,
            now=lambda: self.moment,
            sleep=lambda s: None,
            # §31.5: qualification requires the three runtime controls wired
            # and an EXECUTED positive power verification — the same contract
            # the production builder satisfies. Frozen detector clocks: no
            # drift, so no suspension is ever detected by these tests.
            heartbeat=lambda phase: None,
            suspension=SuspensionDetector(wall=lambda: 0.0, monotonic=lambda: 0.0),
            power_check=lambda: (True, "test: power verified"),
            epoch=epoch,
        )

    def run_events(self, count: int) -> None:
        for _ in range(count):
            scheduled = next_event(self.clock, self.moment)
            self.moment = scheduled.at + dt.timedelta(seconds=1)
            self.supervisor.handle(scheduled)

    def reports(self) -> dict[str, dict]:
        return {
            p.name: json.loads(p.read_text())
            for p in sorted(self.tmp_path.glob("*-session.json"))
        }


class TestNormalSession:
    def test_exactly_one_normal_report_and_no_attestation(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(5)
        reports = driver.reports()
        assert list(reports) == [f"{FRI}-session.json"]
        report = reports[f"{FRI}-session.json"]
        assert report["qualifying"] is True
        assert not any("SESSION WINDOW MISSED" in r for r in report["reasons"])


class TestSleepThroughRemainingSession:
    def test_exactly_one_missed_report(self, clock, tmp_path) -> None:
        """Friday runs pre_startup + briefing, sleeps through the rest, wakes
        Monday. Friday must get exactly one MISSED/NON_QUALIFYING report."""
        driver = Driver(clock, tmp_path)
        driver.run_events(2)
        driver.moment = at(MON, 6, 0)
        driver.run_events(1)  # Monday pre_startup: attestation settles Friday first

        reports = driver.reports()
        assert f"{FRI}-session.json" in reports
        friday = reports[f"{FRI}-session.json"]
        assert friday["qualifying"] is False
        assert friday["session_health"] == "DEGRADED"
        assert friday["nominal"] is False
        assert friday["clean_event_count"] < 5
        assert any("SESSION WINDOW MISSED" in r for r in friday["reasons"])

    def test_observed_and_missed_boundaries_are_distinguished(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(2)  # pre_startup and briefing DID run
        driver.moment = at(MON, 6, 0)
        driver.run_events(1)
        friday = driver.reports()[f"{FRI}-session.json"]
        executed = {e["event"] for e in friday["events"]}
        assert "pre_startup" in executed and "briefing" in executed
        missed_reason = next(r for r in friday["reasons"] if "SESSION WINDOW MISSED" in r)
        for name in ("activation", "entry_cutoff", "flatten"):
            assert name in missed_reason
        assert "pre_startup" not in missed_reason
        assert friday["failed_event_count"] == 3

    def test_no_fabricated_timestamps(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(2)
        driver.moment = at(MON, 6, 0)
        driver.run_events(1)
        friday = driver.reports()[f"{FRI}-session.json"]
        assert {e["event"] for e in friday["events"]} == {"pre_startup", "briefing"}


class TestWakeAfterFlatten:
    def test_authority_safe_then_reconciled_then_non_qualifying(
        self, clock, tmp_path
    ) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(2)
        driver.moment = at(FRI, 12, 16)
        driver.supervisor.advance_authority(FRI)
        assert driver.supervisor._latch.state is SessionAuthority.FLATTENING

        # Next loop iteration (Monday's event) triggers the attestation.
        driver.run_events(1)
        friday = driver.reports()[f"{FRI}-session.json"]
        assert friday["qualifying"] is False
        assert friday["flat_state"] == str(FlatState.VERIFIED_FLAT)
        assert friday["authority_state"] == str(SessionAuthority.CLOSED)

    def test_late_flat_verification_does_not_qualify_the_session(
        self, clock, tmp_path
    ) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(2)
        driver.moment = at(MON, 6, 0)
        driver.run_events(1)
        friday = driver.reports()[f"{FRI}-session.json"]
        assert friday["flat_state"] == str(FlatState.VERIFIED_FLAT)
        assert friday["qualifying"] is False, (
            "recovery-time flat verification must not convert a missed session "
            "into a qualifying one (§31.2)"
        )


class TestWakeAfterFlattenBrokerDown:
    def test_unverified_flat_takes_the_halted_severe_path(self, clock, tmp_path) -> None:
        calls = {"n": 0}

        def probe() -> HealthReport:
            calls["n"] += 1
            if calls["n"] <= 1:  # Friday pre_startup is the only pre-outage probe
                return healthy()
            raise ConnectionError("broker unreachable during recovery")

        driver = Driver(clock, tmp_path, probe=probe)
        driver.run_events(2)
        driver.moment = at(MON, 6, 0)
        # Monday's first event triggers attestation, whose probe is call 2.
        driver.run_events(1)
        friday = driver.reports()[f"{FRI}-session.json"]
        assert friday["flat_state"] == str(FlatState.UNVERIFIED)
        assert friday["authority_state"] == str(SessionAuthority.HALTED)
        severe = [b for k, b in driver.sent if k is NotificationKind.DATA_OR_BROKER_FAILURE]
        assert any("MISSED SESSION" in b for b in severe)

    def test_missed_report_is_durable(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(2)
        driver.moment = at(MON, 6, 0)
        driver.run_events(1)
        assert (tmp_path / f"{FRI}-session.json").exists()


class TestRestartScenarios:
    def test_restart_after_session_with_no_report_attests_exactly_once(
        self, clock, tmp_path
    ) -> None:
        """The epoch is Thursday; Friday produced nothing; the supervisor
        restarts Monday. Friday is attested exactly once, from the epoch —
        no report file is needed as an anchor."""
        driver = Driver(clock, tmp_path, start=at(MON, 6, 0))
        driver.run_events(1)
        reports = driver.reports()
        assert f"{FRI}-session.json" in reports
        assert reports[f"{FRI}-session.json"]["qualifying"] is False

    def test_restart_after_completed_session_creates_no_duplicate(
        self, clock, tmp_path
    ) -> None:
        first = Driver(clock, tmp_path)
        first.run_events(5)
        normal = (tmp_path / f"{FRI}-session.json").read_text()

        second = Driver(clock, tmp_path, start=at(MON, 6, 0))
        second.run_events(1)
        assert (tmp_path / f"{FRI}-session.json").read_text() == normal, (
            "a completed normal report must never be replaced by a missed one"
        )

    def test_restart_after_missed_report_creates_no_duplicate(self, clock, tmp_path) -> None:
        first = Driver(clock, tmp_path)
        first.run_events(2)
        first.moment = at(MON, 6, 0)
        first.run_events(1)
        attested = (tmp_path / f"{FRI}-session.json").read_text()

        second = Driver(clock, tmp_path, start=at(MON, 8, 30))
        second.run_events(1)
        assert (tmp_path / f"{FRI}-session.json").read_text() == attested

    def test_a_missed_report_is_never_upgraded_to_qualifying(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(2)
        driver.moment = at(MON, 6, 0)
        driver.run_events(5)  # a full clean Monday session on top
        friday = driver.reports()[f"{FRI}-session.json"]
        monday = driver.reports()[f"{MON}-session.json"]
        assert friday["qualifying"] is False
        assert monday["qualifying"] is True, "Monday itself is unaffected"

    def test_multiple_iterations_after_recovery_still_one_report(
        self, clock, tmp_path
    ) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_events(2)
        driver.moment = at(MON, 6, 0)
        scheduled = next_event(clock, driver.moment)
        for _ in range(4):  # repeated loop passes before the event fires
            driver.supervisor.advance_authority(scheduled.session_date)
            driver.supervisor.attest_missed_sessions(scheduled)
        assert len(driver.reports()) == 1
        assert f"{FRI}-session.json" in driver.reports()


class TestMultiDayOutage:
    def test_each_missed_weekday_attested_weekends_skipped(self, clock, tmp_path) -> None:
        """Down from Friday morning through the following Tuesday: Friday and
        Monday are attested; Saturday and Sunday are not."""
        driver = Driver(clock, tmp_path)
        driver.run_events(5)  # Friday completes normally
        driver.moment = at(TUE + dt.timedelta(days=1), 6, 0)  # wake Wednesday
        driver.run_events(1)
        names = set(driver.reports())
        assert f"{MON}-session.json" in names
        assert f"{TUE}-session.json" in names
        weekend = {f"{FRI + dt.timedelta(days=1)}-session.json",
                   f"{FRI + dt.timedelta(days=2)}-session.json"}
        assert not (weekend & names), "no Saturday/Sunday artifacts"

    def test_fresh_install_attests_nothing(self, clock, tmp_path) -> None:
        """Genuinely uninitialized = no operational epoch, NOT empty reports."""
        driver = Driver(clock, tmp_path, start=at(MON, 6, 0), epoch=None)
        scheduled = next_event(clock, driver.moment)
        driver.supervisor.advance_authority(scheduled.session_date)
        assert driver.supervisor.attest_missed_sessions(scheduled) == []
        assert driver.reports() == {}


class TestEventuallyExhaustiveRecovery:
    """Owner amendment 1: the batch limit bounds a PASS, never the backlog."""

    @staticmethod
    def _expected(epoch: dt.date, before: dt.date) -> list[dt.date]:
        day, out = epoch + dt.timedelta(days=1), []
        while day < before:
            if day.weekday() < 5:
                out.append(day)
            day += dt.timedelta(days=1)
        return out

    def _run_recovery(self, clock, tmp_path, epoch, passes):
        from trading_firm.runner.schedule import next_event as ne

        driver = Driver(clock, tmp_path, start=at(MON, 6, 0), epoch=epoch)
        scheduled = ne(clock, driver.moment)
        results = []
        for _ in range(passes):
            driver.supervisor.advance_authority(scheduled.session_date)
            results.append(driver.supervisor.attest_missed_sessions(scheduled))
        return driver, results

    def test_one_missing_session(self, clock, tmp_path) -> None:
        driver, results = self._run_recovery(clock, tmp_path, FRI - dt.timedelta(days=1), 1)
        assert len(results[0]) == 1
        assert f"{FRI}-session.json" in driver.reports()

    def test_exactly_ten_missing_fit_one_pass(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 26)  # Sunday; 10 weekdays lie before MON
        expected = self._expected(epoch, MON)
        assert len(expected) == 10
        driver, results = self._run_recovery(clock, tmp_path, epoch, 1)
        assert len(results[0]) == 10
        assert driver.supervisor.attestation_backlog(MON) == []

    def test_eleven_missing_take_two_passes(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 23)  # Thursday; 11 weekdays lie before MON
        expected = self._expected(epoch, MON)
        assert len(expected) == 11
        driver, results = self._run_recovery(clock, tmp_path, epoch, 2)
        assert [len(r) for r in results] == [10, 1]
        assert driver.supervisor.attestation_backlog(MON) == []

    def test_twenty_five_plus_missing_resolve_across_batches(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 1)
        expected = self._expected(epoch, MON)
        assert len(expected) >= 25
        driver, results = self._run_recovery(clock, tmp_path, epoch, 10)
        sizes = [len(r) for r in results if r]
        assert all(s <= 10 for s in sizes), "no pass may exceed the batch limit"
        assert sum(sizes) == len(expected), "the backlog is exhausted, never truncated"
        assert driver.supervisor.attestation_backlog(MON) == []

    def test_recovery_is_oldest_first(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 23)
        expected = self._expected(epoch, MON)
        driver, results = self._run_recovery(clock, tmp_path, epoch, 1)
        attested = sorted(
            dt.date.fromisoformat(n[: -len("-session.json")]) for n in driver.reports()
        )
        assert attested == expected[:10], "first batch must be the OLDEST ten"

    def test_no_duplicates_across_batches(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 23)
        driver, _ = self._run_recovery(clock, tmp_path, epoch, 5)
        contents = {n: (tmp_path / n).read_text() for n in driver.reports()}
        driver2, _ = self._run_recovery(clock, tmp_path, epoch, 5)
        for name, body in contents.items():
            assert (tmp_path / name).read_text() == body, f"{name} was rewritten"

    def test_normal_and_missed_reports_are_preserved(self, clock, tmp_path) -> None:
        normal = Driver(clock, tmp_path, epoch=dt.date(2026, 7, 23))
        normal.run_events(5)  # Friday completes normally
        friday_body = (tmp_path / f"{FRI}-session.json").read_text()
        driver, _ = self._run_recovery(clock, tmp_path, dt.date(2026, 7, 23), 5)
        assert (tmp_path / f"{FRI}-session.json").read_text() == friday_body
        assert json.loads(friday_body)["qualifying"] is True

    def test_weekends_never_attested_in_deep_recovery(self, clock, tmp_path) -> None:
        driver, _ = self._run_recovery(clock, tmp_path, dt.date(2026, 7, 1), 10)
        for name in driver.reports():
            day = dt.date.fromisoformat(name[: -len("-session.json")])
            assert day.weekday() < 5, f"weekend artifact {name}"

    def test_eventual_invariant_exactly_one_artifact_per_expected_date(
        self, clock, tmp_path
    ) -> None:
        epoch = dt.date(2026, 7, 1)
        expected = self._expected(epoch, MON)
        driver, _ = self._run_recovery(clock, tmp_path, epoch, 10)
        names = sorted(driver.reports())
        assert len(names) == len(set(names)) == len(expected)
        assert {dt.date.fromisoformat(n[: -len("-session.json")]) for n in names} == set(
            expected
        )

    def test_one_summary_notification_per_pass(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 23)
        driver, results = self._run_recovery(clock, tmp_path, epoch, 2)
        summaries = [b for _, b in driver.sent if b.startswith("MISSED-SESSION RECOVERY")]
        assert len(summaries) == 2, "one summary per non-empty pass, not one per date"
        assert "1 older-than-batch session(s) still unresolved" in summaries[0]
        assert "Backlog clear" in summaries[1]

    def test_backlog_visible_while_unresolved(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 23)
        driver, _ = self._run_recovery(clock, tmp_path, epoch, 1)
        assert len(driver.supervisor.attestation_backlog(MON)) == 1, (
            "continuity must not read as reconciled while a backlog remains"
        )


class TestOperationalEpoch:
    """Owner amendment 2: empty reports are never proof of a fresh install."""

    def test_established_install_with_empty_reports_is_an_evidence_gap(
        self, clock, tmp_path
    ) -> None:
        driver = Driver(clock, tmp_path, start=at(MON, 6, 0), epoch=THU)
        driver.run_events(1)
        assert f"{FRI}-session.json" in driver.reports(), (
            "an epoch with no reports must recover the gap, not restart history"
        )

    def test_deleting_reports_cannot_reset_the_epoch(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path, start=at(MON, 6, 0), epoch=THU)
        driver.run_events(1)
        for name in list(driver.reports()):
            (tmp_path / name).unlink()
        # A new supervisor (restart) with the same durable epoch re-attests.
        second = Driver(clock, tmp_path, start=at(MON, 8, 0), epoch=THU)
        from trading_firm.runner.schedule import next_event as ne

        scheduled = ne(clock, second.moment)
        second.supervisor.advance_authority(scheduled.session_date)
        second.supervisor.attest_missed_sessions(scheduled)
        assert f"{FRI}-session.json" in second.reports()

    def test_epoch_reader_uses_the_database_not_reports(self, tmp_path, monkeypatch) -> None:
        import importlib.util
        import sqlite3
        import sys as _sys
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "run_supervisor_epoch", Path("scripts/run_supervisor.py").resolve()
        )
        module = importlib.util.module_from_spec(spec)
        _sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        db = tmp_path / "firm.sqlite"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE schema_migrations (name TEXT, applied_at TEXT)")
        conn.execute(
            "INSERT INTO schema_migrations VALUES ('0001_init.sql', '2026-08-01T06:16:59Z')"
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(module, "DB_PATH", db)
        assert module.operational_epoch() == dt.date(2026, 8, 1)

        # Restart (re-read) yields the same epoch; reports are irrelevant to it.
        assert module.operational_epoch() == dt.date(2026, 8, 1)
        # A missing database is the one genuinely uninitialized state.
        monkeypatch.setattr(module, "DB_PATH", tmp_path / "absent.sqlite")
        assert module.operational_epoch() is None
        # A corrupt database REFUSES composition (§31.7): it exists, so its
        # unreadable baseline is an evidence gap to surface loudly. The prior
        # contract returned None here, which silently emptied the backlog —
        # a fresh-install disguise for exactly the state that must never wear
        # one ("must never be silently treated as a fresh install").
        bad = tmp_path / "bad.sqlite"
        bad.write_text("not a database")
        monkeypatch.setattr(module, "DB_PATH", bad)
        with pytest.raises(RuntimeError, match="operational baseline unreadable"):
            module.operational_epoch()

    def test_recovery_earliest_date_comes_from_the_epoch(self, clock, tmp_path) -> None:
        epoch = dt.date(2026, 7, 23)
        driver = Driver(clock, tmp_path, start=at(MON, 6, 0), epoch=epoch)
        backlog = driver.supervisor.attestation_backlog(MON)
        assert backlog[0] == dt.date(2026, 7, 24), (
            "the first expected session is the first trading day after the epoch"
        )


class TestExistingSuitesUnaffected:
    def test_the_authority_suite_and_fixtures_still_hold(self) -> None:
        """Run inline so this file cannot pass while the others rot."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q",
             "tests/acceptance/test_supervisor_authority.py",
             "tests/unit/test_session_timing.py"],
            capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stdout[-2000:]

    def test_no_order_path_reachable_from_the_attestor(self) -> None:
        import ast
        from pathlib import Path

        source = Path("src/trading_firm/runner/supervisor.py").read_text()
        imports = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports |= {a.name for a in node.names}
        assert not {i for i in imports if "execution" in i}
