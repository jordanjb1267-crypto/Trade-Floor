"""Notifier readiness confirmation refreshes on every successful delivery.

The defect, observed on the 2026-08-03 shadow session: the supervisor ran for
days, delivered both session messages to the owner's phone, and still reported
`notify: unconfirmed` with `--require-notify-confirmed` exiting 6. Readiness
was derived from the STARTUP delivery marker, which is written once and never
refreshed, so it aged past its one-hour TTL and stayed there while the notifier
was demonstrably working.

The fix routes every approved owner notification through one `deliver()`
function that refreshes a canonical readiness marker on a confirmed delivery,
and only on a confirmed delivery. These tests pin both halves: that success
refreshes, and that nothing else does.

No socket is opened — `notify_owner` is substituted in the script's namespace.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from trading_firm.notify.surface import NotificationKind
from trading_firm.notify.telegram import NotifyResult
from trading_firm.runner import liveness

REPO = Path(__file__).resolve().parents[2]
NOW = dt.datetime(2026, 8, 3, 6, 0, tzinfo=dt.UTC)

PAYLOAD = {"at": NOW.isoformat(), "pid": 4242, "python_version": "3.11.2", "mode": "loop"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load("run_supervisor_confirm", REPO / "scripts" / "run_supervisor.py")
status = _load("supervisor_status_confirm", REPO / "scripts" / "supervisor_status.py")


def ok_result() -> NotifyResult:
    return NotifyResult(ok=True, stage="api", detail="delivered", status=200, attempts=1)


def failed_result(status_code: int | None = 500) -> NotifyResult:
    return NotifyResult(ok=False, stage="api", detail="boom", status=status_code, attempts=2)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Redirect every marker path in BOTH scripts to tmp_path."""
    for module in (runner, status):
        for attribute in dir(module):
            value = getattr(module, attribute)
            if attribute.isupper() and isinstance(value, Path) and "state" in str(value).lower():
                monkeypatch.setattr(module, attribute, tmp_path / f"{attribute.lower()}.json")
    monkeypatch.setattr(runner, "LOG_DIR", tmp_path)
    monkeypatch.setattr(status, "LOG_DIR", tmp_path)
    # Both scripts must agree on which file is canonical, or the fix is a
    # no-op in production while passing here.
    confirmation = tmp_path / "confirmation_marker.json"
    monkeypatch.setattr(runner, "CONFIRMATION_MARKER", confirmation)
    monkeypatch.setattr(status, "CONFIRMATION_MARKER", confirmation)

    outcomes: list[NotifyResult] = []
    sent: list[tuple[NotificationKind, str]] = []

    def fake_notify_owner(kind, body):
        sent.append((kind, body))
        return outcomes.pop(0) if outcomes else ok_result()

    monkeypatch.setattr(runner, "notify_owner", fake_notify_owner)

    class Wiring:
        root = tmp_path
        confirmation_marker = confirmation
        startup_marker = tmp_path / "delivery_marker.json"
        queue = outcomes
        messages = sent

        @staticmethod
        def confirmed_at():
            return liveness.read_delivery_marker(confirmation)

    return Wiring


class TestEverySuccessfulDeliveryRefreshesConfirmation:
    def test_startup_delivery_creates_confirmation(self, wired) -> None:
        runner.attempt_startup_notification(PAYLOAD, NOW)
        assert wired.confirmed_at() == NOW

    def test_session_start_delivery_refreshes_confirmation(self, wired) -> None:
        later = NOW + dt.timedelta(hours=5)
        runner.attempt_startup_notification(PAYLOAD, NOW)
        assert runner.deliver(NotificationKind.SESSION_START_HEALTH, "session starting", later).ok
        assert wired.confirmed_at() == later, "a session-start delivery must refresh readiness"

    def test_daily_report_delivery_refreshes_confirmation(self, wired) -> None:
        later = NOW + dt.timedelta(hours=9)
        runner.deliver(NotificationKind.DAILY_SESSION_REPORT, "session complete", later)
        assert wired.confirmed_at() == later

    def test_the_injected_supervisor_callable_uses_the_same_path(self, wired) -> None:
        """`notify` is what Supervisor actually calls; if it bypassed deliver()
        the session path would still not refresh anything."""
        assert runner.notify(NotificationKind.DAILY_SESSION_REPORT, "done") is True
        assert wired.confirmed_at() is not None

    def test_every_notification_kind_refreshes(self, wired) -> None:
        for index, kind in enumerate(NotificationKind):
            moment = NOW + dt.timedelta(minutes=index)
            runner.deliver(kind, "body", moment)
            assert wired.confirmed_at() == moment, f"{kind} did not refresh confirmation"


class TestConfirmationIsNotWrittenWithoutRealDelivery:
    def test_a_failed_delivery_does_not_refresh(self, wired) -> None:
        wired.queue.append(failed_result())
        runner.deliver(NotificationKind.DAILY_SESSION_REPORT, "body", NOW)
        assert wired.confirmed_at() is None

    def test_a_non_success_status_does_not_refresh(self, wired) -> None:
        for code in (400, 401, 403, 429, 500):
            wired.queue.append(failed_result(code))
            runner.deliver(NotificationKind.RISK_HALT, "halt", NOW)
        assert wired.confirmed_at() is None

    def test_a_failure_after_a_success_leaves_the_older_confirmation(self, wired) -> None:
        """A later failure must not erase evidence, and must not advance it."""
        runner.deliver(NotificationKind.SESSION_START_HEALTH, "ok", NOW)
        wired.queue.append(failed_result())
        runner.deliver(NotificationKind.DAILY_SESSION_REPORT, "x", NOW + dt.timedelta(hours=2))
        assert wired.confirmed_at() == NOW

    def test_a_skipped_startup_send_does_not_refresh(self, wired) -> None:
        """plan_notification suppressing a duplicate is not a delivery."""
        runner.attempt_startup_notification(PAYLOAD, NOW)
        before = wired.confirmed_at()
        soon = NOW + dt.timedelta(minutes=1)
        assert runner.attempt_startup_notification(PAYLOAD, soon) is False
        assert wired.confirmed_at() == before, "a suppressed send must not refresh"

    def test_a_preflight_failure_does_not_refresh(self, wired) -> None:
        """A disabled/misconfigured notifier fails at preflight, before any I/O."""
        wired.queue.append(
            NotifyResult(ok=False, stage="preflight", detail="TOKEN not set", attempts=0)
        )
        runner.deliver(NotificationKind.SESSION_START_HEALTH, "body", NOW)
        assert wired.confirmed_at() is None

    def test_only_one_place_in_the_process_writes_confirmation(self) -> None:
        """Requirement: one shared path. A second writer would let a caller
        record confirmation without having delivered anything."""
        source = (REPO / "scripts" / "run_supervisor.py").read_text()
        assert source.count("record_delivered(CONFIRMATION_MARKER") == 1

    def test_notify_owner_is_never_called_outside_deliver(self) -> None:
        source = (REPO / "scripts" / "run_supervisor.py").read_text()
        assert source.count("notify_owner(") == 1, (
            "every send must route through deliver(); a direct notify_owner call "
            "would deliver without refreshing readiness"
        )


class TestTtlBehaviourPreserved:
    def test_confirmation_is_not_permanent(self, wired) -> None:
        runner.deliver(NotificationKind.SESSION_START_HEALTH, "body", NOW)
        expired = NOW + dt.timedelta(seconds=liveness.DELIVERY_CONFIRMED_TTL_SECONDS + 1)
        state = liveness.notify_surface_state(
            delivered_at=wired.confirmed_at(), ledger=liveness.NotifyLedger(), now=expired
        )
        assert state is liveness.NotifyState.UNCONFIRMED

    def test_a_newer_delivery_restores_readiness(self, wired) -> None:
        runner.deliver(NotificationKind.SESSION_START_HEALTH, "body", NOW)
        expired = NOW + dt.timedelta(seconds=liveness.DELIVERY_CONFIRMED_TTL_SECONDS + 1)
        runner.deliver(NotificationKind.DAILY_SESSION_REPORT, "body", expired)
        state = liveness.notify_surface_state(
            delivered_at=wired.confirmed_at(), ledger=liveness.NotifyLedger(), now=expired
        )
        assert state is liveness.NotifyState.CONFIRMED

    def test_the_ttl_constant_is_unchanged(self) -> None:
        assert liveness.DELIVERY_CONFIRMED_TTL_SECONDS == 3600.0

    def test_an_assumption_still_cannot_satisfy_the_gate(self) -> None:
        """The gate is not weakened: ASSUMED remains distinct from CONFIRMED."""
        state = liveness.notify_surface_state(
            delivered_at=None, assumed_at=NOW, ledger=liveness.NotifyLedger(), now=NOW
        )
        assert state is liveness.NotifyState.ASSUMED
        assert status.EXIT_BY_STATE.get(liveness.SupervisorState.HEALTHY) == 0


class TestStartupAnnouncerSemanticsPreserved:
    def test_startup_dedup_still_uses_its_own_marker(self, wired) -> None:
        """A session delivery must NOT dedup away the startup announcement —
        otherwise a restart would go unannounced because a session message
        happened to be delivered shortly before it."""
        runner.deliver(NotificationKind.DAILY_SESSION_REPORT, "session done", NOW)
        wired.messages.clear()
        assert runner.attempt_startup_notification(PAYLOAD, NOW + dt.timedelta(minutes=1)) is True
        kinds = [kind for kind, _ in wired.messages]
        assert NotificationKind.SUPERVISOR_STARTUP_HEALTH in kinds

    def test_the_startup_marker_is_still_written_on_startup_success(self, wired) -> None:
        runner.attempt_startup_notification(PAYLOAD, NOW)
        assert liveness.read_delivery_marker(runner.DELIVERY_MARKER) == NOW

    def test_the_announcer_stops_once_confirmed(self, wired) -> None:
        announcer = runner.StartupAnnouncer(lambda phase: None, PAYLOAD, lambda: NOW)
        announcer("waiting")
        assert announcer.confirmed is True
        announcer("waiting")
        assert len(wired.messages) == 1


class TestRegressionExactFailure:
    """The 2026-08-03 failure, reproduced and then shown fixed."""

    def _healthy_launchd(self, monkeypatch):
        monkeypatch.setattr(
            status, "read_launchd",
            lambda label: liveness.LaunchdStatus(loaded=True, running=True, pid=1, runs=1),
        )

    def test_stale_startup_confirmation_alone_fails_the_gate(self, wired, monkeypatch) -> None:
        self._healthy_launchd(monkeypatch)
        long_ago = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
        liveness.record_startup(
            wired.root, now=dt.datetime.now(dt.UTC), pid=1, interpreter="/x",
            python_version="3.11.2", mode="loop", repo="/r", env={},
        )
        # Startup confirmed two days ago; nothing since.
        liveness.record_delivered(wired.confirmation_marker, now=long_ago)
        assert status.main(["--require-notify-confirmed"]) == 6

    def test_a_current_session_delivery_restores_exit_zero(self, wired, monkeypatch) -> None:
        """The exact fix: startup confirmation older than an hour, then a
        session message delivered successfully → the gate passes."""
        self._healthy_launchd(monkeypatch)
        now = dt.datetime.now(dt.UTC)
        liveness.record_startup(
            wired.root, now=now, pid=1, interpreter="/x", python_version="3.11.2",
            mode="loop", repo="/r", env={},
        )
        liveness.record_delivered(wired.confirmation_marker, now=now - dt.timedelta(days=2))
        assert status.main(["--require-notify-confirmed"]) == 6

        # A session-start notification is delivered now, through the real path.
        assert runner.notify(NotificationKind.SESSION_START_HEALTH, "session starting") is True

        assert status.main(["--require-notify-confirmed"]) == 0, (
            "a successful current delivery must restore readiness"
        )

    def test_a_failed_session_delivery_leaves_the_gate_closed(self, wired, monkeypatch) -> None:
        self._healthy_launchd(monkeypatch)
        now = dt.datetime.now(dt.UTC)
        liveness.record_startup(
            wired.root, now=now, pid=1, interpreter="/x", python_version="3.11.2",
            mode="loop", repo="/r", env={},
        )
        liveness.record_delivered(wired.confirmation_marker, now=now - dt.timedelta(days=2))
        wired.queue.append(failed_result())
        assert runner.notify(NotificationKind.SESSION_START_HEALTH, "starting") is False
        assert status.main(["--require-notify-confirmed"]) == 6


class TestNoTradingBehaviourChanged:
    def test_the_supervisor_module_is_untouched_by_this_fix(self) -> None:
        """The trading loop still receives a plain bool-returning callable and
        knows nothing about delivery evidence."""
        source = (REPO / "src" / "trading_firm" / "runner" / "supervisor.py").read_text()
        for token in ("CONFIRMATION_MARKER", "record_delivered", "notify_owner", "deliver("):
            assert token not in source

    def test_no_broker_order_risk_or_database_import_was_added(self) -> None:
        import ast

        source = (REPO / "scripts" / "run_supervisor.py").read_text()
        top_level = set()
        for node in ast.parse(source).body:
            if isinstance(node, ast.ImportFrom) and node.module:
                top_level.add(node.module)
            elif isinstance(node, ast.Import):
                top_level |= {a.name for a in node.names}
        forbidden = {
            m for m in top_level
            if m.startswith(("trading_firm.execution", "trading_firm.risk",
                             "trading_firm.sizing", "trading_firm.audit",
                             "trading_firm.surveillance", "trading_firm.strategies"))
        }
        assert not forbidden, f"new runtime coupling introduced: {sorted(forbidden)}"

    def test_deliver_touches_no_database(self, wired) -> None:
        runner.deliver(NotificationKind.DAILY_SESSION_REPORT, "body", NOW)
        assert not list(wired.root.glob("*.sqlite*"))

    def test_the_confirmation_marker_holds_only_a_timestamp(self, wired) -> None:
        """No credential, no message body, no account identifier."""
        runner.deliver(NotificationKind.SESSION_START_HEALTH, "sensitive body text", NOW)
        raw = json.loads(wired.confirmation_marker.read_text())
        assert set(raw) == {"delivered_at"}
        assert "sensitive" not in wired.confirmation_marker.read_text()
