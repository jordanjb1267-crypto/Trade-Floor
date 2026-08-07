"""The §18 session supervisor: scheduled operation, health, fail-closed.

First Phase 6 increment (§22): **scheduled laptop operation**. The loop wakes
at each London-anchored session event (`runner/schedule.py`), runs the checks
that event calls for, notifies the owner (§19), and writes the operational
record §22 asks for. It does not yet evaluate market state or run the §6A
workflow — live-data shadow evaluation is the next increment, and pretending
otherwise here would be a claim the code does not deliver.

What this module will never do, by construction rather than restraint: it
imports nothing that can place, modify, or cancel an order. Shadow mode never
places orders (§12.1), and the §0 iron rule 1 acceptance test for this module
is that the import graph cannot reach the order path.

Every dependency with a side effect — the broker probe, the notifier, sleep,
and the clock — is injected, so the whole session lifecycle is testable as a
pure sequence. `scripts/run_supervisor.py` composes the real ones.

Failure posture (§0.10): a failed health probe never crashes the supervisor
and never gets retried into silence. It emits a DATA_OR_BROKER_FAILURE alert,
marks the session degraded, and keeps the schedule — the flatten-boundary
check still runs on a degraded day, because "we could not verify we are flat"
is precisely the state the owner must hear about (§14, F-5).
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from trading_firm.notify.surface import NotificationKind
from trading_firm.runner.schedule import LONDON, ScheduledEvent, SessionEvent, next_event
from trading_firm.runner.timing import (
    EventTiming,
    FlatState,
    SessionAuthority,
    SessionAuthorityLatch,
    SessionVerdict,
    assess_session,
    evaluate,
)
from trading_firm.sessions.clock import SessionClock

# Injected dependency shapes. The notifier returns bool (delivered) — §18: a
# notification failure is recorded and never fatal. The probe returns a
# HealthReport and may raise; the supervisor catches everything it raises.
Notify = Callable[[NotificationKind, str], bool]
Probe = Callable[[], "HealthReport"]
Sleep = Callable[[float], None]
Now = Callable[[], dt.datetime]
# Advisory liveness ping, called with a phase label. Injected like everything
# else with a side effect; the default is None, so the trading loop is byte-for
# -byte the same sequence with or without observability attached.
Beat = Callable[[str], None]
# §30.9 surveillance sweep: takes the scheduled event, returns a one-line
# outcome for the session record. Injected, optional, advisory — the trading
# loop knows nothing about surveillance internals.
Sweep = Callable[["ScheduledEvent"], str]

# Sleep in bounded slices and recompute the target each wake. A laptop that
# slept through a DST transition, an NTP step, or a lid-close would otherwise
# act on a wakeup computed under the old clock (§18 restart behaviour).
MAX_SLEEP_SLICE_SECONDS = 300.0


@dataclass(frozen=True)
class HealthReport:
    """What the read-only broker/data probe found. Everything §0.10 needs."""

    broker_reachable: bool
    account_flat: bool
    open_position_count: int
    currency: str | None = None
    detail: str = ""

    @property
    def healthy(self) -> bool:
        return self.broker_reachable

    def summary(self) -> str:
        if not self.broker_reachable:
            return f"broker unreachable: {self.detail or 'no detail'}"
        flat = "flat" if self.account_flat else f"{self.open_position_count} OPEN POSITION(S)"
        return f"broker OK, account {flat}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class SessionRecord:
    """One session's operational log, written at flatten (§22 'performance and
    operational reports'; §0.11)."""

    session_date: dt.date
    events: list[dict] = field(default_factory=list)
    degraded: bool = False
    # §31: scheduled and actual instants are both retained, never overwritten,
    # so a report stays auditable long after the session.
    timings: dict[SessionEvent, EventTiming] = field(default_factory=dict)
    flat_state: FlatState = FlatState.UNVERIFIED
    unacceptable: set[SessionEvent] = field(default_factory=set)
    suspension_detected: bool = False
    authority_state: str = "pre_session"
    clock_regressions: int = 0
    health_verified: bool = False
    power_verified: bool = True

    def note(
        self,
        event: SessionEvent,
        at: dt.datetime,
        outcome: str,
        scheduled_at: dt.datetime | None = None,
    ) -> None:
        timing = None
        if scheduled_at is not None and event not in self.timings:
            # First execution of this boundary is the one timed. Later notes
            # (the §30.9 sweep appends one) annotate the same boundary and must
            # not restate or improve its timing verdict.
            timing = evaluate(event, scheduled_at, at)
            self.timings[event] = timing
        entry = {"event": event.value, "at": at.isoformat(), "outcome": outcome}
        if timing is not None:
            entry["scheduled_at"] = timing.scheduled_at.isoformat()
            entry["lateness_s"] = round(timing.lateness_seconds, 3)
            entry["timing_status"] = str(timing.status)
        self.events.append(entry)

    def verdict(self) -> SessionVerdict:
        return assess_session(
            timings=self.timings,
            flat_state=self.flat_state,
            suspension_detected=self.suspension_detected,
            health_verified=self.health_verified,
            power_verified=self.power_verified,
            unacceptable_outcomes=frozenset(self.unacceptable),
            authority_state=self.authority_state,
            boundaries_processed=len(self.timings),
        )


class Supervisor:
    def __init__(
        self,
        clock: SessionClock,
        probe: Probe,
        notify: Notify,
        report_dir: Path,
        now: Now,
        sleep: Sleep,
        heartbeat: Beat | None = None,
        sweep: Sweep | None = None,
        suspension: object | None = None,
    ) -> None:
        self._clock = clock
        self._probe = probe
        self._notify = notify
        self._report_dir = report_dir
        self._now = now
        self._sleep = sleep
        self._heartbeat = heartbeat
        self._sweep = sweep
        self._suspension = suspension
        # ONE latch per session (§31.6). Rebuilt only when the session DATE
        # changes; never per boundary, because reconstructing it would discard
        # the monotonic state that makes a prohibition irreversible.
        self._latch: SessionAuthorityLatch | None = None
        self._latch_date: dt.date | None = None
        self._record: SessionRecord | None = None
        self.stopping = False

    # -------------------------------------------------------------- liveness

    def _beat(self, phase: str) -> None:
        """Advisory liveness ping (§18 posture, same as the notifier).

        A failing heartbeat must never stop the loop it exists to observe, and
        swallowing the error is not hiding it: the heartbeat then goes stale on
        disk, and `liveness.diagnose()` reports STALE. The absence of a beat is
        itself the alarm, so there is nothing to re-raise.
        """
        if self._heartbeat is None:
            return
        try:
            self._heartbeat(phase)
        except Exception:  # noqa: BLE001, S110 — see docstring
            pass

    # ------------------------------------------------------------------ probe

    def _checked_probe(self) -> HealthReport:
        """Run the probe; a raising probe is a failed probe, never a crash."""
        try:
            return self._probe()
        except Exception as error:  # noqa: BLE001 — §0.10: any failure fails closed
            return HealthReport(
                broker_reachable=False,
                account_flat=False,
                open_position_count=-1,
                detail=f"{type(error).__name__}: {error}",
            )

    # ----------------------------------------------------- §31.6 authority

    def latch_for(self, session_date: dt.date) -> SessionAuthorityLatch:
        """The session's single latch, built from the governing §14 boundaries.

        Keyed on the session DATE: a genuinely new trading session gets a fresh
        latch, and every iteration within one session gets the same object. A
        latch rebuilt per boundary would reset its monotonic state and silently
        restore permissions the wall clock had already withdrawn.
        """
        if self._latch is None or self._latch_date != session_date:
            b = self._clock.boundaries(session_date)
            self._latch = SessionAuthorityLatch(
                activation_at=b["activation"],
                entry_cutoff_at=b["entry_cutoff"],
                flatten_at=b["flatten"],
            )
            self._latch_date = session_date
        return self._latch

    def advance_authority(
        self, session_date: dt.date, now: dt.datetime | None = None
    ) -> SessionAuthority:
        """Advance authority from the AUTHORITATIVE wall clock.

        Called by `run_forever` on every iteration BEFORE any scheduled event
        is processed, and again at the top of `handle()` so a direct call
        (`--once`, tests) cannot bypass it. The loop is the mechanism; the
        call in `handle()` is a backstop, not the design — authority must not
        depend on a handler running, which is the whole point of §31.6.

        Converted to Europe/London explicitly: the boundaries are London
        instants, and comparing against a differently-zoned clock is how a
        timezone anomaly becomes a permission bug.
        """
        moment = (now if now is not None else self._now()).astimezone(LONDON)
        latch = self.latch_for(session_date)
        state = latch.observe(moment)
        if self._record is not None and self._record.session_date == session_date:
            # Report evidence is SOURCED from the live latch, never synthesized,
            # so a report can prove the runtime control was actually exercised.
            self._record.authority_state = str(state)
            self._record.clock_regressions = latch.regressions_observed
        return state

    @property
    def entry_permitted(self) -> bool:
        """Live new-entry authority. False forever once 10:30 is observed."""
        return self._latch is not None and self._latch.entry_permitted

    # ------------------------------------------------------------------ events

    def handle(self, scheduled: ScheduledEvent) -> None:
        """Run one session event. Public so tests drive the lifecycle directly."""
        # §31.6 mandatory ordering: authority advances from the wall clock
        # before any session-state-dependent action is evaluated.
        self.advance_authority(scheduled.session_date)
        if self._record is None or self._record.session_date != scheduled.session_date:
            self._record = SessionRecord(session_date=scheduled.session_date)
        record = self._record
        self.advance_authority(scheduled.session_date)
        at = self._now()

        if scheduled.event is SessionEvent.PRE_STARTUP:
            health = self._checked_probe()
            record.note(scheduled.event, at, health.summary(), scheduled.at)
            record.health_verified = health.healthy
            if health.healthy:
                self._notify(
                    NotificationKind.SESSION_START_HEALTH,
                    f"{scheduled.session_date} session starting. {health.summary()}",
                )
            else:
                record.degraded = True
                record.unacceptable.add(scheduled.event)
                self._notify(
                    NotificationKind.DATA_OR_BROKER_FAILURE,
                    f"{scheduled.session_date} pre-startup health FAILED — session "
                    f"degraded, no evaluation will run today (§0.10). "
                    f"{health.summary()}",
                )

        elif scheduled.event in (SessionEvent.BRIEFING, SessionEvent.ACTIVATION):
            # Shadow evaluation attaches here in the next increment. Today the
            # supervisor records that the boundary was kept, which is the §22
            # "scheduled laptop operation" deliverable — and on a degraded day
            # it records that evaluation was correctly withheld.
            #
            # The §30.9 surveillance sweep rides this same boundary, injected
            # like the heartbeat: default None means byte-identical behavior,
            # a degraded day withholds it exactly as it withholds evaluation,
            # and a raising sweep is a recorded failure, never a crash —
            # surveillance observes the session and must not be able to end it.
            outcome = "skipped: session degraded" if record.degraded else "boundary kept"
            record.note(scheduled.event, at, outcome, scheduled.at)
            if self._sweep is not None and not record.degraded:
                try:
                    record.note(scheduled.event, at, f"sweep: {self._sweep(scheduled)}")
                except Exception as error:  # noqa: BLE001 — observe-only (§30.2)
                    record.note(
                        scheduled.event, at,
                        f"sweep FAILED (contained): {type(error).__name__}: {error}",
                    )

        elif scheduled.event is SessionEvent.ENTRY_CUTOFF:
            record.note(scheduled.event, at, "manage-only from here (§14)", scheduled.at)

        elif scheduled.event is SessionEvent.FLATTEN:
            # Runs on degraded days too: "could not verify flat" must reach the
            # owner, not be skipped along with everything else (§14, F-5).
            health = self._checked_probe()
            if not health.broker_reachable:
                record.note(scheduled.event, at, f"UNVERIFIED: {health.summary()}", scheduled.at)
                self._notify(
                    NotificationKind.DATA_OR_BROKER_FAILURE,
                    f"{scheduled.session_date} 11:00 flatten boundary: could NOT "
                    f"verify the account is flat — {health.summary()}. Check the "
                    f"broker directly (§14, F-5).",
                )
                # §31.2: could-not-verify is never nominal.
                record.flat_state = FlatState.UNVERIFIED
                record.degraded = True
                record.unacceptable.add(scheduled.event)
            elif not health.account_flat:
                record.note(scheduled.event, at, f"NOT FLAT: {health.summary()}", scheduled.at)
                self._notify(
                    NotificationKind.RISK_HALT,
                    f"{scheduled.session_date} 11:00 flatten boundary: account is "
                    f"NOT flat ({health.open_position_count} open). The flatten "
                    f"boundary is inviolate — intervene now (§14, F-5).",
                )
                record.flat_state = FlatState.VERIFIED_NON_FLAT
                record.degraded = True
                record.unacceptable.add(scheduled.event)
            else:
                record.flat_state = FlatState.VERIFIED_FLAT
                record.note(scheduled.event, at, "verified flat", scheduled.at)
            # §14 lifecycle: FLATTENING -> RECONCILIATION -> CLOSED, or HALTED
            # when flat state could not be proven (§31.2). Driven on the live
            # latch so the report's terminal state is evidence, not a label.
            latch = self.latch_for(scheduled.session_date)
            latch.begin_reconciliation()
            if record.flat_state is FlatState.VERIFIED_FLAT:
                latch.close()
            else:
                latch.halt()
            record.authority_state = str(latch.state)
            record.clock_regressions = latch.regressions_observed
            self._write_report(record)
            verdict = record.verdict()
            if verdict.degraded:
                # §31.1/§31.2: a hard-boundary breach or an unverified flat
                # state takes the SEVERE path, not the routine daily report.
                # RISK_HALT and DATA_OR_BROKER_FAILURE are the two §19 alert
                # kinds; which one depends on whether the broker answered.
                kind = (
                    NotificationKind.DATA_OR_BROKER_FAILURE
                    if verdict.flat_state is FlatState.UNVERIFIED
                    else NotificationKind.RISK_HALT
                )
                self._notify(kind, "SESSION DEGRADED — " + verdict.summary(
                    record.session_date))
            self._notify(
                NotificationKind.DAILY_SESSION_REPORT,
                self._daily_summary(record),
            )
            self._record = None

    # ------------------------------------------------------------------ report

    def _write_report(self, record: SessionRecord) -> Path:
        self._report_dir.mkdir(parents=True, exist_ok=True)
        path = self._report_dir / f"{record.session_date}-session.json"
        verdict = record.verdict()
        payload = {
            "session_date": record.session_date.isoformat(),
            "degraded": verdict.degraded,
            "nominal": verdict.nominal,
            "qualifying": verdict.qualifying,
            "session_health": str(verdict.health),
            "qualification": str(verdict.qualification),
            "qualification_reason": verdict.qualification_reason,
            "authority_state": str(record.authority_state),
            "clock_regressions": record.clock_regressions,
            "required_event_count": verdict.required_event_count,
            "clean_event_count": verdict.clean_event_count,
            "late_event_count": verdict.late_event_count,
            "failed_event_count": verdict.failed_event_count,
            "max_lateness_s": round(verdict.max_lateness_seconds, 3),
            "flat_state": str(verdict.flat_state),
            "suspension_detected": verdict.suspension_detected,
            "reasons": list(verdict.reasons),
            "events": record.events,
            "environment": "shadow",
            "orders_placed": 0,  # structurally: this process cannot place any
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return path

    @staticmethod
    def _daily_summary(record: SessionRecord) -> str:
        """§31.3/§31.4. Was a substring test over the outcome string, which
        reported a flatten 73 minutes past an inviolate boundary as "nominal,
        5/5 events clean" on 2026-08-05. The verdict now derives every number
        and the headline from the same assessment, so they cannot disagree."""
        return record.verdict().summary(record.session_date)

    # ------------------------------------------------------------------ loop

    def run_forever(self) -> None:
        """Wake at each event until stopped. Sleeps in bounded slices and
        recomputes after every slice, so clock steps and DST transitions are
        absorbed within five minutes instead of compounding."""
        while not self.stopping:
            # §31.6 MANDATORY ORDERING, every iteration:
            #   (1) authoritative Europe/London time
            #   (2) suspension / clock-regression evidence
            #   (3) advance the session authority latch
            #   (4) only then process scheduled events.
            # The wall clock establishes authority; the handler does not. A
            # handler that ran late must be incapable of restoring a permission
            # the clock already withdrew, which is only guaranteed if authority
            # advances BEFORE the handler is reached.
            scheduled = next_event(self._clock, self._now())
            self._sample_suspension()
            self.advance_authority(scheduled.session_date)
            self._beat("waiting")
            while not self.stopping:
                remaining = scheduled.seconds_until(self._now())
                if remaining <= 0:
                    break
                self._sleep(min(remaining, MAX_SLEEP_SLICE_SECONDS))
                # §31.5: sample BEFORE recomputing the target. A suspension is
                # wall-clock time the monotonic clock did not see, and the only
                # moment we can observe it is on the wake that follows.
                self._sample_suspension()
                # Advance on every wake, so a session that resumes at 10:54
                # after a suspension is MANAGE_ONLY before anything else runs.
                self.advance_authority(scheduled.session_date)
                # One beat per slice, so a stalled loop is visible within a
                # slice rather than at the next session boundary hours away.
                self._beat("waiting")
            if not self.stopping:
                # Final advancement from the CURRENT clock immediately before
                # the handler — the boundary may have been crossed while the
                # last sleep slice was running.
                self.advance_authority(scheduled.session_date)
                self.handle(scheduled)
                self._beat("handled")

    # --------------------------------------------------------- §31.5 suspension

    def _sample_suspension(self) -> None:
        """Record a detected freeze on the live session, if one is open.

        Expired boundaries are NOT replayed as timely: `handle()` timestamps
        every event with the real wall clock and `timing.evaluate` compares it
        to the scheduled instant, so a boundary reached late after a suspension
        is classified LATE on its own evidence. This flag adds the reason.
        """
        if self._suspension is None:
            return
        try:
            event = self._suspension.sample()
        except Exception:  # noqa: BLE001, S110 — a detector must not end a session
            return
        if event is not None and self._record is not None:
            self._record.suspension_detected = True
