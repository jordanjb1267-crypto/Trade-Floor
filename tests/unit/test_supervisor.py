"""Supervisor lifecycle (§18, §19, §14/F-5, §0.10) as a pure sequence.

Every side effect is injected, so a full session day — healthy, degraded, and
not-flat — runs as a deterministic test with no sockets, no clock, no disk
beyond tmp_path.
"""

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.notify.surface import NotificationKind
from trading_firm.runner.schedule import next_event
from trading_firm.runner.supervisor import HealthReport, Supervisor
from trading_firm.sessions import SessionClock

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 7, 29)  # Wednesday


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def healthy() -> HealthReport:
    return HealthReport(broker_reachable=True, account_flat=True, open_position_count=0)


class Harness:
    """Drives a supervisor through a whole session day event by event."""

    def __init__(self, clock, tmp_path, probe=healthy):
        self.sent: list[tuple[NotificationKind, str]] = []
        self.probe = probe
        self.moment = dt.datetime.combine(DAY, dt.time(6, 0), tzinfo=LONDON)
        self.supervisor = Supervisor(
            clock=clock,
            probe=lambda: self.probe(),
            notify=self._notify,
            report_dir=tmp_path,
            now=lambda: self.moment,
            sleep=lambda seconds: None,
        )
        self.clock = clock

    def _notify(self, kind, body) -> bool:
        self.sent.append((kind, body))
        return True

    def run_day(self) -> None:
        for _ in range(5):
            scheduled = next_event(self.clock, self.moment)
            self.moment = scheduled.at + dt.timedelta(seconds=1)
            self.supervisor.handle(scheduled)


class TestHealthyDay:
    def test_the_owner_hears_start_and_end(self, clock, tmp_path) -> None:
        harness = Harness(clock, tmp_path)
        harness.run_day()
        kinds = [kind for kind, _ in harness.sent]
        assert kinds == [
            NotificationKind.SESSION_START_HEALTH,
            NotificationKind.DAILY_SESSION_REPORT,
        ], "a nominal day is two messages: starting, and done — not a feed"

    def test_the_report_is_written_and_says_shadow_zero_orders(self, clock, tmp_path) -> None:
        harness = Harness(clock, tmp_path)
        harness.run_day()
        report = json.loads((tmp_path / f"{DAY}-session.json").read_text())
        assert report["environment"] == "shadow"
        assert report["orders_placed"] == 0
        assert report["degraded"] is False
        assert len(report["events"]) == 5

    def test_flatten_is_verified_not_assumed(self, clock, tmp_path) -> None:
        harness = Harness(clock, tmp_path)
        harness.run_day()
        report = json.loads((tmp_path / f"{DAY}-session.json").read_text())
        flatten = [e for e in report["events"] if e["event"] == "flatten"]
        assert flatten and flatten[0]["outcome"] == "verified flat"


class TestDegradedDay:
    """§0.10: a failed pre-startup probe fails the day closed — but the
    schedule is kept, because the flatten check must still run."""

    @staticmethod
    def _down() -> HealthReport:
        raise ConnectionError("practice host unreachable")

    def test_a_raising_probe_never_crashes_and_fails_closed(self, clock, tmp_path) -> None:
        harness = Harness(clock, tmp_path, probe=self._down)
        harness.run_day()  # does not raise
        report = json.loads((tmp_path / f"{DAY}-session.json").read_text())
        assert report["degraded"] is True

    def test_the_owner_is_alerted_at_start_and_flatten_stays_unverified(
        self, clock, tmp_path
    ) -> None:
        harness = Harness(clock, tmp_path, probe=self._down)
        harness.run_day()
        kinds = [kind for kind, _ in harness.sent]
        assert kinds[0] is NotificationKind.DATA_OR_BROKER_FAILURE
        assert NotificationKind.SESSION_START_HEALTH not in kinds
        # The flatten boundary still reported, as its own alert:
        assert kinds.count(NotificationKind.DATA_OR_BROKER_FAILURE) == 2
        report = json.loads((tmp_path / f"{DAY}-session.json").read_text())
        flatten = [e for e in report["events"] if e["event"] == "flatten"]
        assert "UNVERIFIED" in flatten[0]["outcome"]

    def test_evaluation_boundaries_record_the_withholding(self, clock, tmp_path) -> None:
        harness = Harness(clock, tmp_path, probe=self._down)
        harness.run_day()
        report = json.loads((tmp_path / f"{DAY}-session.json").read_text())
        briefing = [e for e in report["events"] if e["event"] == "briefing"]
        assert briefing[0]["outcome"] == "skipped: session degraded"


class TestNotFlatAtEleven:
    """F-5: the one state that must page the owner as a RISK_HALT."""

    def test_an_open_position_at_flatten_is_a_risk_halt(self, clock, tmp_path) -> None:
        calls = {"n": 0}

        def probe() -> HealthReport:
            calls["n"] += 1
            if calls["n"] == 1:
                return healthy()
            return HealthReport(
                broker_reachable=True, account_flat=False, open_position_count=1
            )

        harness = Harness(clock, tmp_path, probe=probe)
        harness.run_day()
        kinds = [kind for kind, _ in harness.sent]
        assert NotificationKind.RISK_HALT in kinds
        halt = next(body for kind, body in harness.sent if kind is NotificationKind.RISK_HALT)
        assert "inviolate" in halt


class TestNotificationFailureIsNotFatal:
    def test_a_dead_notifier_does_not_stop_the_session(self, clock, tmp_path) -> None:
        harness = Harness(clock, tmp_path)
        harness.supervisor._notify = lambda kind, body: False  # delivery fails
        harness.run_day()  # does not raise
        assert (tmp_path / f"{DAY}-session.json").exists(), (
            "the operational record is written even when the owner is unreachable "
            "(§18: local record plus notification path, not instead of)"
        )


class TestStopping:
    def test_run_forever_exits_promptly_on_stop(self, clock, tmp_path) -> None:
        harness = Harness(clock, tmp_path)
        harness.supervisor.stopping = True
        harness.supervisor.run_forever()  # returns immediately, handles nothing
        assert harness.sent == []
