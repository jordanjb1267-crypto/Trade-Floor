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
    NonRetryableProbeError,
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


class SimClock:
    """Wall clock that advances when the supervisor sleeps or the probe works."""

    def __init__(self, start: dt.datetime):
        self.t = start

    def now(self) -> dt.datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += dt.timedelta(seconds=seconds)


def sim_supervisor(clock, tmp_path, probe, sim: SimClock) -> Supervisor:
    return Supervisor(
        clock=clock,
        probe=probe,
        notify=lambda kind, body: True,
        report_dir=tmp_path,
        now=sim.now,
        sleep=sim.sleep,
        epoch=DAY - dt.timedelta(days=3),
    )


class TestDeadlineGovernance:
    """Blocker 1: verification is governed by the boundary's own window."""

    T0 = dt.datetime.combine(DAY, dt.time(11, 0), tzinfo=LONDON)

    def test_retry_not_started_when_budget_cannot_fit(self, clock, tmp_path) -> None:
        """Requirement 3: a retry that could not legally complete never starts."""
        from trading_firm.runner.supervisor import PROBE_ATTEMPT_BUDGET_SECONDS

        sim = SimClock(self.T0)
        calls = {"n": 0}

        def slow_failure() -> HealthReport:
            calls["n"] += 1
            sim.t += dt.timedelta(seconds=24)  # attempt consumes its budget
            raise BrokerAuthError(AUTH_401)

        sup = sim_supervisor(clock, tmp_path, slow_failure, sim)
        deadline = self.T0 + dt.timedelta(seconds=60)
        report = sup._checked_probe(deadline=deadline)
        # t=24 after attempt 1; sleep guard: 24+15+25=64>60 -> stop, one attempt.
        assert calls["n"] == 1
        assert not report.broker_reachable
        assert sim.t <= deadline, "must stop early, not run out the window"
        assert PROBE_ATTEMPT_BUDGET_SECONDS == 25.0

    def test_sleep_never_crosses_the_deadline(self, clock, tmp_path) -> None:
        """Requirement 4: the guard covers sleep + attempt, so the loop cannot
        doze past the boundary."""
        sim = SimClock(self.T0 + dt.timedelta(seconds=25))  # 35 s remain
        slept: list[float] = []
        original_sleep = sim.sleep

        def tracked_sleep(seconds: float) -> None:
            slept.append(seconds)
            original_sleep(seconds)

        def fast_failure() -> HealthReport:
            sim.t += dt.timedelta(seconds=1)
            raise BrokerAuthError(AUTH_401)

        sup = Supervisor(
            clock=clock, probe=fast_failure, notify=lambda k, b: True,
            report_dir=tmp_path, now=sim.now, sleep=tracked_sleep,
            epoch=DAY - dt.timedelta(days=3),
        )
        deadline = self.T0 + dt.timedelta(seconds=60)
        sup._checked_probe(deadline=deadline)
        # after attempt1 at t=26: guard 26-60+15+25 = 6 > 0 -> no sleep at all.
        assert slept == []
        assert sim.t <= deadline

    def test_success_after_deadline_is_not_verified_flat(self, clock, tmp_path) -> None:
        """Requirement 5: the load-bearing theorem — a late 2xx is evidence,
        never verification."""
        sim = SimClock(self.T0)

        def slow_success() -> HealthReport:
            sim.t += dt.timedelta(seconds=70)  # completes past the 60 s window
            return healthy()

        sup = sim_supervisor(clock, tmp_path, slow_success, sim)
        report = sup._checked_probe(deadline=self.T0 + dt.timedelta(seconds=60))
        assert not report.broker_reachable, "late success must route UNVERIFIED"
        assert not report.account_flat
        assert "AFTER the authorized deadline" in report.detail
        assert "account observed flat" in report.detail, "observation kept as evidence"

    def test_late_verification_cannot_qualify(self, clock, tmp_path) -> None:
        """Requirements 5+7+26 end to end: a slow broker at flatten yields an
        UNVERIFIED, HALTED, non-qualifying session even though the eventual
        answer was 'flat'."""
        state = {"calls": 0}
        sim = SimClock(dt.datetime.combine(DAY, dt.time(6, 0), tzinfo=LONDON))

        def slow_at_flatten() -> HealthReport:
            state["calls"] += 1
            if state["calls"] >= 2:  # flatten probes only
                sim.t += dt.timedelta(seconds=70)
            return healthy()

        sup = sim_supervisor(clock, tmp_path, slow_at_flatten, sim)
        for _ in range(5):
            scheduled = next_event(clock, sim.t)
            sim.t = scheduled.at + dt.timedelta(seconds=0.15)
            sup.handle(scheduled)
        report = json.loads((tmp_path / f"{DAY}-session.json").read_text())
        assert report["flat_state"] == str(FlatState.UNVERIFIED)
        assert report["qualifying"] is False
        assert report["authority_state"] == str(SessionAuthority.HALTED)

    def test_flatten_uses_the_authoritative_deadline_function(self) -> None:
        """Requirement 8: no caller invents a deadline."""
        from pathlib import Path

        source = Path("src/trading_firm/runner/supervisor.py").read_text()
        assert "deadline=flat_verification_deadline(scheduled.at)" in source

    def test_pre_startup_uses_its_own_checkpoint_window(self) -> None:
        """Requirement 9: pre-startup budgets against §31.1, not §31.2."""
        from pathlib import Path

        source = Path("src/trading_firm/runner/supervisor.py").read_text()
        assert "POLICY[SessionEvent.PRE_STARTUP].tolerance_seconds" in source

    def test_no_deadline_keeps_bounded_recovery_behavior(self, clock, tmp_path) -> None:
        """Attestation reconciliation has no boundary window; the plain
        3-attempt bound still applies."""
        sim = SimClock(self.T0)
        calls = {"n": 0}

        def always_fail() -> HealthReport:
            calls["n"] += 1
            raise BrokerAuthError(AUTH_401)

        sup = sim_supervisor(clock, tmp_path, always_fail, sim)
        report = sup._checked_probe(deadline=None)
        assert calls["n"] == PROBE_ATTEMPTS
        assert not report.broker_reachable


class TestFalsePassContract:
    """Blocker 2: an error body must never verify the account flat."""

    @staticmethod
    def _probe_with(monkeypatch, response=None, raises=None):
        import importlib.util
        import sys as _sys
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "run_supervisor_probe", Path("scripts/run_supervisor.py").resolve()
        )
        module = importlib.util.module_from_spec(spec)
        _sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        import trading_firm.execution.oanda_transport as transport_module

        class FakeTransport:
            _account_id = "101-001-TEST-001"

            def __init__(self, *args, **kwargs):
                pass

            def _request(self, method, path, body=None):
                if raises is not None:
                    raise raises
                return response

        monkeypatch.setattr(transport_module, "OandaPracticeTransport", FakeTransport)
        return module.probe

    @pytest.mark.parametrize(
        "body",
        [
            {"errorMessage": "Internal server error"},  # 10: 500 JSON body
            {"errorMessage": "The account was not found"},  # 12: 404/wrong account
            {"errorMessage": "Invalid value specified"},  # 13: 400 JSON body
            {"errorMessage": "Rate limit exceeded"},  # 14: 429 JSON body
            {"positions": None},  # 16 variant: field present, wrong type
            {"orders": [], "trades": []},  # 17: unrelated arrays
            {},  # 16: valid JSON without positions
        ],
    )
    def test_error_shaped_bodies_never_verify_flat(self, monkeypatch, body) -> None:
        probe = self._probe_with(monkeypatch, response=body)
        with pytest.raises(Exception, match="success schema"):
            probe()

    def test_non_dict_response_never_verifies_flat(self, monkeypatch) -> None:
        probe = self._probe_with(monkeypatch, response=["not", "a", "dict"])
        with pytest.raises(Exception, match="success schema"):
            probe()

    def test_valid_empty_positions_is_flat(self, monkeypatch) -> None:
        probe = self._probe_with(monkeypatch, response={"positions": []})
        report = probe()
        assert report.broker_reachable and report.account_flat

    def test_one_open_position_is_not_flat(self, monkeypatch) -> None:
        probe = self._probe_with(
            monkeypatch, response={"positions": [{"instrument": "GBP_USD"}]}
        )
        report = probe()
        assert report.broker_reachable and not report.account_flat
        assert report.open_position_count == 1

    def test_repeated_error_bodies_end_unverified(self, clock, tmp_path, monkeypatch) -> None:
        """Requirement 11, end to end: 500-shaped bodies at every flatten
        attempt leave the session UNVERIFIED, never VERIFIED_FLAT."""
        probe_fn = self._probe_with(monkeypatch, response={"errorMessage": "boom"})
        calls = {"n": 0}

        def wrapped() -> HealthReport:
            calls["n"] += 1
            if calls["n"] == 1:
                return healthy()  # pre_startup succeeds
            return probe_fn()  # flatten attempts hit the error body

        driver = Driver(clock, tmp_path, wrapped)
        driver.run_events(5)
        report = driver.report()
        assert report["flat_state"] == str(FlatState.UNVERIFIED)
        assert report["qualifying"] is False

    def test_credential_error_fails_immediately_no_sleep(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Requirements 21/22: a local deterministic failure gets exactly one
        attempt and zero retry sleeps."""
        calls = {"n": 0}

        def missing_credential() -> HealthReport:
            calls["n"] += 1
            raise NonRetryableProbeError("OANDA_DEMO_API_TOKEN not set (see .env.example)")

        driver = Driver(clock, tmp_path, missing_credential)
        driver.run_events(1)
        assert calls["n"] == 1, "no retry for a locally-deterministic failure"
        retry_sleeps = [s for s in driver.slept if s == PROBE_RETRY_DELAY_SECONDS]
        assert retry_sleeps == []

    def test_no_sleep_after_terminal_exhaustion(self, clock, tmp_path) -> None:
        """Requirement 25: the final failed attempt is not followed by a sleep."""
        def always_fail() -> HealthReport:
            raise BrokerAuthError(AUTH_401)

        driver = Driver(clock, tmp_path, always_fail)
        driver.run_events(1)
        retry_sleeps = [s for s in driver.slept if s == PROBE_RETRY_DELAY_SECONDS]
        assert len(retry_sleeps) == PROBE_ATTEMPTS - 1

    def test_2026_08_10_authoritative_result_unchanged(self) -> None:
        """Requirement 29: the incident session stays exactly as recorded.

        Reads the CANONICAL committed evidence, not the gitignored production
        artifact — the original version did the latter, so this required
        invariant passed only on the production machine and left the
        repository's deterministic CI red from the day it landed. The
        canonical fixture's provenance, secret-freedom, and exact equivalence
        to the production artifact (where that artifact exists) are proven in
        tests/unit/test_historical_authority.py; this assertion keeps the
        incident's contract anchored beside the incident's other regressions.
        """
        from pathlib import Path

        report = json.loads(
            Path("tests/fixtures/2026-08-10-session.authoritative.json").read_text()
        )
        assert report["session_health"] == "DEGRADED"
        assert report["qualification"] == "NON_QUALIFYING"
        assert report["flat_state"] == "UNVERIFIED"

    def test_no_secret_shapes_in_probe_or_report_strings(self, clock, tmp_path) -> None:
        """Requirement 31: nothing token-shaped in any persisted string."""
        import re

        def always_fail() -> HealthReport:
            raise BrokerAuthError(AUTH_401)

        driver = Driver(clock, tmp_path, always_fail)
        driver.run_events(5)
        blob = json.dumps(driver.report()) + " ".join(b for _, b in driver.sent)
        assert not re.search(r"[0-9a-f]{32}-[0-9a-f]{32}", blob)
        assert "Bearer" not in blob
