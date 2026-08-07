"""Session boundary timing and sleep integrity (§31, amendment A-4).

Scenarios A–N from the owner's correction brief, plus fixtures built from the
ACTUAL timestamps of the 2026-08-05 and 2026-08-06 incidents. Those two
fixtures are the point of the file: under the old validator both scored
"nominal, 5/5 events clean", and both must now fail.

Everything here is pure — no clock, no broker, no filesystem, no supervisor.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from trading_firm.runner.schedule import SessionEvent
from trading_firm.runner.timing import (
    POLICY,
    REQUIRED_EVENTS,
    BoundaryClass,
    FlatState,
    Qualification,
    SessionAuthority,
    SessionAuthorityLatch,
    SessionHealth,
    TimingStatus,
    assess_session,
    entry_permitted,
    evaluate,
    flat_verification_deadline,
)

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 8, 6)

SCHEDULE = {
    SessionEvent.PRE_STARTUP: dt.time(7, 15),
    SessionEvent.BRIEFING: dt.time(7, 40),
    SessionEvent.ACTIVATION: dt.time(8, 0),
    SessionEvent.ENTRY_CUTOFF: dt.time(10, 30),
    SessionEvent.FLATTEN: dt.time(11, 0),
}


def scheduled(event: SessionEvent, day: dt.date = DAY) -> dt.datetime:
    return dt.datetime.combine(day, SCHEDULE[event], tzinfo=LONDON)


def session(lateness: dict[SessionEvent, float], day: dt.date = DAY):
    """Build a full timing map from per-event lateness in seconds."""
    out = {}
    for event in REQUIRED_EVENTS:
        at = scheduled(event, day) + dt.timedelta(seconds=lateness.get(event, 0.0))
        out[event] = evaluate(event, scheduled(event, day), at)
    return out


class TestScenarioAOnTime:
    def test_all_five_on_time_is_clean_and_nominal(self) -> None:
        verdict = assess_session(
            timings=session({}), flat_state=FlatState.VERIFIED_FLAT, health_verified=True
        )
        assert verdict.clean_event_count == 5
        assert verdict.late_event_count == 0
        assert verdict.failed_event_count == 0
        assert verdict.nominal and verdict.qualifying and not verdict.degraded
        assert "nominal" in verdict.summary(DAY)


class TestScenarioBPermittedJitter:
    @pytest.mark.parametrize(
        ("event", "seconds"),
        [
            (SessionEvent.PRE_STARTUP, 119),
            (SessionEvent.BRIEFING, 120),
            (SessionEvent.ACTIVATION, 59),
            (SessionEvent.ENTRY_CUTOFF, 5),
            (SessionEvent.FLATTEN, 5),
        ],
    )
    def test_at_or_inside_tolerance_stays_clean(self, event, seconds) -> None:
        verdict = assess_session(
            timings=session({event: seconds}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert verdict.clean_event_count == 5, verdict.reasons
        assert verdict.nominal

    @pytest.mark.parametrize(
        ("event", "seconds"),
        [
            (SessionEvent.PRE_STARTUP, 121),
            (SessionEvent.BRIEFING, 121),
            (SessionEvent.ACTIVATION, 61),
            (SessionEvent.ENTRY_CUTOFF, 6),
            (SessionEvent.FLATTEN, 6),
        ],
    )
    def test_one_second_past_tolerance_is_late(self, event, seconds) -> None:
        verdict = assess_session(
            timings=session({event: seconds}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert verdict.late_event_count == 1
        assert not verdict.nominal and not verdict.qualifying


class TestScenariosCToFLateBoundaries:
    @pytest.mark.parametrize(
        "event",
        [
            SessionEvent.PRE_STARTUP,
            SessionEvent.BRIEFING,
            SessionEvent.ACTIVATION,
            SessionEvent.ENTRY_CUTOFF,
        ],
    )
    def test_a_materially_late_boundary_disqualifies(self, event) -> None:
        verdict = assess_session(
            timings=session({event: 900}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert verdict.clean_event_count == 4
        assert verdict.late_event_count == 1
        assert not verdict.nominal
        assert not verdict.qualifying
        assert any(event.value in r for r in verdict.reasons)

    def test_a_hard_boundary_says_so_in_the_reason(self) -> None:
        verdict = assess_session(
            timings=session({SessionEvent.ENTRY_CUTOFF: 900}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert any("HARD BOUNDARY BREACH" in r for r in verdict.reasons)


class TestScenarioGAug05Incident:
    """The real 2026-08-05 timings. Reported "nominal, 5/5 events clean"."""

    LATENESS = {
        SessionEvent.PRE_STARTUP: 255.4,
        SessionEvent.BRIEFING: 270.4,
        SessionEvent.ACTIVATION: 1562.1,
        SessionEvent.ENTRY_CUTOFF: 789.5,
        SessionEvent.FLATTEN: 4396.6,
    }

    def test_it_is_not_five_of_five_clean(self) -> None:
        verdict = assess_session(
            timings=session(self.LATENESS),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert verdict.clean_event_count != 5
        assert verdict.clean_event_count == 0, verdict.reasons

    def test_it_is_not_nominal(self) -> None:
        verdict = assess_session(
            timings=session(self.LATENESS),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert not verdict.nominal
        assert not verdict.qualifying
        assert "DEGRADED" in verdict.summary(dt.date(2026, 8, 5))
        assert "nominal" not in verdict.summary(dt.date(2026, 8, 5))

    def test_the_flatten_breach_is_named(self) -> None:
        verdict = assess_session(
            timings=session(self.LATENESS),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert any("flatten HARD BOUNDARY BREACH" in r for r in verdict.reasons)
        assert verdict.max_lateness_seconds == pytest.approx(4396.6)


class TestScenarioHAug06Incident:
    """The real 2026-08-06 timings, with the HTTP 401 flat-state failure."""

    LATENESS = {
        SessionEvent.PRE_STARTUP: 550.7,
        SessionEvent.BRIEFING: 988.1,
        SessionEvent.ACTIVATION: 850.3,
        SessionEvent.ENTRY_CUTOFF: 1469.8,
        SessionEvent.FLATTEN: 4568.2,
    }

    def _verdict(self):
        return assess_session(
            timings=session(self.LATENESS),
            flat_state=FlatState.UNVERIFIED,
            health_verified=True,
            unacceptable_outcomes=frozenset({SessionEvent.FLATTEN}),
        )

    def test_never_nominal(self) -> None:
        verdict = self._verdict()
        assert not verdict.nominal
        assert verdict.degraded
        assert "nominal" not in verdict.summary(dt.date(2026, 8, 6))

    def test_flat_state_is_unverified_and_reported(self) -> None:
        verdict = self._verdict()
        assert verdict.flat_state is FlatState.UNVERIFIED
        assert "flat state UNVERIFIED" in verdict.reasons
        assert "UNVERIFIED" in verdict.summary(dt.date(2026, 8, 6))

    def test_it_is_non_qualifying(self) -> None:
        assert not self._verdict().qualifying

    def test_the_failed_flatten_counts_as_failed_not_merely_late(self) -> None:
        assert self._verdict().failed_event_count >= 1


class TestScenarioISuspensionGap:
    def test_suspension_alone_degrades_an_otherwise_perfect_session(self) -> None:
        verdict = assess_session(
            timings=session({}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
            suspension_detected=True,
        )
        assert not verdict.nominal
        assert not verdict.qualifying
        assert verdict.suspension_detected
        assert "runtime suspension detected during the session" in verdict.reasons

    def test_expired_boundaries_are_not_replayed_as_clean(self) -> None:
        """A backlog executed on wake carries real wall-clock timestamps, so
        each boundary is judged on its own lateness rather than forgiven."""
        woke = {event: 5400.0 for event in REQUIRED_EVENTS}
        verdict = assess_session(
            timings=session(woke),
            flat_state=FlatState.VERIFIED_FLAT,
            suspension_detected=True,
            health_verified=True,
        )
        assert verdict.clean_event_count == 0
        assert verdict.late_event_count == 5


class TestScenarioJWakeAfterEntryCutoff:
    def test_entry_authority_is_wall_clock_not_handler(self) -> None:
        """§31.1 zero authority tolerance: eligibility never consults the
        handler, so a late handler cannot extend the window."""
        cutoff = scheduled(SessionEvent.ENTRY_CUTOFF)
        assert entry_permitted(cutoff - dt.timedelta(seconds=1), cutoff)
        assert not entry_permitted(cutoff, cutoff)
        assert not entry_permitted(cutoff + dt.timedelta(seconds=1), cutoff)

    def test_waking_an_hour_late_grants_nothing_retroactively(self) -> None:
        cutoff = scheduled(SessionEvent.ENTRY_CUTOFF)
        woke = cutoff + dt.timedelta(hours=1)
        assert not entry_permitted(woke, cutoff)

    def test_a_late_activation_does_not_create_eligibility(self) -> None:
        verdict = assess_session(
            timings=session({SessionEvent.ACTIVATION: 3600}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
        )
        assert not verdict.qualifying
        assert any("activation" in r for r in verdict.reasons)


class TestScenarioKWakeAfterFlatten:
    def test_a_later_verification_does_not_make_flatten_timely(self) -> None:
        """§31.2 verbatim: a later successful reconciliation does not
        retroactively make the original flatten timely."""
        verdict = assess_session(
            timings=session({SessionEvent.FLATTEN: 4568}),
            flat_state=FlatState.VERIFIED_FLAT,  # reconciled later, successfully
            health_verified=True,
        )
        assert verdict.degraded
        assert not verdict.qualifying
        assert verdict.late_event_count == 1
        assert any("flatten HARD BOUNDARY BREACH" in r for r in verdict.reasons)

    def test_the_verification_deadline_is_one_minute(self) -> None:
        assert flat_verification_deadline(
            scheduled(SessionEvent.FLATTEN)
        ) == scheduled(SessionEvent.FLATTEN) + dt.timedelta(seconds=60)


class TestScenarioLBroker401:
    def test_unverified_fails_closed_and_degrades(self) -> None:
        verdict = assess_session(
            timings=session({}),
            flat_state=FlatState.UNVERIFIED,
            health_verified=True,
        )
        assert verdict.degraded and not verdict.nominal and not verdict.qualifying
        assert "flat state UNVERIFIED" in verdict.reasons

    def test_the_three_flat_states_stay_distinct(self) -> None:
        assert len(set(FlatState)) == 3
        for state, nominal in (
            (FlatState.VERIFIED_FLAT, True),
            (FlatState.VERIFIED_NON_FLAT, False),
            (FlatState.UNVERIFIED, False),
        ):
            verdict = assess_session(
                timings=session({}), flat_state=state, health_verified=True
            )
            assert verdict.nominal is nominal


class TestOrderAndPresence:
    def test_a_missing_boundary_is_failed_not_ignored(self) -> None:
        timings = session({})
        del timings[SessionEvent.FLATTEN]
        verdict = assess_session(
            timings=timings, flat_state=FlatState.VERIFIED_FLAT, health_verified=True
        )
        assert verdict.failed_event_count == 1
        assert "flatten did not execute" in verdict.reasons
        assert not verdict.nominal

    def test_out_of_order_execution_is_not_clean(self) -> None:
        timings = session({})
        # flatten executed before entry_cutoff — a replayed backlog
        timings[SessionEvent.FLATTEN] = evaluate(
            SessionEvent.FLATTEN,
            scheduled(SessionEvent.FLATTEN),
            scheduled(SessionEvent.ENTRY_CUTOFF) - dt.timedelta(minutes=5),
        )
        verdict = assess_session(
            timings=timings, flat_state=FlatState.VERIFIED_FLAT, health_verified=True
        )
        assert "events executed out of order" in verdict.reasons
        assert verdict.clean_event_count < 5

    def test_unverified_health_degrades(self) -> None:
        verdict = assess_session(
            timings=session({}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=False,
        )
        assert not verdict.nominal
        assert "required health checks not verified" in verdict.reasons

    def test_power_unverified_disqualifies_without_degrading(self) -> None:
        """§31.5: power readiness gates the STABILITY GATE. A sound session on
        an unproven machine is honest but non-qualifying."""
        verdict = assess_session(
            timings=session({}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
            power_verified=False,
        )
        assert verdict.nominal
        assert not verdict.qualifying


class TestRatifiedPolicyConstants:
    def test_tolerances_match_the_owner_ratified_table(self) -> None:
        assert POLICY[SessionEvent.PRE_STARTUP].tolerance_seconds == 120
        assert POLICY[SessionEvent.BRIEFING].tolerance_seconds == 120
        assert POLICY[SessionEvent.ACTIVATION].tolerance_seconds == 60
        assert POLICY[SessionEvent.ENTRY_CUTOFF].tolerance_seconds == 5
        assert POLICY[SessionEvent.FLATTEN].tolerance_seconds == 5

    def test_boundary_classes_match_the_ratified_table(self) -> None:
        assert POLICY[SessionEvent.ENTRY_CUTOFF].boundary_class is BoundaryClass.HARD
        assert POLICY[SessionEvent.FLATTEN].boundary_class is BoundaryClass.HARD
        assert POLICY[SessionEvent.ACTIVATION].boundary_class is BoundaryClass.PERMISSION
        assert POLICY[SessionEvent.PRE_STARTUP].boundary_class is BoundaryClass.CHECKPOINT

    def test_early_execution_is_clamped_not_negative(self) -> None:
        early = evaluate(
            SessionEvent.FLATTEN,
            scheduled(SessionEvent.FLATTEN),
            scheduled(SessionEvent.FLATTEN) - dt.timedelta(seconds=30),
        )
        assert early.lateness_seconds == 0.0
        assert early.status is TimingStatus.ON_TIME

    def test_both_timestamps_are_retained(self) -> None:
        timing = evaluate(
            SessionEvent.BRIEFING,
            scheduled(SessionEvent.BRIEFING),
            scheduled(SessionEvent.BRIEFING) + dt.timedelta(seconds=300),
        )
        assert timing.scheduled_at == scheduled(SessionEvent.BRIEFING)
        assert timing.actual_at != timing.scheduled_at
        assert timing.lateness_seconds == 300


class TestAuthorityLatchIsIrreversible:
    """§31.6 owner hardening: the wall clock ESTABLISHES a prohibition; the
    latch makes it IRREVERSIBLE. A pure comparison is reversible, and a
    prohibition undone by a clock adjustment is not a prohibition."""

    def _latch(self, day: dt.date = DAY) -> SessionAuthorityLatch:
        return SessionAuthorityLatch(
            activation_at=scheduled(SessionEvent.ACTIVATION, day),
            entry_cutoff_at=scheduled(SessionEvent.ENTRY_CUTOFF, day),
            flatten_at=scheduled(SessionEvent.FLATTEN, day),
        )

    def test_crossing_1030_disables_entry_authority(self) -> None:
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.ACTIVATION) + dt.timedelta(minutes=5))
        assert latch.entry_permitted
        latch.observe(scheduled(SessionEvent.ENTRY_CUTOFF))
        assert not latch.entry_permitted
        assert latch.state is SessionAuthority.MANAGE_ONLY

    def test_a_backward_clock_cannot_restore_entry_authority(self) -> None:
        """NTP correction, manual change, timezone anomaly — none may re-open
        the entry window."""
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.ENTRY_CUTOFF))
        assert not latch.entry_permitted
        # Clock jumps back an hour, into what was ACTIVE.
        latch.observe(scheduled(SessionEvent.ENTRY_CUTOFF) - dt.timedelta(hours=1))
        assert not latch.entry_permitted
        assert latch.state is SessionAuthority.MANAGE_ONLY
        assert latch.regressions_observed == 1

    def test_a_backward_clock_is_counted_as_evidence(self) -> None:
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.FLATTEN))
        for _ in range(3):
            latch.observe(scheduled(SessionEvent.ACTIVATION))
        assert latch.regressions_observed == 3
        assert latch.state is SessionAuthority.FLATTENING

    def test_waking_after_1030_cannot_restore_entry_authority(self) -> None:
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.ACTIVATION))
        assert latch.entry_permitted
        # Clamshell sleep; wakes 90 minutes later.
        latch.observe(scheduled(SessionEvent.ENTRY_CUTOFF) + dt.timedelta(minutes=90))
        assert not latch.entry_permitted

    def test_reaching_1100_leaves_active_permanently(self) -> None:
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.ACTIVATION))
        latch.observe(scheduled(SessionEvent.FLATTEN))
        assert latch.state is SessionAuthority.FLATTENING
        assert not latch.entry_permitted
        assert not latch.may_activate

    def test_waking_after_1100_cannot_replay_active_or_activation(self) -> None:
        """The exact 2026-08-06 shape: the supervisor woke at 12:16 London."""
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.FLATTEN) + dt.timedelta(minutes=76))
        assert latch.state is SessionAuthority.FLATTENING
        assert not latch.may_activate
        assert not latch.entry_permitted
        # And a later reading inside the old ACTIVE window changes nothing.
        latch.observe(scheduled(SessionEvent.ACTIVATION) + dt.timedelta(minutes=1))
        assert not latch.may_activate
        assert not latch.entry_permitted

    def test_activation_is_permitted_only_before_the_latch_advances(self) -> None:
        latch = self._latch()
        assert latch.may_activate
        latch.observe(scheduled(SessionEvent.ACTIVATION))
        assert latch.may_activate
        latch.observe(scheduled(SessionEvent.ENTRY_CUTOFF))
        assert not latch.may_activate

    def test_dst_cannot_re_enable_a_latched_prohibition(self) -> None:
        """2026-10-25 is the London DST fall-back: 02:00 BST repeats as 01:00
        GMT. Boundaries are absolute instants, so a repeated wall-clock hour is
        still monotonic in real time — and the latch holds regardless."""
        dst_day = dt.date(2026, 10, 25)
        latch = self._latch(dst_day)
        latch.observe(scheduled(SessionEvent.ENTRY_CUTOFF, dst_day))
        assert not latch.entry_permitted
        # A naive re-reading of the repeated hour, expressed in the other offset.
        ambiguous = scheduled(SessionEvent.ACTIVATION, dst_day).astimezone(dt.UTC)
        latch.observe(ambiguous)
        assert not latch.entry_permitted
        assert latch.state is SessionAuthority.MANAGE_ONLY

    def test_naive_datetimes_are_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            SessionAuthorityLatch(
                activation_at=dt.datetime(2026, 8, 6, 8, 0),
                entry_cutoff_at=scheduled(SessionEvent.ENTRY_CUTOFF),
                flatten_at=scheduled(SessionEvent.FLATTEN),
            )

    def test_the_latch_never_retreats_under_random_clock_noise(self) -> None:
        latch = self._latch()
        base = scheduled(SessionEvent.FLATTEN)
        latch.observe(base)
        highest = latch.state
        for offset in (-7200, 600, -3600, 30, -60, 5):
            latch.observe(base + dt.timedelta(seconds=offset))
            assert latch.state is highest


class TestTwoDimensionalReporting:
    """§31.4 owner amendment: a non-qualifying session must never read as
    merely "nominal"."""

    def _sound_but_unprovable(self):
        return assess_session(
            timings=session({}),
            flat_state=FlatState.VERIFIED_FLAT,
            health_verified=True,
            power_verified=False,
        )

    def test_health_and_qualification_are_separate_values(self) -> None:
        verdict = self._sound_but_unprovable()
        assert verdict.health is SessionHealth.NOMINAL
        assert verdict.qualification is Qualification.NON_QUALIFYING

    def test_the_headline_carries_both_dimensions(self) -> None:
        text = self._sound_but_unprovable().summary(DAY)
        assert "NOMINAL EXECUTION" in text
        assert "NON-QUALIFYING" in text
        assert "POWER READINESS UNVERIFIED" in text

    def test_a_non_qualifying_session_never_reads_as_a_bare_nominal(self) -> None:
        text = self._sound_but_unprovable().summary(DAY)
        assert not text.startswith(f"{DAY} nominal")

    def test_a_fully_sound_session_says_qualifying(self) -> None:
        verdict = assess_session(
            timings=session({}), flat_state=FlatState.VERIFIED_FLAT, health_verified=True
        )
        assert "QUALIFYING" in verdict.summary(DAY)
        assert verdict.qualification is Qualification.QUALIFYING

    def test_a_degraded_session_leads_with_degraded(self) -> None:
        verdict = assess_session(
            timings=session({SessionEvent.FLATTEN: 4568}),
            flat_state=FlatState.UNVERIFIED,
            health_verified=True,
        )
        assert verdict.summary(DAY).startswith(f"{DAY} SESSION DEGRADED")
        assert verdict.qualification_reason == "SESSION DEGRADED"


class TestLifecycleExpressesHaltedIndependently:
    """§14/§31.2: the lifecycle must be able to say HALTED and RECONCILIATION,
    on the AUTHORITY axis, independently of the NOMINAL/DEGRADED health axis.
    Before this, §31.2 claimed a transition to HALTED that the code could not
    represent — a spec claim that resolved while being false."""

    def _latch(self) -> SessionAuthorityLatch:
        return SessionAuthorityLatch(
            activation_at=scheduled(SessionEvent.ACTIVATION),
            entry_cutoff_at=scheduled(SessionEvent.ENTRY_CUTOFF),
            flatten_at=scheduled(SessionEvent.FLATTEN),
        )

    def test_reconciliation_follows_flattening(self) -> None:
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.FLATTEN))
        assert latch.begin_reconciliation() is SessionAuthority.RECONCILIATION

    def test_halted_is_reachable_and_terminal(self) -> None:
        latch = self._latch()
        latch.halt()
        assert latch.halted and latch.state is SessionAuthority.HALTED
        # No clock reading un-halts it.
        latch.observe(scheduled(SessionEvent.ACTIVATION))
        assert latch.halted
        # Nor does a clean close.
        latch.close()
        assert latch.halted

    def test_halted_forbids_entry_and_activation(self) -> None:
        latch = self._latch()
        latch.observe(scheduled(SessionEvent.ACTIVATION))
        assert latch.entry_permitted
        latch.halt()
        assert not latch.entry_permitted
        assert not latch.may_activate

    def test_authority_and_health_are_independent_axes(self) -> None:
        """A halted session's health is computed from execution facts, not from
        the halt — and a NOMINAL verdict does not imply the session may act."""
        latch = self._latch()
        latch.halt()
        verdict = assess_session(
            timings=session({}), flat_state=FlatState.VERIFIED_FLAT, health_verified=True
        )
        assert verdict.health is SessionHealth.NOMINAL
        assert latch.state is SessionAuthority.HALTED

    def test_every_section_14_authority_state_is_representable(self) -> None:
        for name in ("PRE_SESSION", "ACTIVE", "MANAGE_ONLY", "FLATTENING",
                     "RECONCILIATION", "CLOSED", "HALTED"):
            assert hasattr(SessionAuthority, name)
