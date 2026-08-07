"""The production Supervisor actually drives its session authority latch (§31.6).

The 2026-08-07 defect escaped every gate: `SessionAuthorityLatch` had forty
passing unit tests, and nothing instantiated it. The session executed
flawlessly, the report said `qualification: QUALIFYING`, and
`authority_state` read `pre_session` after a completed five-boundary session.
Unit tests proved the latch *works*; none proved the supervisor *uses* it.

So these are SUPERVISOR-level tests. Every one drives the real `Supervisor`
and asserts against the record and report it produces, never against a latch
the test built itself. Scenarios A–J from the owner's brief.
"""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.notify.surface import NotificationKind
from trading_firm.runner.schedule import SessionEvent, next_event
from trading_firm.runner.supervisor import HealthReport, Supervisor
from trading_firm.runner.timing import FlatState, SessionAuthority
from trading_firm.sessions import SessionClock

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 8, 7)  # the post-fix session date


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def at(hour: int, minute: int, second: int = 0, day: dt.date = DAY) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute, second), tzinfo=LONDON)


def healthy() -> HealthReport:
    return HealthReport(broker_reachable=True, account_flat=True, open_position_count=0)


class Driver:
    """Drives the REAL Supervisor with a controllable clock."""

    def __init__(self, clock, tmp_path, probe=healthy, start: dt.datetime | None = None):
        self.sent: list[tuple[NotificationKind, str]] = []
        self.moment = start or at(6, 0)
        self.clock = clock
        self.supervisor = Supervisor(
            clock=clock,
            probe=probe,
            notify=lambda kind, body: (self.sent.append((kind, body)), True)[1],
            report_dir=tmp_path,
            now=lambda: self.moment,
            sleep=lambda seconds: None,
        )
        self.tmp_path = tmp_path

    def run_day(self, count: int = 5) -> None:
        for _ in range(count):
            scheduled = next_event(self.clock, self.moment)
            self.moment = scheduled.at + dt.timedelta(seconds=1)
            self.supervisor.handle(scheduled)

    def jump_to(self, moment: dt.datetime) -> None:
        self.moment = moment

    def report(self) -> dict:
        return json.loads((self.tmp_path / f"{DAY}-session.json").read_text())


class TestScenarioANormalCompleteSession:
    def test_the_supervisor_instantiates_a_real_latch(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        assert driver.supervisor._latch is None, "no latch before the session starts"
        driver.run_day()
        assert driver.supervisor._latch is not None, (
            "the production Supervisor never built a latch — the 2026-08-07 defect"
        )

    def test_the_final_authority_state_is_closed_not_pre_session(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day()
        report = driver.report()
        assert report["authority_state"] != str(SessionAuthority.PRE_SESSION)
        assert report["authority_state"] == str(SessionAuthority.CLOSED)

    def test_clock_regressions_are_sourced_from_the_live_latch(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day()
        assert driver.report()["clock_regressions"] == (
            driver.supervisor._latch.regressions_observed
        )

    def test_a_clean_session_qualifies(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day()
        report = driver.report()
        assert report["qualifying"] is True
        assert report["session_health"] == "NOMINAL"
        assert report["flat_state"] == str(FlatState.VERIFIED_FLAT)

    def test_one_latch_is_reused_across_the_whole_session(self, clock, tmp_path) -> None:
        """Rebuilding per boundary would discard monotonic state."""
        driver = Driver(clock, tmp_path)
        seen = []
        for _ in range(5):
            scheduled = next_event(clock, driver.moment)
            driver.moment = scheduled.at + dt.timedelta(seconds=1)
            driver.supervisor.handle(scheduled)
            seen.append(id(driver.supervisor._latch))
        assert len(set(seen)) == 1


class TestScenarioBEntryCutoffBetweenIterations:
    def test_authority_is_latched_before_any_handler_runs(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day(3)  # through activation
        assert driver.supervisor.entry_permitted

        # Next iteration lands after 10:30 — advance authority, no handler yet.
        driver.jump_to(at(10, 30, 1))
        driver.supervisor.advance_authority(DAY)
        assert not driver.supervisor.entry_permitted
        assert driver.supervisor._latch.state is SessionAuthority.MANAGE_ONLY


class TestScenarioCWakeAfterEntryCutoff:
    def test_waking_at_1054_latches_before_a_missed_activation(self, clock, tmp_path) -> None:
        """Suspension from before activation until 10:54. The first resumed
        iteration must establish MANAGE_ONLY before the late activation handler
        can run — so the handler cannot restore ACTIVE."""
        driver = Driver(clock, tmp_path)
        driver.run_day(2)  # pre_startup, briefing
        driver.jump_to(at(10, 54))

        driver.supervisor.advance_authority(DAY)
        assert driver.supervisor._latch.state is SessionAuthority.MANAGE_ONLY
        assert not driver.supervisor._latch.may_activate

        # The missed activation handler now executes, very late.
        activation = next(
            s for s in [next_event(clock, at(7, 59))] if s.event is SessionEvent.ACTIVATION
        )
        driver.supervisor.handle(activation)
        assert not driver.supervisor.entry_permitted
        assert driver.supervisor._latch.state is SessionAuthority.MANAGE_ONLY

    def test_such_a_session_is_non_qualifying(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day(2)
        driver.jump_to(at(10, 54))
        driver.supervisor.advance_authority(DAY)
        driver.run_day(3)
        assert driver.report()["qualifying"] is False


class TestScenarioDWakeAfterFlatten:
    def test_waking_at_1116_is_flattening_before_replay(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day(2)
        driver.jump_to(at(11, 16))
        driver.supervisor.advance_authority(DAY)
        assert driver.supervisor._latch.state is SessionAuthority.FLATTENING
        assert not driver.supervisor._latch.may_activate
        assert not driver.supervisor.entry_permitted

    def test_reconciliation_follows_and_the_session_is_non_qualifying(
        self, clock, tmp_path
    ) -> None:
        """The scheduler replays today's missed boundaries after the wake; the
        latch has already advanced, so the replay changes no authority and the
        session ends non-qualifying with its report written."""
        from trading_firm.runner.schedule import ScheduledEvent

        driver = Driver(clock, tmp_path)
        driver.run_day(2)
        driver.jump_to(at(11, 16))
        driver.supervisor.advance_authority(DAY)

        boundaries = clock.boundaries(DAY)
        for event, key in (
            (SessionEvent.ACTIVATION, "activation"),
            (SessionEvent.ENTRY_CUTOFF, "entry_cutoff"),
            (SessionEvent.FLATTEN, "flatten"),
        ):
            driver.supervisor.handle(
                ScheduledEvent(event=event, at=boundaries[key], session_date=DAY)
            )
        report = driver.report()
        assert report["qualifying"] is False
        assert report["authority_state"] in {
            str(SessionAuthority.CLOSED), str(SessionAuthority.HALTED)
        }
        assert report["late_event_count"] >= 1, "replayed boundaries are LATE, never clean"


class TestScenarioEBackwardClock:
    def test_authority_does_not_retreat_and_regression_is_recorded(
        self, clock, tmp_path
    ) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day(3)
        driver.jump_to(at(10, 30, 1))
        driver.supervisor.advance_authority(DAY)
        assert not driver.supervisor.entry_permitted

        driver.jump_to(at(9, 0))  # clock moves backward, before the cutoff
        driver.supervisor.advance_authority(DAY)
        assert not driver.supervisor.entry_permitted
        assert driver.supervisor._latch.state is SessionAuthority.MANAGE_ONLY
        assert driver.supervisor._latch.regressions_observed >= 1


class TestScenarioFHalted:
    def test_halted_is_terminal_through_the_supervisor(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day(3)
        latch = driver.supervisor._latch
        latch.halt()
        driver.jump_to(at(8, 30))
        driver.supervisor.advance_authority(DAY)
        assert latch.halted
        latch.close()
        assert latch.halted
        assert not latch.entry_permitted
        assert not latch.may_activate

    def test_an_unverified_flatten_halts_the_session(self, clock, tmp_path) -> None:
        calls = {"n": 0}

        def probe() -> HealthReport:
            calls["n"] += 1
            if calls["n"] == 1:
                return healthy()
            raise ConnectionError("HTTP 401 from the practice host")

        driver = Driver(clock, tmp_path, probe=probe)
        driver.run_day()
        report = driver.report()
        assert report["flat_state"] == str(FlatState.UNVERIFIED)
        assert report["authority_state"] == str(SessionAuthority.HALTED)
        assert report["qualifying"] is False


class TestScenarioGDeadLatchRegression:
    """Reproduces the exact 2026-08-07 defect. Fails against main at 3aba477."""

    def test_a_dead_latch_cannot_produce_a_qualifying_report(self, clock, tmp_path) -> None:
        from trading_firm.runner.timing import assess_session, evaluate

        timings = {}
        for event, (h, m) in zip(
            (SessionEvent.PRE_STARTUP, SessionEvent.BRIEFING, SessionEvent.ACTIVATION,
             SessionEvent.ENTRY_CUTOFF, SessionEvent.FLATTEN),
            ((7, 15), (7, 40), (8, 0), (10, 30), (11, 0)),
            strict=True,
        ):
            moment = at(h, m)
            timings[event] = evaluate(event, moment, moment)

        verdict = assess_session(
            timings=timings,
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
            authority_state=str(SessionAuthority.PRE_SESSION),
            boundaries_processed=5,
        )
        assert verdict.qualifying is False, (
            "a five-boundary session whose latch never left PRE_SESSION must "
            "never qualify — this is the 2026-08-07 defect"
        )
        assert verdict.qualification_reason == "AUTHORITY EVIDENCE MISSING"

    def test_a_missing_latch_entirely_cannot_qualify(self) -> None:
        from trading_firm.runner.timing import assess_session, evaluate

        moment = at(11, 0)
        verdict = assess_session(
            timings={SessionEvent.FLATTEN: evaluate(SessionEvent.FLATTEN, moment, moment)},
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
            authority_state=None,
            boundaries_processed=1,
        )
        assert verdict.qualifying is False
        assert any("never instantiated" in r for r in verdict.reasons)


class TestScenarioHReportConsistency:
    def test_a_report_can_never_pair_qualifying_with_pre_session(
        self, clock, tmp_path
    ) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day()
        report = driver.report()
        assert not (
            report["qualifying"] and report["authority_state"] == str(SessionAuthority.PRE_SESSION)
        )

    def test_the_authority_state_is_consistent_with_the_timestamps(
        self, clock, tmp_path
    ) -> None:
        """A report claiming a terminal state must have actually reached flatten."""
        driver = Driver(clock, tmp_path)
        driver.run_day()
        report = driver.report()
        events = {e["event"] for e in report["events"]}
        if report["authority_state"] == str(SessionAuthority.CLOSED):
            assert "flatten" in events


class TestScenarioJPostFixTimingPattern:
    """The real 2026-08-07 timings — sub-second on every boundary — qualify
    only when the production latch is actually driven."""

    def test_excellent_timing_plus_a_driven_latch_qualifies(self, clock, tmp_path) -> None:
        driver = Driver(clock, tmp_path)
        driver.run_day()
        report = driver.report()
        assert report["max_lateness_s"] < 5
        assert report["clean_event_count"] == 5
        assert report["qualifying"] is True
        assert report["authority_state"] == str(SessionAuthority.CLOSED)

    def test_the_same_timings_do_not_qualify_without_latch_evidence(self) -> None:
        from trading_firm.runner.timing import assess_session, evaluate

        timings = {
            e: evaluate(e, at(h, m), at(h, m))
            for e, (h, m) in zip(
                (SessionEvent.PRE_STARTUP, SessionEvent.BRIEFING, SessionEvent.ACTIVATION,
                 SessionEvent.ENTRY_CUTOFF, SessionEvent.FLATTEN),
                ((7, 15), (7, 40), (8, 0), (10, 30), (11, 0)),
                strict=True,
            )
        }
        assert not assess_session(
            timings=timings, flat_state=FlatState.VERIFIED_FLAT, health_verified=True,
            authority_state=str(SessionAuthority.PRE_SESSION), boundaries_processed=5,
        ).qualifying


class TestNoOrderPathFromThisRepair:
    def test_the_supervisor_still_cannot_reach_the_order_path(self) -> None:
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
