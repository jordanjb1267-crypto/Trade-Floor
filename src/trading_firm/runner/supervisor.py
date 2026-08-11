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
from trading_firm.runner.schedule import (
    _TRADING_WEEKDAYS,
    LONDON,
    ScheduledEvent,
    SessionEvent,
    next_event,
)
from trading_firm.runner.timing import (
    POLICY,
    REQUIRED_EVENTS,
    EventTiming,
    FlatState,
    SessionAuthority,
    SessionAuthorityLatch,
    SessionVerdict,
    assess_session,
    evaluate,
    flat_verification_deadline,
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
# §31.5 power-readiness verifier: returns (verified, detail). Injected by the
# composition script (the real one shells out to pmset via runner.power); the
# default None FAILS CLOSED — absence of a verifier is absence of verification,
# never silent readiness. This default exists because the original defect was
# exactly a default-True `power_verified` that no production code ever set.
PowerCheck = Callable[[], tuple[bool, str]]
# §30.9 surveillance sweep: takes the scheduled event, returns a one-line
# outcome for the session record. Injected, optional, advisory — the trading
# loop knows nothing about surveillance internals.
Sweep = Callable[["ScheduledEvent"], str]

# Sleep in bounded slices and recompute the target each wake. A laptop that
# slept through a DST transition, an NTP step, or a lid-close would otherwise
# act on a wakeup computed under the old clock (§18 restart behaviour).
MAX_SLEEP_SLICE_SECONDS = 300.0

# Bounded, deterministic, DEADLINE-GOVERNED broker-verification retry
# (incidents 2026-08-10 and 2026-08-06 — RC-15 PROBABLE: most consistent with
# an external/OANDA-side transient authorization failure. Same process, same
# credential, same host, same account, accepted immediately before and after,
# no rotation, repeated signature — but we hold no broker-side telemetry, so
# elimination is not certainty). On 08-10 the identical Authorization header
# was accepted on GET /v3/accounts and rejected ~150 ms later on
# .../openPositions. A single-shot probe converted that blip into UNVERIFIED,
# HALTED, severe alert, non-qualifying.
#
# The retry is governed by the boundary's own window, never by accidental
# urllib timing: an attempt starts only if it can legally complete before the
# deadline under the per-attempt budget, the loop never sleeps past the
# deadline, and — the load-bearing theorem — success is accepted as verified
# ONLY when its completion time is at or before the deadline, so VERIFIED_FLAT
# after the §31.2 deadline is unrepresentable regardless of how long a request
# actually ran ("a later successful reconciliation does not retroactively make
# the original flatten timely"). Fail-closed is unchanged: exhaustion, budget
# starvation, and late success all route to UNVERIFIED. Fixed count, fixed
# delay, no jitter — the repo's retry convention (notify/telegram.py).
PROBE_ATTEMPTS = 3
PROBE_RETRY_DELAY_SECONDS = 15.0
# Worst case per attempt: account discovery + openPositions, each bounded by
# the probe's request timeout (12 s in scripts/run_supervisor.py), plus margin.
PROBE_ATTEMPT_BUDGET_SECONDS = 25.0


class NonRetryableProbeError(RuntimeError):
    """A locally-deterministic probe failure (missing or malformed credential,
    invalid local configuration). Retrying cannot change the answer, so the
    verification fails immediately — still closed, without spending the
    window on a foregone conclusion."""


class BrokerReadContractError(RuntimeError):
    """A response that parsed but did not match the read-success schema — an
    error body, a missing field, a wrong shape. Never interpreted as data;
    retried like any transient, because a 5xx body and a momentary gateway
    fault look identical from here."""

# §31.7 bounded-but-eventually-exhaustive recovery: at most this many missed
# expected sessions are attested per recovery PASS. The backlog itself is never
# truncated — each loop iteration processes the next batch, oldest first, until
# every expected date since the operational epoch has its terminal artifact.
# Bounding the PASS keeps a long-dead machine from doing all its bookkeeping in
# one breath; bounding the BACKLOG would silently discard audit history, which
# is the failure this constant must never reintroduce.
MISSED_SESSION_BATCH_LIMIT = 10


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
    # §31.5 fails closed for stability qualification: readiness is proven by an
    # executed pre-startup verification or it is absent. A True default here was
    # the original defect — every production session scored power as verified
    # while no code ever checked it. Only `handle()`'s pre-startup gate may set
    # this True, and only from a verifier that actually ran.
    power_verified: bool = False
    attestation_reasons: tuple[str, ...] = ()

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
            extra_reasons=self.attestation_reasons,
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
        epoch: dt.date | None = None,
        power_check: PowerCheck | None = None,
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
        self._power_check = power_check
        # §31.7 operational epoch: the date of the firm's authoritative durable
        # baseline (database initialization, read by the composition script).
        # None means genuinely uninitialized — nothing was ever expected of
        # this deployment, so nothing is attested. The epoch is NOT derived
        # from report files: an emptied report directory is an evidence gap
        # to be recovered, never proof of a fresh install.
        self._epoch = epoch
        # ONE latch per session (§31.6). Rebuilt only when the session DATE
        # changes; never per boundary, because reconstructing it would discard
        # the monotonic state that makes a prohibition irreversible.
        self._latch: SessionAuthorityLatch | None = None
        self._latch_date: dt.date | None = None
        self._record: SessionRecord | None = None
        # §31.5 "no unresolved suspension or wake condition": a suspension the
        # detector observed while NO session record was open (overnight, or in
        # the pre-session wait) used to vanish — sampled, counted by the
        # detector, recorded nowhere. It is retained here as UNRESOLVED until
        # the next pre-startup gate reads it, fails power readiness closed,
        # and thereby records it into that session's durable report.
        self._pending_suspension = False
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

    def _checked_probe(self, deadline: dt.datetime | None = None) -> HealthReport:
        """Run the probe under the boundary's own verification window.

        Per attempt, in order: (1) refuse to START an attempt that cannot
        legally complete before the deadline under PROBE_ATTEMPT_BUDGET_SECONDS;
        (2) never sleep past the deadline; (3) accept a success as verification
        only if its completion is at or before the deadline — a late success is
        evidence for the record, never verification (§31.2). With no deadline
        (recovery attestation), the bounded three-attempt behavior holds.

        A NonRetryableProbeError fails immediately: a missing local credential
        does not improve with repetition.
        """
        last_error: Exception | None = None
        attempts_made = 0
        for attempt in range(1, PROBE_ATTEMPTS + 1):
            if attempt > 1:
                now = self._now()
                if deadline is not None and (
                    (now - deadline).total_seconds()
                    + PROBE_RETRY_DELAY_SECONDS
                    + PROBE_ATTEMPT_BUDGET_SECONDS
                ) > 0:
                    break  # neither the sleep nor the attempt fits the window
                self._sleep(PROBE_RETRY_DELAY_SECONDS)
            now = self._now()
            if deadline is not None and (
                (now - deadline).total_seconds() + PROBE_ATTEMPT_BUDGET_SECONDS
            ) > 0:
                break  # an attempt started now could not legally complete
            attempts_made = attempt
            try:
                report = self._probe()
            except NonRetryableProbeError as error:
                last_error = error
                break  # deterministic locally: retrying cannot change it
            except Exception as error:  # noqa: BLE001 — §0.10: fail closed, but not on one blip
                last_error = error
                continue
            completed = self._now()
            if deadline is not None and completed > deadline:
                # §31.2: verification must COMPLETE by the deadline. The
                # observation is preserved as evidence; verification is not
                # granted. broker_reachable=False routes the UNVERIFIED path.
                late_by = (completed - deadline).total_seconds()
                observed = (
                    "flat" if report.account_flat
                    else f"{report.open_position_count} open position(s)"
                )
                return HealthReport(
                    broker_reachable=False,
                    account_flat=False,
                    open_position_count=-1,
                    detail=(
                        f"verification completed {late_by:.0f}s AFTER the "
                        f"authorized deadline (attempt {attempt}/{PROBE_ATTEMPTS}); "
                        f"account observed {observed}, too late to verify (§31.2)"
                    ),
                )
            if attempt > 1:
                # A transient occurred and resolved: keep the evidence in the
                # session record rather than letting the recovery hide it.
                report = HealthReport(
                    broker_reachable=report.broker_reachable,
                    account_flat=report.account_flat,
                    open_position_count=report.open_position_count,
                    currency=report.currency,
                    detail="; ".join(
                        part for part in (
                            report.detail,
                            f"verified on attempt {attempt}/{PROBE_ATTEMPTS}",
                        ) if part
                    ),
                )
            return report
        if isinstance(last_error, NonRetryableProbeError):
            suffix = "(non-retryable local failure; no retry attempted)"
        else:
            suffix = f"(after {attempts_made} attempt(s))"
        if deadline is not None:
            suffix += " within the authorized verification window"
        prefix = (
            f"{type(last_error).__name__}: {last_error} " if last_error is not None
            else "verification window exhausted before any attempt could run "
        )
        return HealthReport(
            broker_reachable=False,
            account_flat=False,
            open_position_count=-1,
            detail=prefix + suffix,
        )

    def _checked_power(self) -> tuple[bool, str]:
        """§31.5 pre-startup power readiness. DERIVED, never default-true.

        The ratified conditions: AC power present, the required sleep-
        prevention assertion active, supervisor healthy, heartbeat healthy, no
        unresolved suspension or wake condition, and the runtime suspension
        detector operational. The machine-observable set (AC, assertions,
        recent machine sleep) comes from the injected verifier; the
        process-level unresolved-suspension condition is the retained
        `_pending_suspension` evidence (a gap the wired detector saw while no
        record was open); detector-operational and heartbeat-wired are checked
        here because only the supervisor knows its own wiring; "supervisor
        healthy" is the process executing this line. Heartbeat is verified as
        wired, not as durably healthy — beat failures are swallowed by design
        and surface through liveness.diagnose() as STALE, outside this
        process. Every failure path — including a raising verifier and a
        missing verifier — returns False: qualification readiness is proven
        or absent, never assumed (§31.5 "fails closed for stability
        qualification").
        """
        if self._suspension is None:
            return False, "runtime suspension detector not operational (§31.5)"
        if self._pending_suspension:
            return False, (
                "unresolved pre-session suspension (§31.5): the runtime lost "
                "wall-clock time before session start"
            )
        if self._heartbeat is None:
            return False, "heartbeat not wired (§31.5)"
        if self._power_check is None:
            return False, "no power verifier wired (§31.5) — readiness cannot be assumed"
        try:
            verified, detail = self._power_check()
        except Exception as error:  # noqa: BLE001 — a failing check is a failed check
            return False, f"power check failed: {type(error).__name__} (§31.5)"
        return bool(verified), detail

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

    # ------------------------------------------------- §31.7 missed sessions

    def attest_missed_sessions(self, current: ScheduledEvent) -> list[Path]:
        """Ensure every expected past trading date has exactly one terminal
        report (§31.7). Idempotent: the report FILE is the durable guard, so a
        restart can never duplicate an attestation, and a date whose normal
        report exists is never touched.

        "Never both" holds structurally: the normal report for date D is
        written only by D's own flatten handler while D is the current
        session; this scan covers only dates strictly BEFORE the current
        session date, whose handlers can never run again.

        Expected dates are trading weekdays per the repository's deliberate
        calendar position (schedule.py): holidays RUN and fail closed with a
        report, so a weekday with no report is always a missed session, never
        a market-closed day. Weekends are skipped and never attested.
        """
        written: list[Path] = []

        # An open record from an earlier date is the in-process wake case:
        # terminalize it first, with whatever boundaries it actually observed.
        if self._record is not None and self._record.session_date < current.session_date:
            written.append(self._attest_one(self._record))
            self._record = None

        # Restart / multi-day-down case: the recovery backlog is every expected
        # trading date strictly after the operational epoch and strictly before
        # the current session, whose report file is absent. Derived fresh each
        # pass from epoch + report-dir state, so it is deterministic, survives
        # restarts, and needs no separate backlog store. Oldest first, at most
        # MISSED_SESSION_BATCH_LIMIT per pass; the next loop iteration picks up
        # the next batch until the backlog is empty — bounded per pass,
        # eventually exhaustive over the history (§31.7).
        backlog = self.attestation_backlog(current.session_date)
        batch = backlog[:MISSED_SESSION_BATCH_LIMIT]
        for day in batch:
            written.append(
                self._attest_one(SessionRecord(session_date=day), notify_each=False)
            )
        attested = [w for w in written if w is not None]
        if batch:
            # One summary per recovery pass, not one message per historical
            # date (owner amendment): the owner learns what was recovered and
            # what remains, without a day-per-message flood.
            remaining = len(backlog) - len(batch)
            self._notify(
                NotificationKind.RISK_HALT,
                f"MISSED-SESSION RECOVERY: attested {len(batch)} expected "
                f"session(s) ({batch[0]} .. {batch[-1]}) as MISSED/NON-QUALIFYING; "
                f"{remaining} older-than-batch session(s) still unresolved"
                + (" — recovery continues next pass." if remaining else ". Backlog clear."),
            )
        return attested

    def attestation_backlog(self, before: dt.date) -> list[dt.date]:
        """Expected dates after the epoch, before `before`, with no report.

        Oldest first — deterministic recovery ordering. Empty when the epoch is
        unset (uninitialized deployment) or when every expected date has its
        terminal artifact. Weekends are never expected (schedule calendar).
        """
        if self._epoch is None:
            return []
        missing: list[dt.date] = []
        day = self._epoch + dt.timedelta(days=1)
        while day < before:
            if day.weekday() in _TRADING_WEEKDAYS:
                if not (self._report_dir / f"{day}-session.json").exists():
                    missing.append(day)
            day += dt.timedelta(days=1)
        return missing

    def _attest_one(self, record: SessionRecord, notify_each: bool = True) -> Path | None:
        """Write the terminal attestation for one missed session.

        A LOCAL latch is driven for the missed date — never `self._latch`,
        which belongs to the current session and must not be clobbered. The
        latch observes the CURRENT clock (far past that date's flatten), so
        authority evidence reads flattening-or-later, honestly: nothing here
        fabricates an execution timestamp for a handler that never ran.

        Flat state comes from the existing read-only reconciliation probe,
        performed NOW — recovery-time evidence, labelled as such. A verified
        flat account today does not make the missed session timely (§31.2),
        and it cannot: the absent boundaries alone keep the verdict degraded
        and NON_QUALIFYING.
        """
        path = self._report_dir / f"{record.session_date}-session.json"
        if path.exists():
            return None  # durable idempotency: never overwrite any report

        now = self._now()
        boundaries = self._clock.boundaries(record.session_date)
        latch = SessionAuthorityLatch(
            activation_at=boundaries["activation"],
            entry_cutoff_at=boundaries["entry_cutoff"],
            flatten_at=boundaries["flatten"],
        )
        latch.observe(now.astimezone(LONDON))
        latch.begin_reconciliation()

        health = self._checked_probe()
        if health.broker_reachable and health.account_flat:
            record.flat_state = FlatState.VERIFIED_FLAT
            latch.close()
        elif health.broker_reachable:
            record.flat_state = FlatState.VERIFIED_NON_FLAT
            latch.halt()
        else:
            record.flat_state = FlatState.UNVERIFIED
            latch.halt()
        record.authority_state = str(latch.state)
        record.clock_regressions = latch.regressions_observed
        record.degraded = True
        record.suspension_detected = True
        missed = [e.value for e in REQUIRED_EVENTS if e not in record.timings]
        record.attestation_reasons = (
            "SESSION WINDOW MISSED: runtime suspended or offline through required "
            f"boundaries ({', '.join(missed)}); attested {now.isoformat()} with "
            f"recovery-time flat-state evidence",
        )

        self._write_report(record)
        if notify_each:
            verdict = record.verdict()
            # Same mapping as the flatten severe path: unverified means the
            # broker did not answer (data failure); verified-non-flat and plain
            # missed are risk conditions. Batch recovery passes suppress this
            # and send one summary instead (owner amendment).
            kind = (
                NotificationKind.DATA_OR_BROKER_FAILURE
                if record.flat_state is FlatState.UNVERIFIED
                else NotificationKind.RISK_HALT
            )
            self._notify(kind, "MISSED SESSION — " + verdict.summary(record.session_date))
            self._notify(
                NotificationKind.DAILY_SESSION_REPORT, verdict.summary(record.session_date)
            )
        return path

    # ------------------------------------------------------------------ events

    def handle(self, scheduled: ScheduledEvent) -> None:
        """Run one session event. Public so tests drive the lifecycle directly."""
        # §31.6 mandatory ordering: authority advances from the wall clock
        # before any session-state-dependent action is evaluated; §31.7
        # attestation settles prior sessions before this one is touched.
        self.advance_authority(scheduled.session_date)
        self.attest_missed_sessions(scheduled)
        if self._record is None or self._record.session_date != scheduled.session_date:
            self._record = SessionRecord(session_date=scheduled.session_date)
        record = self._record
        self.advance_authority(scheduled.session_date)
        at = self._now()

        if scheduled.event is SessionEvent.PRE_STARTUP:
            # §31.1: health may not be treated as timely past the checkpoint
            # tolerance, so verification gets exactly that window — its own,
            # never the flatten deadline.
            health = self._checked_probe(
                deadline=scheduled.at + dt.timedelta(
                    seconds=POLICY[SessionEvent.PRE_STARTUP].tolerance_seconds
                )
            )
            power_ok, power_detail = self._checked_power()
            record.power_verified = power_ok
            # The gate has now READ any pending pre-session suspension and its
            # verdict is about to enter this session's durable record — that
            # recording is what resolves the condition (§31.5). It must not
            # taint the following session, whose own gate gets fresh evidence.
            self._pending_suspension = False
            power_note = (
                "power readiness verified" if power_ok
                else f"power readiness UNVERIFIED: {power_detail}"
            )
            record.note(
                scheduled.event, at,
                f"{health.summary()}; {power_note}", scheduled.at,
            )
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
            # §31.2: the authoritative deadline, 11:00 -> 11:01 London, from
            # the repository's single deadline function.
            health = self._checked_probe(
                deadline=flat_verification_deadline(scheduled.at)
            )
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
                # Carry the probe detail: a flat verification that needed a
                # retry says so in the record (incident 2026-08-10).
                outcome = "verified flat" + (f" ({health.detail})" if health.detail else "")
                record.note(scheduled.event, at, outcome, scheduled.at)
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
            # §31.7: settle every prior expected session before this one
            # proceeds — authority first, attestation second, events third.
            self.attest_missed_sessions(scheduled)
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
        if event is None:
            return
        if self._record is not None:
            self._record.suspension_detected = True
        else:
            # No session record is open: the evidence must not vanish. It is
            # held as an unresolved condition for the next pre-startup power
            # gate (§31.5 "no unresolved suspension or wake condition").
            self._pending_suspension = True
