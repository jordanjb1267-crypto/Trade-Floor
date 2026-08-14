"""OANDA practice account pinning (retry-margin follow-up, 2026-08-11 review).

The pin removes per-attempt account discovery so the §31.2 window can hold
three legal verification attempts for the observed transient-failure class.
It is engineering insurance, NOT a fix for the broker-side 401 anomaly: on
2026-08-10/11 discovery SUCCEEDED while the scoped call failed, so removing
discovery would not have prevented those rejections — it buys margin only.

Every account id here is synthetic. No network I/O: urlopen is replaced with
a recorder, so the request-level proofs assert exactly which URLs were (and
were not) requested.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import urllib.error
from zoneinfo import ZoneInfo

import pytest

import trading_firm.execution.oanda_transport as transport_module
from trading_firm.execution.credentials import CredentialError, configured_account_id
from trading_firm.execution.oanda_transport import BrokerAuthError, OandaPracticeTransport
from trading_firm.runner.supervisor import (
    PINNED_PROBE_ATTEMPT_BUDGET_SECONDS,
    PROBE_ATTEMPT_BUDGET_SECONDS,
    PROBE_ATTEMPTS,
    PROBE_RETRY_DELAY_SECONDS,
    HealthReport,
    Supervisor,
)
from trading_firm.runner.timing import FLAT_VERIFICATION_DEADLINE_SECONDS

LONDON = ZoneInfo("Europe/London")
PIN = "101-001-00000000-001"  # synthetic


@pytest.fixture(scope="module")
def clock_cfg():
    from trading_firm.config import BASE_CONFIG_PATH, load_config
    from trading_firm.sessions import SessionClock

    return SessionClock(load_config(BASE_CONFIG_PATH).session)


FAKE_TOKEN = "a" * 32 + "-" + "b" * 32  # synthetic, shape-valid


class RecordingTransport:
    """Replaces urlopen: records every requested URL, serves canned bodies."""

    def __init__(self, monkeypatch, responses):
        self.urls: list[str] = []
        self._responses = responses  # list of (status, body-dict) or Exception
        self._index = 0

        def fake_urlopen(request, timeout=None):
            self.urls.append(request.full_url)
            action = self._responses[min(self._index, len(self._responses) - 1)]
            self._index += 1
            if isinstance(action, Exception):
                raise action
            status, body = action
            raw = json.dumps(body).encode()
            if status >= 400:
                raise urllib.error.HTTPError(
                    request.full_url, status, "err", {}, io.BytesIO(raw)
                )

            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return raw

            return _Resp()

        monkeypatch.setattr(transport_module.urllib.request, "urlopen", fake_urlopen)


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("OANDA_DEMO_API_TOKEN", FAKE_TOKEN)
    monkeypatch.delenv("OANDA_DEMO_ACCOUNT_ID", raising=False)
    return monkeypatch


class TestPinContract:
    def test_absent_pin_returns_none_for_discovery_fallback(self, creds) -> None:
        assert configured_account_id() is None

    def test_valid_pin_returns_the_exact_configured_id(self, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        assert configured_account_id() == PIN

    def test_present_but_empty_fails_closed(self, creds) -> None:
        """An attempted pin is never silently equivalent to no pin."""
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "")
        with pytest.raises(CredentialError, match="EMPTY"):
            configured_account_id()

    def test_whitespace_only_fails_closed(self, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "   ")
        with pytest.raises(CredentialError, match="EMPTY"):
            configured_account_id()

    def test_placeholder_fails_closed(self, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "<practice account>")
        with pytest.raises(CredentialError, match="placeholder"):
            configured_account_id()

    @pytest.mark.parametrize(
        "bad", ["101-001-XXXX-001", "abc-def-ghij-klm", "101001-00000000001", "1-2-3"]
    )
    def test_malformed_pin_fails_closed(self, creds, bad) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", bad)
        with pytest.raises(CredentialError):
            configured_account_id()


class TestRequestLevelProofs:
    def test_valid_pin_skips_discovery_entirely(self, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        recorder = RecordingTransport(creds, [(200, {"positions": []})])
        transport = OandaPracticeTransport(timeout_seconds=12.0)
        assert transport._account_id == PIN, "the scoped id is exactly the pin"
        transport._request("GET", f"/v3/accounts/{transport._account_id}/openPositions")
        assert all("/openPositions" in u for u in recorder.urls)
        assert not any(u.endswith("/v3/accounts") for u in recorder.urls), (
            "GET /v3/accounts must not be invoked when pinned"
        )

    def test_unpinned_path_still_performs_discovery(self, creds) -> None:
        recorder = RecordingTransport(
            creds, [(200, {"accounts": [{"id": PIN}]}), (200, {"positions": []})]
        )
        transport = OandaPracticeTransport(timeout_seconds=12.0)
        assert transport._account_id == PIN
        assert any(u.endswith("/v3/accounts") for u in recorder.urls)

    def test_pinned_failure_never_falls_back_to_discovery(self, creds) -> None:
        """THE no-fallback property: configured pin + scoped 401 -> error,
        never a second chance via /v3/accounts."""
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        recorder = RecordingTransport(
            creds, [(401, {"errorMessage": "Insufficient authorization to perform request."})]
        )
        transport = OandaPracticeTransport(timeout_seconds=12.0)
        with pytest.raises(BrokerAuthError):
            transport._request(
                "GET", f"/v3/accounts/{transport._account_id}/openPositions"
            )
        assert not any(u.endswith("/v3/accounts") for u in recorder.urls)

    @pytest.mark.parametrize(
        ("status", "body"),
        [
            (401, {"errorMessage": "Insufficient authorization to perform request."}),
            (403, {"errorMessage": "Forbidden"}),
            (404, {"errorMessage": "The account was not found"}),  # typo/deleted/inaccessible
        ],
    )
    def test_wrong_pin_http_failures_fail_closed(self, creds, status, body) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        recorder = RecordingTransport(creds, [(status, body)])
        transport = OandaPracticeTransport(timeout_seconds=12.0)
        with pytest.raises(Exception):  # noqa: B017 — auth raises; 404 body lacks the contract
            response = transport._request(
                "GET", f"/v3/accounts/{transport._account_id}/openPositions"
            )
            # non-auth statuses return the error body: the strict probe
            # contract must then refuse it
            assert not isinstance(response.get("positions"), list)
            raise AssertionError("error body must not satisfy the read contract")
        assert not any(u.endswith("/v3/accounts") for u in recorder.urls)

    def test_env_edits_cannot_switch_a_constructed_binding(self, creds) -> None:
        """The bound id lives on the transport instance; changing the process
        env after construction cannot re-point an existing binding."""
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        RecordingTransport(creds, [(200, {"positions": []})])
        transport = OandaPracticeTransport(timeout_seconds=12.0)
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "101-001-99999999-001")
        assert transport._account_id == PIN


class TestBudgetSelection:
    def _composition(self):
        import importlib.util
        import sys
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "rs_pin", Path("scripts/run_supervisor.py").resolve()
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_bound_account_selects_15s(self, creds) -> None:
        """The budget is a PURE function of the captured binding — it takes
        the binding as an argument precisely so it CANNOT read the
        environment independently of the account the probe will use
        (immutability remediation: one read feeds both)."""
        assert self._composition().probe_attempt_budget_seconds(PIN) == 15.0

    def test_resolved_absent_selects_25s(self, creds) -> None:
        assert self._composition().probe_attempt_budget_seconds(None) == 25.0

    def test_invalid_pin_fails_composition_before_any_budget_exists(self, creds) -> None:
        """The old contract gave a broken pin the conservative 25 s and let
        the probe fail later; the ratified immutability contract fails the
        COMPOSITION closed instead — a Supervisor is never constructed with
        a fallback account mode (proven end-to-end in
        TestProcessLevelBinding)."""
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "garbage")
        with pytest.raises(CredentialError):
            configured_account_id()

    def test_constants_are_the_reviewed_values(self) -> None:
        assert PINNED_PROBE_ATTEMPT_BUDGET_SECONDS == 15.0
        assert PROBE_ATTEMPT_BUDGET_SECONDS == 25.0
        assert PROBE_RETRY_DELAY_SECONDS == 15.0
        assert FLAT_VERIFICATION_DEADLINE_SECONDS == 60.0


class SimClock:
    def __init__(self, start: dt.datetime):
        self.t = start

    def now(self) -> dt.datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += dt.timedelta(seconds=seconds)


class TestPinnedScheduleProofs:
    """Section 7: deterministic schedules. Three attempts are NOT described as
    unconditionally guaranteed — they fit for the observed fast-failure class
    and are correctly suppressed for pathological slow failures."""

    T0 = dt.datetime.combine(dt.date(2026, 8, 12), dt.time(11, 0), tzinfo=LONDON)

    def _supervisor(self, clock_cfg, probe, sim, budget):
        return Supervisor(
            clock=clock_cfg,
            probe=probe,
            notify=lambda k, b: True,
            report_dir=None,  # never reached in _checked_probe-only tests
            now=sim.now,
            sleep=sim.sleep,
            probe_attempt_budget_seconds=budget,
        )

    def test_case_a_fast_fail_fast_fail_success_fits_three_attempts(
        self, clock_cfg
    ) -> None:
        sim = SimClock(self.T0)
        calls = {"n": 0}

        def fast_flaky() -> HealthReport:
            calls["n"] += 1
            sim.t += dt.timedelta(seconds=1)  # observed 401 latency class
            if calls["n"] <= 2:
                raise RuntimeError("HTTP 401 (transient)")
            return HealthReport(
                broker_reachable=True, account_flat=True, open_position_count=0
            )

        sup = self._supervisor(clock_cfg, fast_flaky, sim, 15.0)
        deadline = self.T0 + dt.timedelta(seconds=60)
        report = sup._checked_probe(deadline=deadline)
        assert calls["n"] == 3, "third attempt must legally start under the pinned budget"
        assert report.broker_reachable and report.account_flat
        assert "attempt 3/3" in report.detail
        assert sim.t <= deadline

    def test_case_a_would_stop_at_two_under_the_unpinned_budget(
        self, clock_cfg
    ) -> None:
        """The margin the pin buys, shown by contrast: same failure latencies,
        25 s budget, attempt 3 suppressed — the Aug-11 outcome."""
        sim = SimClock(self.T0)
        calls = {"n": 0}

        def fast_flaky() -> HealthReport:
            calls["n"] += 1
            sim.t += dt.timedelta(seconds=3)
            raise RuntimeError("HTTP 401 (transient)")

        sup = self._supervisor(clock_cfg, fast_flaky, sim, 25.0)
        sup._checked_probe(deadline=self.T0 + dt.timedelta(seconds=60))
        assert calls["n"] == 2

    def test_case_b_slow_failures_correctly_suppress_attempt_three(
        self, clock_cfg
    ) -> None:
        sim = SimClock(self.T0)
        calls = {"n": 0}

        def slow_fail() -> HealthReport:
            calls["n"] += 1
            sim.t += dt.timedelta(seconds=12)  # full request timeout each
            raise RuntimeError("timeout")

        sup = self._supervisor(clock_cfg, slow_fail, sim, 15.0)
        deadline = self.T0 + dt.timedelta(seconds=60)
        report = sup._checked_probe(deadline=deadline)
        assert calls["n"] == 2, "a2 ends T+39 > T+30 sleep-guard: attempt 3 suppressed"
        assert not report.broker_reachable
        assert sim.t <= deadline

    def test_case_c_late_success_remains_not_verified_flat(self, clock_cfg) -> None:
        sim = SimClock(self.T0)

        def slow_success() -> HealthReport:
            sim.t += dt.timedelta(seconds=70)
            return HealthReport(
                broker_reachable=True, account_flat=True, open_position_count=0
            )

        sup = self._supervisor(clock_cfg, slow_success, sim, 15.0)
        report = sup._checked_probe(deadline=self.T0 + dt.timedelta(seconds=60))
        assert not report.broker_reachable
        assert "AFTER the authorized deadline" in report.detail

    def test_no_sleep_after_success_or_terminal_condition(self, clock_cfg) -> None:
        sim = SimClock(self.T0)
        slept: list[float] = []
        orig = sim.sleep

        def tracked(seconds):
            slept.append(seconds)
            orig(seconds)

        def ok() -> HealthReport:
            sim.t += dt.timedelta(seconds=1)
            return HealthReport(
                broker_reachable=True, account_flat=True, open_position_count=0
            )

        sup = Supervisor(
            clock=clock_cfg, probe=ok, notify=lambda k, b: True, report_dir=None,
            now=sim.now, sleep=tracked, probe_attempt_budget_seconds=15.0,
        )
        sup._checked_probe(deadline=self.T0 + dt.timedelta(seconds=60))
        assert slept == []

    def test_deadline_attempts_and_delay_unchanged(self) -> None:
        assert PROBE_ATTEMPTS == 3
        assert PROBE_RETRY_DELAY_SECONDS == 15.0
        assert FLAT_VERIFICATION_DEADLINE_SECONDS == 60.0


class TestNoSecretsAndPolicy:
    def test_credential_error_messages_name_variables_not_values(self, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "")
        with pytest.raises(CredentialError) as caught:
            configured_account_id()
        assert "OANDA_DEMO_ACCOUNT_ID" in str(caught.value)
        assert FAKE_TOKEN not in str(caught.value)

    def test_shape_rule_is_not_claimed_as_a_practice_boundary(self) -> None:
        from pathlib import Path

        source = Path("src/trading_firm/execution/credentials.py").read_text()
        assert "NOT a practice-vs-live rule" in source


class TestProcessLevelBinding:
    """The ratified immutable-process-binding contract, proven end to end.

    The final V2 review demonstrated — through the real builder and real
    probe — that a Supervisor composed under PIN_A followed an in-process
    environment mutation to PIN_B, and that a pinned 15 s admission budget
    could later admit two-request discovery work. The binding is now
    resolved EXACTLY ONCE in build_supervisor() and closed into the probe,
    so account selection, request shape, and admission budget derive from
    one captured value for the life of the composition. Everything here
    drives the REAL builder and REAL transport with only urlopen replaced.

    The reviewed 51c289a stated this contract but never enforced it: its
    per-probe fresh transport re-read the environment. Fixing that is
    CONTRACT_BUG_FIXED, deliberately stricter than the frozen reference.
    """

    PIN_B = "101-001-22222222-001"
    PIN_C = "101-001-33333333-001"

    def build(self, clock_cfg, tmp_path, monkeypatch):
        import datetime as _dt
        import importlib.util
        import sys
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "rs_binding", Path("scripts/run_supervisor.py").resolve()
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        monkeypatch.setattr(module, "DB_PATH", tmp_path / "absent.sqlite")
        moment = _dt.datetime(2026, 8, 19, 6, 0, tzinfo=LONDON)
        supervisor = module.build_supervisor(
            clock_cfg,
            notify_fn=lambda kind, body: True,
            report_dir=tmp_path / "reports",
            now=lambda: moment,
            sleep=lambda seconds: None,
            heartbeat=lambda phase: None,
        )
        return supervisor

    # ---------------------------------------------- mutation matrix (A-F)

    def test_pin_a_to_pin_b_stays_pin_a(self, clock_cfg, tmp_path, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        sup = self.build(clock_cfg, tmp_path, creds)
        assert sup._probe_attempt_budget == 15.0

        creds.setenv("OANDA_DEMO_ACCOUNT_ID", self.PIN_B)
        recorder = RecordingTransport(creds, [(200, {"positions": []})])
        sup._probe()
        assert all(PIN in u for u in recorder.urls), recorder.urls
        assert not any(self.PIN_B in u for u in recorder.urls)
        assert not any(u.endswith("/v3/accounts") for u in recorder.urls)
        assert sup._probe_attempt_budget == 15.0

    def test_pin_a_to_absent_stays_pin_a(self, clock_cfg, tmp_path, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        sup = self.build(clock_cfg, tmp_path, creds)
        creds.delenv("OANDA_DEMO_ACCOUNT_ID")
        recorder = RecordingTransport(creds, [(200, {"positions": []})])
        sup._probe()
        assert all(PIN in u for u in recorder.urls)
        assert not any(u.endswith("/v3/accounts") for u in recorder.urls), (
            "a pinned composition must never regress to discovery — this was "
            "the account/budget incoherence defect"
        )
        assert sup._probe_attempt_budget == 15.0

    def test_pin_a_to_invalid_stays_pin_a(self, clock_cfg, tmp_path, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        sup = self.build(clock_cfg, tmp_path, creds)
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "now broken!!")
        recorder = RecordingTransport(creds, [(200, {"positions": []})])
        report = sup._probe()  # must not raise: the binding is already resolved
        assert report.account_flat is True
        assert all(PIN in u for u in recorder.urls)

    def test_absent_to_pin_a_stays_discovery(self, clock_cfg, tmp_path, creds) -> None:
        sup = self.build(clock_cfg, tmp_path, creds)  # composed unpinned
        assert sup._probe_attempt_budget == 25.0
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        recorder = RecordingTransport(creds, [
            (200, {"accounts": [{"id": "999-999-DISCOVERED-999"}]}),
            (200, {"positions": []}),
        ])
        sup._probe()
        assert recorder.urls[0].endswith("/v3/accounts"), (
            "an unpinned composition stays discovery-mode for its lifetime"
        )
        assert "999-999-DISCOVERED-999" in recorder.urls[1]
        assert not any(PIN in u for u in recorder.urls)
        assert sup._probe_attempt_budget == 25.0

    def test_absent_to_invalid_stays_discovery(self, clock_cfg, tmp_path, creds) -> None:
        sup = self.build(clock_cfg, tmp_path, creds)
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "broken!!")
        recorder = RecordingTransport(creds, [
            (200, {"accounts": [{"id": "999-999-DISCOVERED-999"}]}),
            (200, {"positions": []}),
        ])
        report = sup._probe()  # unrelated later env damage cannot break it
        assert report.broker_reachable is True
        assert recorder.urls[0].endswith("/v3/accounts")

    def test_pin_a_through_b_and_c_stays_pin_a(self, clock_cfg, tmp_path, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        sup = self.build(clock_cfg, tmp_path, creds)
        for later in (self.PIN_B, self.PIN_C):
            creds.setenv("OANDA_DEMO_ACCOUNT_ID", later)
            recorder = RecordingTransport(creds, [(200, {"positions": []})])
            sup._probe()
            assert all(PIN in u for u in recorder.urls), (later, recorder.urls)

    # ------------------------------------------------- restart semantics

    def test_recomposition_consumes_the_new_pin(self, clock_cfg, tmp_path, creds) -> None:
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        first = self.build(clock_cfg, tmp_path / "p1", creds)
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", self.PIN_B)
        second = self.build(clock_cfg, tmp_path / "p2", creds)
        recorder = RecordingTransport(creds, [(200, {"positions": []})])
        second._probe()
        assert all(self.PIN_B in u for u in recorder.urls), (
            "configuration changes are consumed by RECOMPOSITION, not by "
            "live probes"
        )
        recorder2 = RecordingTransport(creds, [(200, {"positions": []})])
        first._probe()
        assert all(PIN in u for u in recorder2.urls)

    def test_recomposition_absent_to_pin_picks_the_pin(
        self, clock_cfg, tmp_path, creds
    ) -> None:
        first = self.build(clock_cfg, tmp_path / "p1", creds)
        assert first._probe_attempt_budget == 25.0
        creds.setenv("OANDA_DEMO_ACCOUNT_ID", PIN)
        second = self.build(clock_cfg, tmp_path / "p2", creds)
        assert second._probe_attempt_budget == 15.0
        recorder = RecordingTransport(creds, [(200, {"positions": []})])
        second._probe()
        assert all(PIN in u for u in recorder.urls)
        assert not any(u.endswith("/v3/accounts") for u in recorder.urls)

    # ------------------------------------------------- startup fail-closed

    def test_invalid_at_composition_refuses_to_build(
        self, clock_cfg, tmp_path, creds
    ) -> None:
        """No Supervisor exists with a fallback account mode, and no broker
        request is ever made for a broken configuration."""
        # Resolved at CALL time, exactly as build_supervisor's lazy import
        # resolves it: the no-order-path acceptance test evicts and
        # re-imports the credentials module mid-suite, so a class captured at
        # collection time would be a different object than the one raised.
        from trading_firm.execution.credentials import CredentialError as LiveCredentialError

        creds.setenv("OANDA_DEMO_ACCOUNT_ID", "not-an-account")
        recorder = RecordingTransport(creds, [(200, {"positions": []})])
        with pytest.raises(LiveCredentialError):
            self.build(clock_cfg, tmp_path, creds)
        assert recorder.urls == [], "composition failure must make zero requests"
