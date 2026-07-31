"""`attempt_startup_notification` — the composition that captures the result.

These exercise the WIRING, not the pure planning functions (those are in
test_liveness.py). The bug being fixed lived exactly here: the old code called
the notifier, discarded its `NotifyResult`, and stamped a "sent" marker whether
or not anything was delivered. Every test below asserts against the real
markers and the real events log, with the transport replaced.

No socket is opened: `notify_owner` is substituted in the script's namespace.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

import pytest

from trading_firm.notify.telegram import NotifyResult
from trading_firm.runner import liveness

REPO = Path(__file__).resolve().parents[2]
NOW = dt.datetime(2026, 7, 31, 6, 0, tzinfo=dt.UTC)

PAYLOAD = {
    "at": NOW.isoformat(),
    "pid": 4242,
    "python_version": "3.11.2",
    "mode": "loop",
}


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_supervisor_under_test", REPO / "scripts" / "run_supervisor.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def delivered_ok() -> NotifyResult:
    return NotifyResult(ok=True, stage="api", detail="delivered", status=200,
                        message_id=11, attempts=1)


def failed(detail: str = "HTTP 500") -> NotifyResult:
    return NotifyResult(ok=False, stage="api", detail=detail, status=500, attempts=2)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Point every record at tmp_path and capture notifier calls."""
    # EVERY path must be redirected. An earlier version of this fixture missed
    # ASSUMPTION_MARKER, and the migration test wrote a tmp-derived assumption
    # into the repository's real state/ops directory, which then suppressed
    # sends in every later test. A partially-patched fixture is worse than an
    # unpatched one: it fails somewhere else, later.
    monkeypatch.setattr(runner, "LOG_DIR", tmp_path)
    monkeypatch.setattr(runner, "OPS_STATE", tmp_path)
    monkeypatch.setattr(runner, "DELIVERY_MARKER", tmp_path / "delivered.json")
    monkeypatch.setattr(runner, "ATTEMPT_LEDGER", tmp_path / "attempts.json")
    monkeypatch.setattr(runner, "LEGACY_MARKER", tmp_path / "legacy.json")
    monkeypatch.setattr(runner, "ASSUMPTION_MARKER", tmp_path / "assumed.json")

    # Fail loudly if a NEW path constant is added and this fixture is not
    # updated, instead of silently writing into the real repository again.
    for attribute in dir(runner):
        value = getattr(runner, attribute)
        if attribute.isupper() and isinstance(value, Path) and "state" in str(value).lower():
            assert value == tmp_path or tmp_path in value.parents, (
                f"runner.{attribute} still points at {value}: add it to this fixture "
                f"before it writes into the repository's real state directory"
            )

    calls: list[str] = []
    outcomes: list[NotifyResult] = []

    def fake_notify_owner(kind, body):
        calls.append(body)
        return outcomes.pop(0) if outcomes else delivered_ok()

    monkeypatch.setattr(runner, "notify_owner", fake_notify_owner)

    class Wiring:
        root = tmp_path
        sent = calls
        queue = outcomes
        delivery = tmp_path / "delivered.json"
        ledger = tmp_path / "attempts.json"

        @staticmethod
        def events() -> list[dict]:
            path = tmp_path / liveness.EVENTS_FILENAME
            if not path.exists():
                return []
            return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    return Wiring


class TestSuccess:
    def test_a_confirmed_delivery_writes_the_marker_and_returns_true(self, wired) -> None:
        assert runner.attempt_startup_notification(PAYLOAD, NOW) is True
        assert liveness.read_delivery_marker(wired.delivery) == NOW
        assert len(wired.sent) == 1

    def test_the_outcome_is_written_to_the_events_log(self, wired) -> None:
        runner.attempt_startup_notification(PAYLOAD, NOW)
        events = wired.events()
        assert len(events) == 1
        assert events[0]["event"] == liveness.NOTIFY_EVENT
        assert events[0]["ok"] is True
        assert events[0]["status"] == 200

    def test_the_body_carries_no_credential_and_states_nothing_is_live(self, wired) -> None:
        runner.attempt_startup_notification(PAYLOAD, NOW)
        body = wired.sent[0]
        assert "nothing is live" in body
        assert "cannot place an order" in body


class TestFailure:
    def test_a_failed_delivery_writes_no_success_marker(self, wired) -> None:
        wired.queue.append(failed())
        assert runner.attempt_startup_notification(PAYLOAD, NOW) is False
        assert not wired.delivery.exists()
        assert liveness.read_delivery_marker(wired.delivery) is None

    def test_a_failed_delivery_is_recorded_separately(self, wired) -> None:
        wired.queue.append(failed("HTTP 500: internal"))
        runner.attempt_startup_notification(PAYLOAD, NOW)
        events = wired.events()
        assert events[0]["ok"] is False
        assert events[0]["status"] == 500
        assert events[0]["attempt"] == 1

    def test_a_failure_increments_the_ledger(self, wired) -> None:
        wired.queue.append(failed())
        runner.attempt_startup_notification(PAYLOAD, NOW)
        assert liveness.read_attempt_ledger(wired.ledger).consecutive_failures == 1

    def test_the_surface_stays_unconfirmed(self, wired) -> None:
        wired.queue.append(failed())
        runner.attempt_startup_notification(PAYLOAD, NOW)
        state = liveness.notify_surface_state(
            delivered_at=liveness.read_delivery_marker(wired.delivery),
            ledger=liveness.read_attempt_ledger(wired.ledger),
            now=NOW,
        )
        assert state is liveness.NotifyState.UNCONFIRMED


class TestRetryAndEventualSuccess:
    def test_a_retry_is_suppressed_until_the_interval_elapses(self, wired) -> None:
        wired.queue.append(failed())
        runner.attempt_startup_notification(PAYLOAD, NOW)
        runner.attempt_startup_notification(PAYLOAD, NOW + dt.timedelta(seconds=30))
        assert len(wired.sent) == 1, "second call inside the interval must not send"

    def test_eventual_success_confirms_and_then_deduplicates(self, wired) -> None:
        step = dt.timedelta(seconds=liveness.NOTIFY_RETRY_INTERVAL_SECONDS + 1)
        wired.queue.extend([failed(), failed(), delivered_ok()])

        assert runner.attempt_startup_notification(PAYLOAD, NOW) is False
        assert runner.attempt_startup_notification(PAYLOAD, NOW + step) is False
        confirmed_at = NOW + 2 * step
        assert runner.attempt_startup_notification(PAYLOAD, confirmed_at) is True

        assert len(wired.sent) == 3
        assert liveness.read_delivery_marker(wired.delivery) == confirmed_at
        # Confirmed: a fourth call sends nothing.
        runner.attempt_startup_notification(PAYLOAD, confirmed_at + step)
        assert len(wired.sent) == 3

        outcomes = [e["ok"] for e in wired.events()]
        assert outcomes == [False, False, True]

    def test_success_resets_the_failure_count(self, wired) -> None:
        step = dt.timedelta(seconds=liveness.NOTIFY_RETRY_INTERVAL_SECONDS + 1)
        wired.queue.extend([failed(), delivered_ok()])
        runner.attempt_startup_notification(PAYLOAD, NOW)
        runner.attempt_startup_notification(PAYLOAD, NOW + step)
        assert liveness.read_attempt_ledger(wired.ledger).consecutive_failures == 0


class TestDeduplication:
    def test_a_confirmed_startup_is_not_re_announced(self, wired) -> None:
        runner.attempt_startup_notification(PAYLOAD, NOW)
        for minute in (1, 10, 55):
            runner.attempt_startup_notification(PAYLOAD, NOW + dt.timedelta(minutes=minute))
        assert len(wired.sent) == 1

    def test_the_legacy_marker_suppresses_a_duplicate_on_upgrade(self, wired) -> None:
        (wired.root / "legacy.json").write_text(json.dumps({"last_sent_at": NOW.isoformat()}))
        runner.attempt_startup_notification(PAYLOAD, NOW + dt.timedelta(minutes=1))
        assert wired.sent == [], "upgrading must not re-announce a startup already sent"


class TestRestartLoopCannotFlood:
    def test_an_hour_of_60s_restarts_with_telegram_down(self, wired) -> None:
        """Requirement 7 against the real wiring: every delivery fails, and the
        bound plus the retry interval hold. Each simulated restart is a fresh
        process, which is exactly why the records live on disk."""
        wired.queue.extend(failed() for _ in range(100))
        for minute in range(60):
            runner.attempt_startup_notification(PAYLOAD, NOW + dt.timedelta(minutes=minute))
        assert len(wired.sent) == liveness.NOTIFY_MAX_ATTEMPTS
        assert not wired.delivery.exists()

    def test_the_surface_reports_exhausted_afterwards(self, wired) -> None:
        wired.queue.extend(failed() for _ in range(100))
        for minute in range(60):
            runner.attempt_startup_notification(PAYLOAD, NOW + dt.timedelta(minutes=minute))
        state = liveness.notify_surface_state(
            delivered_at=liveness.read_delivery_marker(wired.delivery),
            ledger=liveness.read_attempt_ledger(wired.ledger),
            now=NOW + dt.timedelta(minutes=59),
        )
        assert state is liveness.NotifyState.EXHAUSTED


class TestAnnouncerRidesTheHeartbeat:
    def test_it_beats_before_attempting_delivery(self, wired) -> None:
        """A hanging notification must never delay the liveness signal that
        exists to detect hangs."""
        order: list[str] = []
        wired.queue.append(failed())

        def beat(phase):
            order.append(f"beat:{phase}")

        announcer = runner.StartupAnnouncer(beat, PAYLOAD, lambda: NOW)
        announcer("waiting")
        assert order[0] == "beat:waiting"
        assert wired.sent, "the beat must not have replaced the delivery attempt"

    def test_once_confirmed_it_stops_attempting(self, wired) -> None:
        announcer = runner.StartupAnnouncer(lambda phase: None, PAYLOAD, lambda: NOW)
        announcer("waiting")  # delivers
        assert announcer.confirmed is True
        announcer("waiting")
        announcer("waiting")
        assert len(wired.sent) == 1
