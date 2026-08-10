"""Bounded broker-verification retry (incidents 2026-08-06 and 2026-08-10).

The reproduction test is the point of this file: on 2026-08-10 the practice
host accepted the credential at 01:15, accepted it again on the account-list
request at the flatten boundary, rejected the identical header on
openPositions ~150 ms later, and accepted it after the session — a transient
server-side authorization blip. The single-shot probe turned that blip into
UNVERIFIED → HALTED → severe alert → non-qualifying. These tests reproduce the
incident deterministically, prove the bounded retry recovers it, and prove
fail-closed is untouched when the failure is persistent.
"""

from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.execution.credentials import CredentialError, practice_token
from trading_firm.notify.surface import NotificationKind
from trading_firm.runner.schedule import next_event
from trading_firm.runner.supervisor import (
    PROBE_ATTEMPTS,
    PROBE_RETRY_DELAY_SECONDS,
    HealthReport,
    Supervisor,
)
from trading_firm.runner.timing import FlatState, SessionAuthority
from trading_firm.sessions import SessionClock

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 8, 10)  # the incident session


class BrokerAuthError(RuntimeError):
    """Stands in for the transport's auth error; the supervisor catches by
    Exception, so the class identity is not load-bearing — the message is."""


AUTH_401 = (
    "HTTP 401 from the practice host on GET /v3/accounts/101-001-...-001/"
    "openPositions: credential rejected (Insufficient authorization to perform "
    "request.)"
)


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def healthy() -> HealthReport:
    return HealthReport(broker_reachable=True, account_flat=True, open_position_count=0)


class Driver:
    def __init__(self, clock, tmp_path, probe, start_hour=6):
        self.sent: list[tuple[NotificationKind, str]] = []
        self.slept: list[float] = []
        self.moment = dt.datetime.combine(DAY, dt.time(start_hour, 0), tzinfo=LONDON)
        self.clock = clock
        self.tmp_path = tmp_path
        self.supervisor = Supervisor(
            clock=clock,
            probe=probe,
            notify=lambda kind, body: (self.sent.append((kind, body)), True)[1],
            report_dir=tmp_path,
            now=lambda: self.moment,
            sleep=self.slept.append,
            epoch=DAY - dt.timedelta(days=3),
        )

    def run_events(self, count: int) -> None:
        for _ in range(count):
            scheduled = next_event(self.clock, self.moment)
            self.moment = scheduled.at + dt.timedelta(seconds=0.15)
            self.supervisor.handle(scheduled)

    def report(self) -> dict:
        return json.loads((self.tmp_path / f"{DAY}-session.json").read_text())


class TestIncidentReproduction:
    """The exact 2026-08-10 shape, then the fix."""

    def test_single_transient_401_at_flatten_no_longer_destroys_the_session(
        self, clock, tmp_path
    ) -> None:
        calls = {"n": 0}

        def flaky_at_flatten() -> HealthReport:
            calls["n"] += 1
            # Call 1: pre_startup (succeeded at 01:15 in the incident).
            # Call 2: flatten attempt 1 — the transient 401.
            # Call 3: flatten attempt 2 — the broker answers again.
            if calls["n"] == 2:
                raise BrokerAuthError(AUTH_401)
            return healthy()

        driver = Driver(clock, tmp_path, flaky_at_flatten)
        driver.run_events(5)
        report = driver.report()
        assert report["flat_state"] == str(FlatState.VERIFIED_FLAT)
        assert report["qualifying"] is True
        assert report["authority_state"] == str(SessionAuthority.CLOSED)

    def test_the_recovery_leaves_evidence_in_the_record(self, clock, tmp_path) -> None:
        calls = {"n": 0}

        def flaky(_c=calls) -> HealthReport:
            _c["n"] += 1
            if _c["n"] == 2:
                raise BrokerAuthError(AUTH_401)
            return healthy()

        driver = Driver(clock, tmp_path, flaky)
        driver.run_events(5)
        flatten = next(e for e in driver.report()["events"] if e["event"] == "flatten")
        assert "verified on attempt 2/3" in flatten["outcome"], (
            "a recovered transient must stay visible, not be hidden by the recovery"
        )

    def test_retry_delays_are_deterministic(self, clock, tmp_path) -> None:
        calls = {"n": 0}

        def flaky(_c=calls) -> HealthReport:
            _c["n"] += 1
            if _c["n"] == 2:
                raise BrokerAuthError(AUTH_401)
            return healthy()

        driver = Driver(clock, tmp_path, flaky)
        driver.run_events(5)
        retry_sleeps = [s for s in driver.slept if s == PROBE_RETRY_DELAY_SECONDS]
        assert retry_sleeps == [PROBE_RETRY_DELAY_SECONDS], "exactly one fixed-delay retry"

    def test_retries_do_not_inflate_boundary_timing(self, clock, tmp_path) -> None:
        """`handle()` stamps the event before the probe runs, so re-asking the
        broker spends the §31.2 verification window, never the boundary's
        timing budget."""
        calls = {"n": 0}

        def flaky(_c=calls) -> HealthReport:
            _c["n"] += 1
            if _c["n"] == 2:
                raise BrokerAuthError(AUTH_401)
            return healthy()

        driver = Driver(clock, tmp_path, flaky)
        driver.run_events(5)
        flatten = next(e for e in driver.report()["events"] if e["event"] == "flatten")
        assert flatten["timing_status"] == "on_time"
        assert flatten["lateness_s"] < 1.0


class TestFailClosedUnchanged:
    def test_persistent_401_still_yields_unverified_halted_nonqualifying(
        self, clock, tmp_path
    ) -> None:
        calls = {"n": 0}

        def dead_at_flatten(_c=calls) -> HealthReport:
            _c["n"] += 1
            if _c["n"] >= 2:
                raise BrokerAuthError(AUTH_401)
            return healthy()

        driver = Driver(clock, tmp_path, dead_at_flatten)
        driver.run_events(5)
        report = driver.report()
        assert report["flat_state"] == str(FlatState.UNVERIFIED)
        assert report["qualifying"] is False
        assert report["authority_state"] == str(SessionAuthority.HALTED)
        assert calls["n"] == 1 + PROBE_ATTEMPTS, "bounded: startup + exactly 3 flatten attempts"
        severe = [b for k, b in driver.sent if k is NotificationKind.DATA_OR_BROKER_FAILURE]
        assert any("could NOT" in b for b in severe)

    def test_a_401_can_never_produce_flat_true(self, clock, tmp_path) -> None:
        def always_401() -> HealthReport:
            raise BrokerAuthError(AUTH_401)

        driver = Driver(clock, tmp_path, always_401)
        driver.run_events(5)
        report = driver.report()
        assert report["flat_state"] != str(FlatState.VERIFIED_FLAT)
        assert report["session_health"] == "DEGRADED"

    def test_verified_non_flat_is_never_retried_into_anything_else(
        self, clock, tmp_path
    ) -> None:
        """An open position is a SUCCESSFUL verification. The retry exists for
        raised errors only — it must not re-ask until the answer improves."""
        calls = {"n": 0}

        def open_position(_c=calls) -> HealthReport:
            _c["n"] += 1
            if _c["n"] >= 2:
                return HealthReport(
                    broker_reachable=True, account_flat=False, open_position_count=1
                )
            return healthy()

        driver = Driver(clock, tmp_path, open_position)
        driver.run_events(5)
        report = driver.report()
        assert report["flat_state"] == str(FlatState.VERIFIED_NON_FLAT)
        assert calls["n"] == 2, "one startup call + ONE flatten call — no retry on success"
        assert any(k is NotificationKind.RISK_HALT for k, _ in driver.sent)

    def test_retry_budget_fits_the_ratified_windows(self) -> None:
        worst_case = (PROBE_ATTEMPTS - 1) * PROBE_RETRY_DELAY_SECONDS
        assert worst_case <= 40, "must leave room for request time inside the 60 s window"
        from trading_firm.runner.timing import FLAT_VERIFICATION_DEADLINE_SECONDS

        assert worst_case < FLAT_VERIFICATION_DEADLINE_SECONDS

    def test_transient_at_pre_startup_also_recovers(self, clock, tmp_path) -> None:
        calls = {"n": 0}

        def flaky_at_startup(_c=calls) -> HealthReport:
            _c["n"] += 1
            if _c["n"] == 1:
                raise BrokerAuthError(AUTH_401)
            return healthy()

        driver = Driver(clock, tmp_path, flaky_at_startup)
        driver.run_events(5)
        report = driver.report()
        assert report["qualifying"] is True
        start = next(e for e in report["events"] if e["event"] == "pre_startup")
        assert "verified on attempt 2/3" in start["outcome"]


class TestCredentialIsolation:
    def test_practice_loader_cannot_consume_a_live_variable(self, monkeypatch) -> None:
        """Only OANDA_DEMO_API_TOKEN is ever read. A live token in the
        environment is invisible to the practice client, so it cannot be
        consumed accidentally."""
        monkeypatch.delenv("OANDA_DEMO_API_TOKEN", raising=False)
        monkeypatch.setenv("OANDA_API_TOKEN", "a" * 32 + "-" + "b" * 32)
        monkeypatch.setenv("OANDA_LIVE_API_TOKEN", "c" * 32 + "-" + "d" * 32)
        with pytest.raises(CredentialError, match="OANDA_DEMO_API_TOKEN"):
            practice_token()

    def test_auth_error_text_names_no_secret(self) -> None:
        """The incident's error text carried variable NAME and OANDA's message
        only — assert the transport's template stays that way."""
        from pathlib import Path

        source = Path("src/trading_firm/execution/oanda_transport.py").read_text()
        assert "credential rejected ({_error_message(raw)})" in source
        # The ONLY {token} interpolation permitted is the Authorization header
        # itself; the error template interpolates the variable NAME, never the
        # value.
        assert source.count("{token}") == 1
        assert 'f"Bearer {token}"' in source
