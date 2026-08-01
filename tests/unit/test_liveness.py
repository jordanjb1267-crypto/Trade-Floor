"""Liveness signals and state diagnosis (§18 observability).

`diagnose()` is a pure function, so every state transition is exercised here
without launchd, without a real clock, and without a running process. The
filesystem tests use tmp_path only.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import pytest

from trading_firm.runner import liveness
from trading_firm.runner.liveness import (
    Heartbeat,
    LaunchdStatus,
    SecretLeakError,
    SupervisorState,
)

NOW = dt.datetime(2026, 7, 31, 6, 0, tzinfo=dt.UTC)

FAKE_TOKEN = "1" * 12 + ":" + "z" * 35
FAKE_OANDA = "a" * 32 + "-" + "b" * 32


def beat_at(moment: dt.datetime, *, pid: int = 4242, beats: int = 3) -> Heartbeat:
    return Heartbeat(
        schema_version=1,
        pid=pid,
        interpreter="/repo/.venv/bin/python",
        python_version="3.11.2",
        started_at=moment - dt.timedelta(hours=1),
        beat_at=moment,
        beats=beats,
        phase="waiting",
    )


class TestSecretGuard:
    def test_a_payload_carrying_a_token_is_refused(self) -> None:
        env = {"TELEGRAM_BOT_TOKEN": FAKE_TOKEN}
        with pytest.raises(SecretLeakError) as caught:
            liveness.assert_secret_free(f"phase=waiting token={FAKE_TOKEN}", env)
        # The error names the VARIABLE and must never quote the value: an
        # exception string reaches logs, and §0 rule 11 makes that immutable.
        assert "TELEGRAM_BOT_TOKEN" in str(caught.value)
        assert FAKE_TOKEN not in str(caught.value)

    def test_ordinary_payloads_pass(self) -> None:
        liveness.assert_secret_free("pid=1 interpreter=/x/.venv/bin/python", {})

    def test_short_values_are_not_treated_as_secrets(self) -> None:
        # A 4-character value would match half the payloads on earth; the
        # length floor exists so the guard stays meaningful rather than noisy.
        liveness.assert_secret_free("beats=3", {"TELEGRAM_CHAT_ID": "12"})

    def test_the_guard_runs_on_the_real_write_path(self, tmp_path) -> None:
        """The guard is worthless if it only exists as a helper nobody calls."""
        with pytest.raises(SecretLeakError):
            liveness.write_heartbeat(
                tmp_path,
                now=NOW,
                started_at=NOW,
                pid=1,
                interpreter=FAKE_OANDA,  # a credential smuggled into a field
                python_version="3.11.2",
                beats=0,
                phase="startup",
                env={"OANDA_DEMO_API_TOKEN": FAKE_OANDA},
            )
        assert not (tmp_path / liveness.HEARTBEAT_FILENAME).exists()


class TestStartupRecord:
    def test_startup_writes_event_and_first_heartbeat(self, tmp_path) -> None:
        payload = liveness.record_startup(
            tmp_path,
            now=NOW,
            pid=99,
            interpreter="/repo/.venv/bin/python",
            python_version="3.11.2",
            mode="loop",
            repo="/repo",
            env={},
        )
        assert payload["event"] == liveness.STARTUP_EVENT

        events = (tmp_path / liveness.EVENTS_FILENAME).read_text().splitlines()
        assert len(events) == 1
        assert json.loads(events[0])["pid"] == 99

        # The first heartbeat lands immediately, so a status check moments
        # after bootstrap does not have to wait for the first sleep slice.
        recovered = liveness.read_heartbeat(tmp_path)
        assert recovered is not None
        assert recovered.pid == 99
        assert recovered.beats == 0

    def test_events_append_rather_than_overwrite(self, tmp_path) -> None:
        for index in range(3):
            liveness.record_startup(
                tmp_path,
                now=NOW + dt.timedelta(seconds=index),
                pid=index,
                interpreter="/x",
                python_version="3.11.2",
                mode="loop",
                repo="/repo",
                env={},
            )
        assert liveness.recent_start_count(tmp_path, now=NOW + dt.timedelta(seconds=3)) == 3

    def test_startups_outside_the_window_do_not_count(self, tmp_path) -> None:
        liveness.record_startup(
            tmp_path, now=NOW, pid=1, interpreter="/x", python_version="3.11.2",
            mode="loop", repo="/repo", env={},
        )
        later = NOW + dt.timedelta(seconds=liveness.CRASH_LOOP_WINDOW_SECONDS + 60)
        assert liveness.recent_start_count(tmp_path, now=later) == 0

    def test_a_torn_line_is_ignored_not_fatal(self, tmp_path) -> None:
        path = tmp_path / liveness.EVENTS_FILENAME
        good = json.dumps({"event": liveness.STARTUP_EVENT, "at": NOW.isoformat()})
        path.write_text(good + "\n{not json\n")
        assert liveness.recent_start_count(tmp_path, now=NOW) == 1


class TestHeartbeatFile:
    def test_round_trip(self, tmp_path) -> None:
        liveness.write_heartbeat(
            tmp_path, now=NOW, started_at=NOW - dt.timedelta(minutes=5), pid=7,
            interpreter="/repo/.venv/bin/python", python_version="3.11.2",
            beats=12, phase="waiting", env={},
        )
        recovered = liveness.read_heartbeat(tmp_path)
        assert recovered is not None
        assert recovered.beats == 12
        assert recovered.interpreter == "/repo/.venv/bin/python"
        assert recovered.age_seconds(NOW + dt.timedelta(seconds=30)) == 30

    def test_missing_file_reads_as_none(self, tmp_path) -> None:
        assert liveness.read_heartbeat(tmp_path) is None

    def test_corrupt_file_reads_as_none(self, tmp_path) -> None:
        """Unreadable must degrade to 'unknown', which diagnose() calls STALE.
        Failing towards not-healthy is the §0.10 direction."""
        (tmp_path / liveness.HEARTBEAT_FILENAME).write_text("{ this is not json")
        assert liveness.read_heartbeat(tmp_path) is None

    def test_no_temporary_file_is_left_behind(self, tmp_path) -> None:
        liveness.write_heartbeat(
            tmp_path, now=NOW, started_at=NOW, pid=1, interpreter="/x",
            python_version="3.11.2", beats=1, phase="waiting", env={},
        )
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_writer_increments_beats(self, tmp_path) -> None:
        writer = liveness.HeartbeatWriter(
            tmp_path, started_at=NOW, pid=5, interpreter="/x",
            python_version="3.11.2", now=lambda: NOW,
        )
        writer("waiting")
        writer("waiting")
        recovered = liveness.read_heartbeat(tmp_path)
        assert recovered is not None and recovered.beats == 2


class TestDiagnosis:
    def test_healthy(self) -> None:
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=True, pid=1, runs=1),
            heartbeat=beat_at(NOW),
            recent_starts=1,
            now=NOW + dt.timedelta(seconds=30),
            heartbeat_pid_alive=True,
        )
        assert result.state is SupervisorState.HEALTHY
        assert result.healthy

    def test_not_loaded_is_stopped(self) -> None:
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=False), heartbeat=None,
            recent_starts=0, now=NOW,
        )
        assert result.state is SupervisorState.STOPPED

    def test_loaded_but_cleanly_exited_is_stopped(self) -> None:
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=False, last_exit_code=0),
            heartbeat=beat_at(NOW), recent_starts=1, now=NOW,
        )
        assert result.state is SupervisorState.STOPPED

    def test_never_exited_is_not_confused_with_exit_zero(self) -> None:
        """launchd prints '(never exited)' for a long-runner; parsing that as 0
        would be indistinguishable from a clean shutdown."""
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=True, last_exit_code=None),
            heartbeat=beat_at(NOW), recent_starts=1, now=NOW,
            heartbeat_pid_alive=True,
        )
        assert result.state is SupervisorState.HEALTHY

    def test_nonzero_exit_awaiting_respawn_is_crash_looping(self) -> None:
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=False, last_exit_code=1),
            heartbeat=None, recent_starts=1, now=NOW,
        )
        assert result.state is SupervisorState.CRASH_LOOPING

    def test_repeated_startups_beat_a_running_snapshot(self) -> None:
        """The case that motivated the ordering: a fast-respawning job IS
        'running' at the instant you look, and reporting that as healthy is
        exactly the failure this exists to catch."""
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=True, pid=9, runs=14),
            heartbeat=beat_at(NOW),
            recent_starts=liveness.CRASH_LOOP_MIN_STARTS,
            now=NOW,
            heartbeat_pid_alive=True,
        )
        assert result.state is SupervisorState.CRASH_LOOPING

    def test_running_without_a_heartbeat_is_stale(self) -> None:
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=True),
            heartbeat=None, recent_starts=0, now=NOW,
        )
        assert result.state is SupervisorState.STALE

    def test_old_heartbeat_is_stale(self) -> None:
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=True),
            heartbeat=beat_at(NOW), recent_starts=1,
            now=NOW + dt.timedelta(seconds=liveness.DEFAULT_MAX_BEAT_AGE_SECONDS + 1),
            heartbeat_pid_alive=True,
        )
        assert result.state is SupervisorState.STALE
        assert "loop is not turning" in result.reason

    def test_heartbeat_from_a_dead_pid_is_stale(self) -> None:
        """A leftover file from a previous process must not read as liveness."""
        result = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=True),
            heartbeat=beat_at(NOW), recent_starts=1, now=NOW,
            heartbeat_pid_alive=False,
        )
        assert result.state is SupervisorState.STALE

    def test_every_state_is_reachable(self) -> None:
        """Guards against a refactor that makes a branch unreachable — a state
        machine with a dead state silently stops reporting a real condition."""
        seen = {
            liveness.diagnose(launchd=LaunchdStatus(loaded=False), heartbeat=None,
                              recent_starts=0, now=NOW).state,
            liveness.diagnose(launchd=LaunchdStatus(loaded=True, running=True),
                              heartbeat=beat_at(NOW), recent_starts=0, now=NOW,
                              heartbeat_pid_alive=True).state,
            liveness.diagnose(launchd=LaunchdStatus(loaded=True, running=True),
                              heartbeat=None, recent_starts=0, now=NOW).state,
            liveness.diagnose(launchd=LaunchdStatus(loaded=True, running=False,
                                                    last_exit_code=2),
                              heartbeat=None, recent_starts=0, now=NOW).state,
        }
        assert seen == set(SupervisorState)


class TestPidProbe:
    def test_our_own_pid_is_alive(self) -> None:
        assert liveness.pid_alive(os.getpid())

    def test_an_absurd_pid_is_not(self) -> None:
        assert not liveness.pid_alive(2**30)


class TestDeliveryRecords:
    """Requirements 3 and 4: the success marker and the attempt ledger are
    separate files answering separate questions. The previous single marker was
    stamped on ATTEMPT, so a failed delivery was recorded as a success."""

    def test_a_failed_attempt_never_writes_the_success_marker(self, tmp_path) -> None:
        delivered, ledger = tmp_path / "d.json", tmp_path / "a.json"
        liveness.record_attempt(ledger, now=NOW, ok=False)
        assert not delivered.exists()
        assert liveness.read_delivery_marker(delivered) is None

    def test_a_confirmed_delivery_writes_the_success_marker(self, tmp_path) -> None:
        delivered = tmp_path / "d.json"
        liveness.record_delivered(delivered, now=NOW)
        assert liveness.read_delivery_marker(delivered) == NOW

    def test_the_ledger_records_both_outcomes(self, tmp_path) -> None:
        ledger = tmp_path / "a.json"
        liveness.record_attempt(ledger, now=NOW, ok=False)
        assert liveness.read_attempt_ledger(ledger).consecutive_failures == 1
        liveness.record_attempt(ledger, now=NOW, ok=False)
        assert liveness.read_attempt_ledger(ledger).consecutive_failures == 2

    def test_success_resets_the_failure_count(self, tmp_path) -> None:
        ledger = tmp_path / "a.json"
        liveness.record_attempt(ledger, now=NOW, ok=False)
        liveness.record_attempt(ledger, now=NOW, ok=True)
        assert liveness.read_attempt_ledger(ledger).consecutive_failures == 0

    def test_an_unreadable_ledger_reads_as_empty(self, tmp_path) -> None:
        ledger = tmp_path / "a.json"
        ledger.write_text("not json")
        assert liveness.read_attempt_ledger(ledger) == liveness.NotifyLedger()


class TestNotificationPlanning:
    def test_a_first_attempt_is_eligible(self) -> None:
        plan = liveness.plan_notification(
            delivered_at=None, ledger=liveness.NotifyLedger(), now=NOW
        )
        assert plan.should_send and plan.attempt_number == 1

    def test_a_confirmed_delivery_deduplicates(self) -> None:
        plan = liveness.plan_notification(
            delivered_at=NOW, ledger=liveness.NotifyLedger(last_attempt_at=NOW),
            now=NOW + dt.timedelta(minutes=10),
        )
        assert not plan.should_send
        assert "confirmed" in plan.reason

    def test_a_failure_is_retried_after_the_interval(self) -> None:
        """Requirement 5: a failed delivery stays eligible, unlike the old
        attempt-stamped marker which recorded it as done."""
        ledger = liveness.NotifyLedger(last_attempt_at=NOW, consecutive_failures=1)
        too_soon = liveness.plan_notification(
            delivered_at=None, ledger=ledger, now=NOW + dt.timedelta(seconds=60)
        )
        assert not too_soon.should_send

        due = liveness.plan_notification(
            delivered_at=None, ledger=ledger,
            now=NOW + dt.timedelta(seconds=liveness.NOTIFY_RETRY_INTERVAL_SECONDS + 1),
        )
        assert due.should_send and due.attempt_number == 2

    def test_retries_are_bounded(self) -> None:
        ledger = liveness.NotifyLedger(
            last_attempt_at=NOW, consecutive_failures=liveness.NOTIFY_MAX_ATTEMPTS
        )
        plan = liveness.plan_notification(
            delivered_at=None, ledger=ledger,
            now=NOW + dt.timedelta(seconds=liveness.NOTIFY_RETRY_INTERVAL_SECONDS + 1),
        )
        assert not plan.should_send
        assert "bounded retry spent" in plan.reason

    def test_a_lapsed_episode_resets_the_bound(self) -> None:
        """A bound that never resets is a permanent mute: one bad hour would
        kill the notification surface forever."""
        ledger = liveness.NotifyLedger(
            last_attempt_at=NOW, consecutive_failures=liveness.NOTIFY_MAX_ATTEMPTS
        )
        plan = liveness.plan_notification(
            delivered_at=None, ledger=ledger, now=NOW + dt.timedelta(hours=2)
        )
        assert plan.should_send

    def test_a_restart_loop_cannot_flood(self, tmp_path) -> None:
        """Requirement 7, now with failing deliveries. launchd respawns every
        60s; simulate an hour of that with Telegram down and assert the bound
        holds. The old in-memory design would have sent 60."""
        delivered, ledger = tmp_path / "d.json", tmp_path / "a.json"
        sends = 0
        for minute in range(60):
            moment = NOW + dt.timedelta(minutes=minute)
            plan = liveness.plan_notification(
                delivered_at=liveness.read_delivery_marker(delivered),
                ledger=liveness.read_attempt_ledger(ledger),
                now=moment,
            )
            if plan.should_send:
                sends += 1
                liveness.record_attempt(ledger, now=moment, ok=False)  # always fails
        assert sends == liveness.NOTIFY_MAX_ATTEMPTS

    def test_eventual_success_stops_the_retries(self, tmp_path) -> None:
        """Fails twice, then succeeds: the marker appears only at the success,
        and nothing is sent afterwards."""
        delivered, ledger = tmp_path / "d.json", tmp_path / "a.json"
        outcomes = {0: False, 1: False}  # attempt index -> ok
        sends, confirmed_at = 0, None
        for minute in range(60):
            moment = NOW + dt.timedelta(minutes=minute)
            plan = liveness.plan_notification(
                delivered_at=liveness.read_delivery_marker(delivered),
                ledger=liveness.read_attempt_ledger(ledger),
                now=moment,
            )
            if not plan.should_send:
                continue
            ok = outcomes.get(sends, True)
            sends += 1
            liveness.record_attempt(ledger, now=moment, ok=ok)
            if ok:
                liveness.record_delivered(delivered, now=moment)
                confirmed_at = confirmed_at or moment
        assert sends == 3, "two failures then one success, then dedup"
        assert liveness.read_delivery_marker(delivered) == confirmed_at


class TestNotifySurfaceState:
    def test_unconfirmed_until_delivery_succeeds(self) -> None:
        """Requirement 6. Reported on its own axis so a dead notifier cannot
        hide behind a healthy process."""
        assert (
            liveness.notify_surface_state(
                delivered_at=None, ledger=liveness.NotifyLedger(), now=NOW
            )
            is liveness.NotifyState.UNCONFIRMED
        )

    def test_confirmed_after_delivery(self) -> None:
        assert (
            liveness.notify_surface_state(
                delivered_at=NOW, ledger=liveness.NotifyLedger(), now=NOW
            )
            is liveness.NotifyState.CONFIRMED
        )

    def test_a_failed_attempt_does_not_confirm(self) -> None:
        state = liveness.notify_surface_state(
            delivered_at=None,
            ledger=liveness.NotifyLedger(last_attempt_at=NOW, consecutive_failures=1),
            now=NOW,
        )
        assert state is liveness.NotifyState.UNCONFIRMED

    def test_exhausted_is_distinct_from_merely_unconfirmed(self) -> None:
        state = liveness.notify_surface_state(
            delivered_at=None,
            ledger=liveness.NotifyLedger(
                last_attempt_at=NOW, consecutive_failures=liveness.NOTIFY_MAX_ATTEMPTS
            ),
            now=NOW,
        )
        assert state is liveness.NotifyState.EXHAUSTED

    def test_confirmation_goes_stale(self) -> None:
        state = liveness.notify_surface_state(
            delivered_at=NOW, ledger=liveness.NotifyLedger(), now=NOW + dt.timedelta(hours=2)
        )
        assert state is liveness.NotifyState.UNCONFIRMED


class TestNotificationOutcomeEvents:
    def test_both_outcomes_are_written_to_the_events_log(self, tmp_path) -> None:
        liveness.record_notification_attempt(
            tmp_path, now=NOW, ok=False, stage="api", status=500,
            attempt=1, detail="HTTP 500", env={},
        )
        liveness.record_notification_attempt(
            tmp_path, now=NOW, ok=True, stage="api", status=200,
            attempt=2, detail="delivered", env={},
        )
        lines = (tmp_path / liveness.EVENTS_FILENAME).read_text().splitlines()
        records = [json.loads(line) for line in lines]
        assert [r["ok"] for r in records] == [False, True]
        assert all(r["event"] == liveness.NOTIFY_EVENT for r in records)

    def test_a_leaked_token_in_the_detail_is_refused(self, tmp_path) -> None:
        with pytest.raises(SecretLeakError):
            liveness.record_notification_attempt(
                tmp_path, now=NOW, ok=False, stage="api", status=401,
                attempt=1, detail=f"401 for bot{FAKE_TOKEN}",
                env={"TELEGRAM_BOT_TOKEN": FAKE_TOKEN},
            )
        assert not (tmp_path / liveness.EVENTS_FILENAME).exists()

    def test_detail_is_bounded(self, tmp_path) -> None:
        liveness.record_notification_attempt(
            tmp_path, now=NOW, ok=False, stage="api", status=500,
            attempt=1, detail="x" * 5000, env={},
        )
        record = json.loads((tmp_path / liveness.EVENTS_FILENAME).read_text())
        assert len(record["detail"]) == liveness.DETAIL_LIMIT

    def test_notify_events_do_not_count_as_restarts(self, tmp_path) -> None:
        """The crash-loop detector counts startup events; a delivery outcome
        sharing the log must not be mistaken for one."""
        liveness.record_notification_attempt(
            tmp_path, now=NOW, ok=True, stage="api", status=200,
            attempt=1, detail="delivered", env={},
        )
        assert liveness.recent_start_count(tmp_path, now=NOW) == 0


class TestApprovedConditions:
    """The six conditions attached to the approved design. Each is pinned here
    so a later refactor has to break a named test rather than quietly erode a
    decision that was made deliberately."""

    # -- 1: process and notifier health are independent axes ------------------

    def test_notify_state_never_feeds_supervisor_diagnosis(self) -> None:
        """diagnose() takes no notification argument at all — the axes cannot
        be coupled by accident, only by an obvious signature change."""
        import inspect

        parameters = set(inspect.signature(liveness.diagnose).parameters)
        assert not {p for p in parameters if "notify" in p or "deliver" in p}

    def test_a_dead_notifier_leaves_the_process_healthy(self) -> None:
        healthy = liveness.diagnose(
            launchd=LaunchdStatus(loaded=True, running=True),
            heartbeat=beat_at(NOW), recent_starts=0, now=NOW,
            heartbeat_pid_alive=True,
        )
        exhausted = liveness.notify_surface_state(
            delivered_at=None,
            ledger=liveness.NotifyLedger(
                last_attempt_at=NOW, consecutive_failures=liveness.NOTIFY_MAX_ATTEMPTS
            ),
            now=NOW,
        )
        assert healthy.state is SupervisorState.HEALTHY
        assert exhausted is liveness.NotifyState.EXHAUSTED

    # -- 4: episode state persists across restarts ----------------------------

    def test_the_failure_count_survives_a_restart(self, tmp_path) -> None:
        """A crash loop must not get a fresh retry budget every 60 seconds.
        Each iteration here re-reads from disk, which is what a new process
        does — an in-memory counter would reset and hand out 60 more sends."""
        ledger = tmp_path / "a.json"
        for index in range(3):
            moment = NOW + dt.timedelta(minutes=index)
            liveness.record_attempt(ledger, now=moment, ok=False)
        assert liveness.read_attempt_ledger(ledger).consecutive_failures == 3

    def test_only_a_confirmed_success_resets_the_count(self, tmp_path) -> None:
        ledger = tmp_path / "a.json"
        liveness.record_attempt(ledger, now=NOW, ok=False)
        liveness.record_attempt(ledger, now=NOW + dt.timedelta(minutes=1), ok=False)
        assert liveness.read_attempt_ledger(ledger).consecutive_failures == 2
        liveness.record_attempt(ledger, now=NOW + dt.timedelta(minutes=2), ok=True)
        assert liveness.read_attempt_ledger(ledger).consecutive_failures == 0

    # -- 5: the legacy marker becomes a finite, explicit assumption -----------

    def test_migration_writes_an_assumption_not_a_delivery(self, tmp_path) -> None:
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"last_sent_at": NOW.isoformat()}))
        assumption, delivered = tmp_path / "assumed.json", tmp_path / "d.json"

        result = liveness.migrate_legacy_marker(
            legacy=legacy, assumption=assumption, log_dir=tmp_path, now=NOW, env={}
        )
        assert result == NOW
        assert liveness.read_assumed_confirmation(assumption) == NOW
        # The delivery marker must remain untouched: an assumption is not one.
        assert not delivered.exists()
        assert liveness.read_delivery_marker(delivered) is None

    def test_migration_writes_an_explicit_event(self, tmp_path) -> None:
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"last_sent_at": NOW.isoformat()}))
        liveness.migrate_legacy_marker(
            legacy=legacy, assumption=tmp_path / "assumed.json",
            log_dir=tmp_path, now=NOW, env={},
        )
        records = [
            json.loads(line)
            for line in (tmp_path / liveness.EVENTS_FILENAME).read_text().splitlines()
        ]
        assert len(records) == 1
        assert records[0]["event"] == liveness.LEGACY_ASSUMPTION_EVENT
        assert records[0]["ttl_seconds"] == liveness.LEGACY_ASSUMPTION_TTL_SECONDS
        assert "NOT a confirmed delivery" in records[0]["detail"]

    def test_migration_happens_exactly_once(self, tmp_path) -> None:
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"last_sent_at": NOW.isoformat()}))
        assumption = tmp_path / "assumed.json"
        for minute in range(5):
            liveness.migrate_legacy_marker(
                legacy=legacy, assumption=assumption, log_dir=tmp_path,
                now=NOW + dt.timedelta(minutes=minute), env={},
            )
        records = (tmp_path / liveness.EVENTS_FILENAME).read_text().splitlines()
        assert len(records) == 1, "the migration event must not repeat"

    def test_nothing_to_migrate_is_not_an_error(self, tmp_path) -> None:
        assert liveness.migrate_legacy_marker(
            legacy=tmp_path / "absent.json", assumption=tmp_path / "a.json",
            log_dir=tmp_path, now=NOW, env={},
        ) is None
        assert not (tmp_path / liveness.EVENTS_FILENAME).exists()

    def test_an_assumption_reports_as_assumed_not_confirmed(self) -> None:
        state = liveness.notify_surface_state(
            delivered_at=None, assumed_at=NOW, ledger=liveness.NotifyLedger(), now=NOW
        )
        assert state is liveness.NotifyState.ASSUMED
        assert state is not liveness.NotifyState.CONFIRMED

    def test_an_assumption_suppresses_a_duplicate_while_live(self) -> None:
        plan = liveness.plan_notification(
            delivered_at=None, assumed_at=NOW, ledger=liveness.NotifyLedger(),
            now=NOW + dt.timedelta(minutes=5),
        )
        assert not plan.should_send
        assert "legacy assumed confirmation" in plan.reason

    def test_the_assumption_expires_and_a_real_send_follows(self) -> None:
        """Finite TTL: the point is to converge on a REAL confirmation rather
        than let an inherited attempt stand in for one indefinitely."""
        later = NOW + dt.timedelta(seconds=liveness.LEGACY_ASSUMPTION_TTL_SECONDS + 1)
        plan = liveness.plan_notification(
            delivered_at=None, assumed_at=NOW, ledger=liveness.NotifyLedger(), now=later
        )
        assert plan.should_send

        assert (
            liveness.notify_surface_state(
                delivered_at=None, assumed_at=NOW, ledger=liveness.NotifyLedger(), now=later
            )
            is liveness.NotifyState.UNCONFIRMED
        )

    def test_read_delivery_marker_cannot_be_fed_a_legacy_file(self, tmp_path) -> None:
        """The old signature accepted `legacy=` and returned it as a delivery.
        That path is gone, not merely unused."""
        import inspect

        assert "legacy" not in inspect.signature(liveness.read_delivery_marker).parameters
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"last_sent_at": NOW.isoformat()}))
        assert liveness.read_delivery_marker(legacy) is None
