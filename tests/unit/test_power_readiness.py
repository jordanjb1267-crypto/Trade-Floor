"""Power readiness and suspension detection (§31.5, amendment A-4).

The 2026-08-05/06 incidents were caused by clamshell sleep that `caffeinate -i`
never prevented, and nothing in the runtime noticed. These tests pin both
halves of the correction: what macOS can prove before a session, and how the
runtime detects that it was frozen during one.

`pmset` is never invoked — every parser is fed captured output, and the
suspension detector takes injected clocks, so nothing here sleeps or shells out.
"""

from __future__ import annotations

from trading_firm.runner.power import (
    RECENT_SLEEP_WINDOW_SECONDS,
    SUSPENSION_THRESHOLD_SECONDS,
    PowerSource,
    PowerState,
    SuspensionDetector,
    count_recent_sleep_events,
    parse_assertions,
    parse_power_source,
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
        assert count_recent_sleep_events(SLEEP_LOG) == 2

    def test_no_sleep_log_counts_zero(self) -> None:
        assert count_recent_sleep_events("") == 0


class TestReadiness:
    def _state(self, **kw) -> PowerState:
        base = dict(
            source=PowerSource.AC,
            prevent_system_sleep=True,
            prevent_idle_sleep=True,
            recent_sleep_events=0,
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
