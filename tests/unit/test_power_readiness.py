"""Power readiness and suspension detection (§31.5, amendment A-4).

The 2026-08-05/06 incidents were caused by clamshell sleep that `caffeinate -i`
never prevented, and nothing in the runtime noticed. These tests pin both
halves of the correction: what macOS can prove before a session, and how the
runtime detects that it was frozen during one.

`pmset` is never invoked — every parser is fed captured output, and the
suspension detector takes injected clocks, so nothing here sleeps or shells out.
"""

from __future__ import annotations

import datetime as dt
import subprocess

from trading_firm.runner import power as power_module
from trading_firm.runner.power import (
    RECENT_SLEEP_WINDOW_SECONDS,
    SUSPENSION_THRESHOLD_SECONDS,
    PowerSource,
    PowerState,
    SuspensionDetector,
    count_recent_sleep_events,
    parse_assertions,
    parse_power_source,
    read_power_state,
)

# Captured from the incident machine.
PS_AC = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1234)\t100%; charged"
PS_BATTERY = "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1234)\t52%; discharging"

ASSERTIONS_IDLE_ONLY = """Assertion status system-wide:
   BackgroundTask                 0
   PreventUserIdleSystemSleep     1
   PreventSystemSleep             0
   ExternalMedia                  0
"""
ASSERTIONS_BOTH = """Assertion status system-wide:
   BackgroundTask                 0
   PreventUserIdleSystemSleep     1
   PreventSystemSleep             1
"""

# The actual log line that explains both incidents.
SLEEP_LOG = """2026-08-04 23:50:18 -0500 Sleep  Entering Sleep state due to 'Clamshell Sleep': ...
2026-08-05 00:20:27 -0500 DarkWake  DarkWake from Deep Idle [CDNPB] : due to EC.RTC/Maintenance
2026-08-05 00:27:18 -0500 Sleep  Entering Sleep state due to 'Maintenance Sleep': ...
"""


class TestParsers:
    def test_ac_power_is_recognised(self) -> None:
        assert parse_power_source(PS_AC) is PowerSource.AC

    def test_battery_is_recognised(self) -> None:
        assert parse_power_source(PS_BATTERY) is PowerSource.BATTERY

    def test_unreadable_output_is_unknown_not_ac(self) -> None:
        """Fail closed: an unparseable probe must never read as ready."""
        assert parse_power_source("") is PowerSource.UNKNOWN
        assert parse_power_source("garbage") is PowerSource.UNKNOWN

    def test_caffeinate_i_alone_shows_no_system_assertion(self) -> None:
        """The exact pre-fix state of the incident machine."""
        system, idle = parse_assertions(ASSERTIONS_IDLE_ONLY)
        assert idle is True
        assert system is False

    def test_caffeinate_si_shows_both(self) -> None:
        system, idle = parse_assertions(ASSERTIONS_BOTH)
        assert system is True and idle is True

    def test_sleep_events_are_counted(self) -> None:
        # Anchored just after the fixture's second sleep entry: both fall
        # inside the hour and both count. The count is TIME-scoped now, so
        # the observation instant is explicit rather than implied.
        now = dt.datetime(2026, 8, 5, 0, 30, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
        assert count_recent_sleep_events(SLEEP_LOG, now=now) == 2

    def test_no_sleep_log_counts_zero(self) -> None:
        assert count_recent_sleep_events("") == 0


CDT = dt.timezone(dt.timedelta(hours=-5))
NOW = dt.datetime(2026, 8, 12, 7, 0, 0, tzinfo=CDT)


def sleep_line(instant: dt.datetime, cause: str = "Clamshell Sleep") -> str:
    return (
        f"{instant:%Y-%m-%d %H:%M:%S %z}"[:19]
        + f" {instant:%z} Sleep  Entering Sleep state due to '{cause}': ..."
    )


def dense_lines(start: dt.datetime, count: int, step_seconds: float = 6.0) -> list[str]:
    return [
        f"{start + dt.timedelta(seconds=step_seconds * i):%Y-%m-%d %H:%M:%S} "
        f"{start:%z} Assertions  PID 4242(powerd) Created MPlayAudio ..."
        for i in range(count)
    ]


class TestRecentSleepTimeWindow:
    """The window is TIME, not line position (final-rereview blocker).

    The defeated defect: `count_recent_sleep_events` read only the final 400
    log lines, so a sleep 45 minutes old vanished behind denser logging and
    power readiness — by then qualification-authoritative — falsely PASSed.
    Every case here is expressed against an injected `now`, because the
    property under test is an interval, not a file position.
    """

    def ago(self, **kw) -> dt.datetime:
        return NOW - dt.timedelta(**kw)

    def test_no_sleep_entries_counts_zero(self) -> None:
        assert count_recent_sleep_events("\n".join(dense_lines(self.ago(minutes=50), 50)),
                                         now=NOW) == 0

    def test_sleep_thirty_minutes_ago_is_detected(self) -> None:
        assert count_recent_sleep_events(sleep_line(self.ago(minutes=30)), now=NOW) == 1

    def test_sleep_just_inside_the_window_is_detected(self) -> None:
        log = sleep_line(self.ago(minutes=59, seconds=59))
        assert count_recent_sleep_events(log, now=NOW) == 1

    def test_sleep_exactly_at_the_cutoff_counts(self) -> None:
        """Boundary INCLUSIVE: 'within this window' keeps its edge, and the
        edge case fails closed rather than open."""
        assert count_recent_sleep_events(sleep_line(self.ago(hours=1)), now=NOW) == 1

    def test_sleep_just_older_than_the_cutoff_does_not_count(self) -> None:
        log = sleep_line(self.ago(hours=1, seconds=1))
        assert count_recent_sleep_events(log, now=NOW) == 0

    def test_sleep_two_hours_ago_does_not_count(self) -> None:
        assert count_recent_sleep_events(sleep_line(self.ago(hours=2)), now=NOW) == 0

    def test_one_recent_among_old_sleeps_is_detected(self) -> None:
        log = "\n".join([
            sleep_line(self.ago(hours=9)),
            sleep_line(self.ago(hours=5)),
            sleep_line(self.ago(minutes=20)),
        ])
        assert count_recent_sleep_events(log, now=NOW) == 1

    def test_all_old_sleeps_count_zero(self) -> None:
        log = "\n".join(sleep_line(self.ago(hours=h)) for h in (2, 5, 9))
        assert count_recent_sleep_events(log, now=NOW) == 0

    def test_the_reproduced_defect_400_dense_lines_cannot_hide_a_sleep(self) -> None:
        """THE blocking reproduction: sleep 45 minutes ago, then 400 newer
        in-hour lines. The old line-bounded parser returned 0 here."""
        log = "\n".join([
            sleep_line(self.ago(minutes=45)),
            *dense_lines(self.ago(minutes=40), 400),
        ])
        assert count_recent_sleep_events(log, now=NOW) == 1

    def test_a_thousand_newer_lines_cannot_hide_a_sleep_either(self) -> None:
        log = "\n".join([
            sleep_line(self.ago(minutes=45)),
            *dense_lines(self.ago(minutes=40), 1000, step_seconds=2.0),
        ])
        assert count_recent_sleep_events(log, now=NOW) == 1

    def test_a_recognized_sleep_with_a_malformed_timestamp_fails_closed(self) -> None:
        """A sleep we cannot place in time cannot be proven old."""
        log = "not-a-timestamp Sleep  Entering Sleep state due to 'Clamshell Sleep'"
        assert count_recent_sleep_events(log, now=NOW) == 1

    def test_a_wrapped_or_offsetless_sleep_line_fails_closed(self) -> None:
        # Continuation-style line: signature present, no leading stamp.
        wrapped = "        Entering Sleep state due to 'Maintenance Sleep': ..."
        assert count_recent_sleep_events(wrapped, now=NOW) == 1
        # Timestamp shape without the UTC offset the platform provides:
        # ambiguous local time, refused rather than guessed.
        offsetless = "2026-08-12 06:15:00 Sleep  Entering Sleep state due to 'x'"
        assert count_recent_sleep_events(offsetless, now=NOW) == 1
        # Shape matches but the instant is impossible: still fail closed.
        impossible = "2026-13-45 99:99:99 -0500 Sleep  Entering Sleep state due to 'x'"
        assert count_recent_sleep_events(impossible, now=NOW) == 1

    def test_unrelated_garbage_lines_disqualify_nothing(self) -> None:
        log = "\n".join([
            "\x00 utter garbage with no signature",
            "2026-08-12 06:59:00 -0500 Wake  DarkWake from Deep Idle ...",
            sleep_line(self.ago(hours=3)),
        ])
        assert count_recent_sleep_events(log, now=NOW) == 0

    def test_the_real_fixture_format_parses(self) -> None:
        """The captured incident log (offset-carrying stamps) still parses:
        anchored inside its own window both entries count, anchored a day
        later neither does."""
        inside = dt.datetime(2026, 8, 5, 0, 30, 0, tzinfo=CDT)
        assert count_recent_sleep_events(SLEEP_LOG, now=inside) == 2
        later = dt.datetime(2026, 8, 6, 0, 30, 0, tzinfo=CDT)
        assert count_recent_sleep_events(SLEEP_LOG, now=later) == 0

    def test_read_power_state_threads_the_injected_clock(self) -> None:
        log = sleep_line(self.ago(minutes=45))
        state = read_power_state(recent_sleep_lines=log, now=NOW)
        assert state.recent_sleep_events == 1
        old = read_power_state(recent_sleep_lines=sleep_line(self.ago(hours=3)), now=NOW)
        assert old.recent_sleep_events == 0


class _Completed:
    """The two fields of subprocess.run's result that _pmset reads."""

    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


LOG_QUIET = "2026-08-12 06:05:00 -0500 Wake  DarkWake from Deep Idle [CDNPB] ...\n"


class TestChannelVerification:
    """Command failure is never an empty answer (final-rereview blocker).

    The defeated defect: `_pmset` collapsed timeout, non-zero exit, and
    OSError to "" — and for `pmset -g log` alone, "" is a PASSING value
    (zero recent sleeps). "Unable to establish sleep history" was
    observationally identical to "history queried, no recent sleep", so a
    dead log command let readiness pass on evidence never obtained. These
    drive the REAL subprocess wrapper with subprocess.run substituted at
    the command boundary — the only seam a channel-failure test may use.
    """

    def probe(self, monkeypatch, *, ps=None, assertions=None, log=None) -> PowerState:
        behaviors = {
            ("-g", "ps"): ps if ps is not None else _Completed(PS_AC),
            ("-g", "assertions"):
                assertions if assertions is not None else _Completed(ASSERTIONS_BOTH),
            ("-g", "log"): log if log is not None else _Completed(LOG_QUIET),
        }

        def fake_run(cmd, **kwargs):
            behavior = behaviors[tuple(cmd[1:])]
            if isinstance(behavior, BaseException):
                raise behavior
            return behavior

        monkeypatch.setattr(power_module.subprocess, "run", fake_run)
        return read_power_state(now=NOW)

    # ------------------------------------------------------------- log channel

    def test_log_success_with_empty_output_is_verified(self, monkeypatch) -> None:
        """Case A: the command RAN and answered 'nothing'. That is evidence."""
        state = self.probe(monkeypatch, log=_Completed(""))
        assert state.sleep_history_verified is True
        assert state.recent_sleep_events == 0
        assert state.ready is True

    def test_log_success_with_quiet_output_is_verified(self, monkeypatch) -> None:
        state = self.probe(monkeypatch)
        assert state.sleep_history_verified is True
        assert state.recent_sleep_events == 0
        assert state.ready is True

    def test_log_success_with_recent_sleep_fails_readiness(self, monkeypatch) -> None:
        recent = sleep_line(NOW - dt.timedelta(minutes=30))
        state = self.probe(monkeypatch, log=_Completed(LOG_QUIET + recent + "\n"))
        assert state.sleep_history_verified is True
        assert state.recent_sleep_events == 1
        assert state.ready is False

    def test_log_timeout_is_unverified_not_quiet(self, monkeypatch) -> None:
        state = self.probe(monkeypatch, log=subprocess.TimeoutExpired("pmset", 20))
        assert state.sleep_history_verified is False
        assert state.ready is False
        assert any("sleep history could not be verified" in r for r in state.reasons())

    def test_log_nonzero_exit_is_unverified(self, monkeypatch) -> None:
        state = self.probe(monkeypatch, log=_Completed("some error text", returncode=1))
        assert state.sleep_history_verified is False
        assert state.ready is False

    def test_log_missing_command_is_unverified(self, monkeypatch) -> None:
        state = self.probe(monkeypatch, log=FileNotFoundError("pmset"))
        assert state.sleep_history_verified is False
        assert state.ready is False

    def test_log_permission_error_is_unverified(self, monkeypatch) -> None:
        state = self.probe(monkeypatch, log=PermissionError("pmset"))
        assert state.sleep_history_verified is False
        assert state.ready is False

    def test_log_unusable_output_is_unverified(self, monkeypatch) -> None:
        """Non-empty output with no pmset timestamp anywhere is not a log we
        can read history from — success at the process level is not success
        at the evidence level."""
        state = self.probe(monkeypatch, log=_Completed("utter garbage\nno stamps here\n"))
        assert state.sleep_history_verified is False
        assert state.ready is False

    def test_recognized_sleep_with_malformed_stamp_fails_through_the_wrapper(
        self, monkeypatch
    ) -> None:
        """The per-line rule survives the channel change: a usable log whose
        SLEEP line cannot be placed in time still counts it (fail closed)."""
        log = LOG_QUIET + "not-a-stamp Sleep  Entering Sleep state due to 'x'\n"
        state = self.probe(monkeypatch, log=_Completed(log))
        assert state.sleep_history_verified is True
        assert state.recent_sleep_events == 1
        assert state.ready is False

    # ------------------------------------------------------ ps / assertions

    def test_ps_failure_blocks_readiness_as_unverified(self, monkeypatch) -> None:
        state = self.probe(monkeypatch, ps=subprocess.TimeoutExpired("pmset", 20))
        assert state.source is PowerSource.UNKNOWN
        assert state.ready is False
        assert any("could not be verified" in r for r in state.reasons())

    def test_ps_success_verifies_ac(self, monkeypatch) -> None:
        assert self.probe(monkeypatch).source is PowerSource.AC

    def test_assertions_failure_blocks_readiness(self, monkeypatch) -> None:
        state = self.probe(monkeypatch, assertions=FileNotFoundError("pmset"))
        assert state.prevent_system_sleep is False
        assert state.prevent_idle_sleep is False
        assert state.ready is False

    def test_assertions_success_verifies_both(self, monkeypatch) -> None:
        state = self.probe(monkeypatch)
        assert state.prevent_system_sleep is True
        assert state.prevent_idle_sleep is True

    # ------------------------------------------------------------- combined

    def test_selective_log_failure_cannot_pass(self, monkeypatch) -> None:
        """THE decisive regression: both other channels healthy, log dead.
        This exact state passed readiness before this fix."""
        state = self.probe(monkeypatch, log=subprocess.TimeoutExpired("pmset", 20))
        assert state.source is PowerSource.AC
        assert state.prevent_system_sleep and state.prevent_idle_sleep
        assert state.ready is False

    def test_successful_empty_log_remains_distinguishable_and_may_pass(
        self, monkeypatch
    ) -> None:
        """The mirror: empty SUCCESS still passes, proving failure and empty
        no longer share a representation."""
        assert self.probe(monkeypatch, log=_Completed("")).ready is True


class TestReadiness:
    def _state(self, **kw) -> PowerState:
        base = dict(
            source=PowerSource.AC,
            prevent_system_sleep=True,
            prevent_idle_sleep=True,
            recent_sleep_events=0,
            sleep_history_verified=True,
        )
        base.update(kw)
        return PowerState(**base)

    def test_a_fully_provisioned_machine_is_ready(self) -> None:
        assert self._state().ready
        assert self._state().reasons() == ()

    def test_battery_is_not_ready(self) -> None:
        state = self._state(source=PowerSource.BATTERY)
        assert not state.ready
        assert any("AC power" in r for r in state.reasons())

    def test_the_incident_configuration_is_not_ready(self) -> None:
        """caffeinate -i only, and the machine has been sleeping — exactly
        2026-08-05. Pre-startup must refuse to call this qualifying."""
        state = self._state(prevent_system_sleep=False, recent_sleep_events=17)
        assert not state.ready
        reasons = " ".join(state.reasons())
        assert "PreventSystemSleep" in reasons
        assert "lid closed?" in reasons

    def test_recent_sleep_alone_blocks_readiness(self) -> None:
        """Assertions can be held and the machine can still be sleeping — the
        assertion is a request, not a guarantee. Observed behaviour wins."""
        assert not self._state(recent_sleep_events=1).ready

    def test_lid_state_is_never_claimed(self) -> None:
        """§31.5: macOS does not reliably expose it, so the gate must not
        pretend to check it."""
        assert not hasattr(PowerState, "lid_open")
        assert "lid" not in " ".join(PowerState.__annotations__)


class TestSuspensionDetector:
    def test_normal_progress_is_not_a_suspension(self) -> None:
        wall = iter([1000.0, 1300.0, 1600.0])
        mono = iter([0.0, 300.0, 600.0])
        detector = SuspensionDetector(wall=lambda: next(wall), monotonic=lambda: next(mono))
        assert detector.sample() is None
        assert detector.sample() is None
        assert not detector.detected

    def test_a_sleep_gap_is_detected(self) -> None:
        """Wall clock advanced 45 minutes; monotonic advanced 300 s. The
        difference is the suspension — this is how the runtime learns it was
        frozen, without needing the OS to cooperate."""
        wall = iter([1000.0, 1000.0 + 2700.0])
        mono = iter([0.0, 300.0])
        detector = SuspensionDetector(wall=lambda: next(wall), monotonic=lambda: next(mono))
        event = detector.sample()
        assert event is not None
        assert event.suspended_seconds == 2400.0
        assert detector.detected
        assert detector.total_suspended_seconds == 2400.0

    def test_small_clock_drift_is_ignored(self) -> None:
        """An NTP correction must not disqualify a session."""
        wall = iter([1000.0, 1000.0 + 305.0])
        mono = iter([0.0, 300.0])
        detector = SuspensionDetector(wall=lambda: next(wall), monotonic=lambda: next(mono))
        assert detector.sample() is None

    def test_the_threshold_is_below_the_shortest_observed_darkwake(self) -> None:
        """Real DarkWake cycles ran ~45 s; the threshold must catch them."""
        assert SUSPENSION_THRESHOLD_SECONDS < 45

    def test_repeated_gaps_accumulate(self) -> None:
        wall = iter([0.0, 1000.0, 2000.0])
        mono = iter([0.0, 100.0, 200.0])
        detector = SuspensionDetector(wall=lambda: next(wall), monotonic=lambda: next(mono))
        detector.sample()
        detector.sample()
        assert len(detector.events) == 2
        assert detector.total_suspended_seconds == 1800.0

    def test_the_recent_sleep_window_is_an_hour(self) -> None:
        assert RECENT_SLEEP_WINDOW_SECONDS == 3600.0
