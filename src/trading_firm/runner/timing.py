"""Session boundary timing policy and session verdict (§31, amendment A-4).

§14 fixes the six boundaries to exact Europe/London instants and calls the
11:00 flatten inviolate; it never said how late is too late. §31 supplies the
ratified tolerances, and this module is their deterministic implementation.

Everything here is a PURE function over plain data. No clock, no filesystem,
no broker, no notifier — so every tolerance edge, every ordering rule, and
both 2026-08 incident fixtures are testable without a running supervisor.

What this module can and cannot do, deliberately:

- It **reports**. It classifies events, marks sessions degraded, and decides
  stability qualification. It grants no authority and widens no window.
- `entry_cutoff` and `flatten` carry a handler tolerance of 5 seconds, which
  is implementation jitter for the LOG ONLY. Authority tolerance is zero:
  eligibility is a function of the wall clock (`entry_permitted`), never of
  when a handler happened to run. A suspended scheduler can therefore never
  extend the entry window — the failure the Aug 5/6 incidents made concrete.
- A late execution is never retroactively forgiven. §31.2: a later successful
  reconciliation does not make the original flatten timely.

The old validator counted an event as clean when its outcome string omitted
the substring "UNVERIFIED". It reported a flatten 73 minutes past an inviolate
boundary as "nominal, 5/5 events clean". `assess_session` replaces it: an
event is clean only if it is present, in order, acceptable in outcome, AND
within tolerance (§31.3).
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field

from trading_firm.runner.schedule import SessionEvent

# §31.1 ratified execution tolerances. Owner-ratified 2026-08-06; changing a
# value here is a spec change (§31), not an implementation detail.
CHECKPOINT_TOLERANCE_SECONDS = 120.0
PERMISSION_TOLERANCE_SECONDS = 60.0
HARD_HANDLER_TOLERANCE_SECONDS = 5.0

# §31.2: after flatten begins, flat state must be verified within this long of
# the SCHEDULED flatten instant — 11:00:00 -> 11:01:00.
FLAT_VERIFICATION_DEADLINE_SECONDS = 60.0


class BoundaryClass(enum.StrEnum):
    CHECKPOINT = "checkpoint"
    PERMISSION = "permission"
    HARD = "hard"


class TimingStatus(enum.StrEnum):
    ON_TIME = "on_time"  # within the ratified tolerance
    LATE = "late"  # tolerance exceeded — never clean, never nominal
    MISSED = "missed"  # never executed at all


class FlatState(enum.StrEnum):
    """§31.2. Three states, never collapsed into two.

    `UNVERIFIED` is not "probably flat". The firm never infers a position it
    cannot prove, and never infers flatness it cannot prove.
    """

    VERIFIED_FLAT = "VERIFIED_FLAT"
    VERIFIED_NON_FLAT = "VERIFIED_NON_FLAT"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class BoundaryPolicy:
    event: SessionEvent
    boundary_class: BoundaryClass
    tolerance_seconds: float

    @property
    def is_hard(self) -> bool:
        return self.boundary_class is BoundaryClass.HARD


POLICY: dict[SessionEvent, BoundaryPolicy] = {
    SessionEvent.PRE_STARTUP: BoundaryPolicy(
        SessionEvent.PRE_STARTUP, BoundaryClass.CHECKPOINT, CHECKPOINT_TOLERANCE_SECONDS
    ),
    SessionEvent.BRIEFING: BoundaryPolicy(
        SessionEvent.BRIEFING, BoundaryClass.CHECKPOINT, CHECKPOINT_TOLERANCE_SECONDS
    ),
    SessionEvent.ACTIVATION: BoundaryPolicy(
        SessionEvent.ACTIVATION, BoundaryClass.PERMISSION, PERMISSION_TOLERANCE_SECONDS
    ),
    SessionEvent.ENTRY_CUTOFF: BoundaryPolicy(
        SessionEvent.ENTRY_CUTOFF, BoundaryClass.HARD, HARD_HANDLER_TOLERANCE_SECONDS
    ),
    SessionEvent.FLATTEN: BoundaryPolicy(
        SessionEvent.FLATTEN, BoundaryClass.HARD, HARD_HANDLER_TOLERANCE_SECONDS
    ),
}

REQUIRED_EVENTS: tuple[SessionEvent, ...] = (
    SessionEvent.PRE_STARTUP,
    SessionEvent.BRIEFING,
    SessionEvent.ACTIVATION,
    SessionEvent.ENTRY_CUTOFF,
    SessionEvent.FLATTEN,
)


@dataclass(frozen=True)
class EventTiming:
    """One boundary's scheduled instant, actual instant, and verdict.

    BOTH timestamps are retained (§31.4): neither overwrites the other, so the
    record stays auditable long after the session.
    """

    event: SessionEvent
    scheduled_at: dt.datetime
    actual_at: dt.datetime | None
    lateness_seconds: float
    status: TimingStatus

    @property
    def on_time(self) -> bool:
        return self.status is TimingStatus.ON_TIME


def evaluate(
    event: SessionEvent, scheduled_at: dt.datetime, actual_at: dt.datetime | None
) -> EventTiming:
    """Classify one boundary execution against its ratified tolerance.

    Early execution is impossible for a scheduler that waits for the instant,
    but if it happens it is clamped to zero lateness rather than reported as
    negative — a boundary cannot be "better than on time", and a negative
    number in a report invites the reader to average it against a positive one.
    """
    policy = POLICY[event]
    if actual_at is None:
        return EventTiming(event, scheduled_at, None, float("inf"), TimingStatus.MISSED)
    lateness = max(0.0, (actual_at - scheduled_at).total_seconds())
    status = (
        TimingStatus.ON_TIME if lateness <= policy.tolerance_seconds else TimingStatus.LATE
    )
    return EventTiming(event, scheduled_at, actual_at, lateness, status)


def entry_permitted(now: dt.datetime, entry_cutoff_at: dt.datetime) -> bool:
    """§31.1 authority tolerance is ZERO for entry_cutoff.

    Eligibility is a pure function of the authoritative wall clock and the
    scheduled instant. It does not consult the event record, the handler, or
    whether the scheduler was suspended — which is precisely why a suspended
    scheduler cannot extend the entry window. The 5-second handler tolerance
    lives in `POLICY` and affects the REPORT only.
    """
    return now < entry_cutoff_at


def flat_verification_deadline(flatten_scheduled_at: dt.datetime) -> dt.datetime:
    """§31.2: 11:00:00 -> 11:01:00 Europe/London."""
    return flatten_scheduled_at + dt.timedelta(seconds=FLAT_VERIFICATION_DEADLINE_SECONDS)


class SessionHealth(enum.StrEnum):
    """Did the session EXECUTE correctly? (§31.4 dimension one.)"""

    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"


class Qualification(enum.StrEnum):
    """May the session earn stability credit? (§31.4 dimension two.)

    Deliberately independent of health. A session can execute perfectly on a
    machine whose power readiness could not be proven: calling that DEGRADED
    would be false, and calling it QUALIFYING would let an unprovable machine
    earn credit. Both dimensions are reported, always.
    """

    QUALIFYING = "QUALIFYING"
    NON_QUALIFYING = "NON_QUALIFYING"


@dataclass(frozen=True)
class SessionVerdict:
    """The §31.4 report surface. `nominal` is derived, never assigned."""

    required_event_count: int
    clean_event_count: int
    late_event_count: int
    failed_event_count: int
    max_lateness_seconds: float
    degraded: bool
    qualifying: bool
    flat_state: FlatState
    suspension_detected: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    qualification_reason: str = ""

    @property
    def nominal(self) -> bool:
        """§31.4 prohibits nominal whenever anything below holds. Derived from
        the same facts the report prints, so the headline can never disagree
        with the table under it."""
        return not self.degraded

    @property
    def health(self) -> SessionHealth:
        return SessionHealth.DEGRADED if self.degraded else SessionHealth.NOMINAL

    @property
    def qualification(self) -> Qualification:
        return Qualification.QUALIFYING if self.qualifying else Qualification.NON_QUALIFYING

    def summary(self, session_date: dt.date) -> str:
        """Owner-facing headline carrying BOTH dimensions (§31.4).

        A non-qualifying session must never read as merely "nominal": the
        headline says NOMINAL EXECUTION and then says, on the same line, that
        it is NON-QUALIFYING and why. Concise enough for Telegram, impossible
        to skim as an all-clear.
        """
        if self.degraded:
            head = f"{session_date} SESSION DEGRADED"
        elif not self.qualifying:
            head = (
                f"{session_date} NOMINAL EXECUTION / NON-QUALIFYING"
                f" — {self.qualification_reason or 'qualification withheld'}"
            )
        else:
            head = f"{session_date} nominal, QUALIFYING"
        counts = (
            f": {self.clean_event_count}/{self.required_event_count} events clean"
            f", {self.late_event_count} late, {self.failed_event_count} failed/unverified"
            f", max lateness {self.max_lateness_seconds:.0f}s"
            f", flat state {self.flat_state}"
        )
        tail = ". " + "; ".join(self.reasons) if self.reasons else ""
        return head + counts + tail + "."


def assess_session(
    *,
    timings: dict[SessionEvent, EventTiming],
    flat_state: FlatState,
    suspension_detected: bool = False,
    health_verified: bool = True,
    power_verified: bool = True,
    unacceptable_outcomes: frozenset[SessionEvent] = frozenset(),
) -> SessionVerdict:
    """Decide clean counts, degraded status, and stability qualification (§31.3).

    An event is CLEAN only when all four dimensions pass: present, in the
    required order, acceptable in outcome, and within tolerance. The order
    dimension is structural — `REQUIRED_EVENTS` is the canonical sequence, and
    an actual timestamp out of order fails regardless of its lateness.
    """
    reasons: list[str] = []
    clean = late = failed = 0
    max_lateness = 0.0

    # Order is checked against actual execution times, so a replayed backlog
    # that fires flatten before entry_cutoff cannot score clean.
    executed = [
        (event, timings[event].actual_at)
        for event in REQUIRED_EVENTS
        if event in timings and timings[event].actual_at is not None
    ]
    out_of_order = any(
        executed[i][1] > executed[i + 1][1] for i in range(len(executed) - 1)
    )
    if out_of_order:
        reasons.append("events executed out of order")

    for event in REQUIRED_EVENTS:
        timing = timings.get(event)
        if timing is None or timing.status is TimingStatus.MISSED:
            failed += 1
            reasons.append(f"{event.value} did not execute")
            continue
        if timing.lateness_seconds != float("inf"):
            max_lateness = max(max_lateness, timing.lateness_seconds)
        if event in unacceptable_outcomes:
            failed += 1
            reasons.append(f"{event.value} outcome not acceptable")
            continue
        if timing.status is TimingStatus.LATE:
            late += 1
            policy = POLICY[event]
            label = "HARD BOUNDARY BREACH" if policy.is_hard else "late"
            reasons.append(
                f"{event.value} {label}: {timing.lateness_seconds:.0f}s late "
                f"(tolerance {policy.tolerance_seconds:.0f}s)"
            )
            continue
        if out_of_order:
            failed += 1
            continue
        clean += 1

    if flat_state is FlatState.UNVERIFIED:
        reasons.append("flat state UNVERIFIED")
    elif flat_state is FlatState.VERIFIED_NON_FLAT:
        reasons.append("account NOT flat at the flatten boundary")
    if suspension_detected:
        reasons.append("runtime suspension detected during the session")
    if not health_verified:
        reasons.append("required health checks not verified")
    if not power_verified:
        reasons.append("power/sleep readiness not verified")

    # §31.4: every one of these prohibits "nominal".
    degraded = bool(
        late
        or failed
        or out_of_order
        or flat_state is not FlatState.VERIFIED_FLAT
        or suspension_detected
        or not health_verified
    )
    # §31.3: qualification is stricter still — power readiness is required for
    # the stability gate even when the session itself was otherwise sound.
    qualifying = not degraded and power_verified
    if degraded:
        qualification_reason = "SESSION DEGRADED"
    elif not power_verified:
        # The named case from the owner amendment: sound execution, unprovable
        # machine. Reported as its own reason so it can never read as a
        # execution fault, nor be mistaken for an all-clear.
        qualification_reason = "POWER READINESS UNVERIFIED"
    else:
        qualification_reason = ""

    return SessionVerdict(
        required_event_count=len(REQUIRED_EVENTS),
        clean_event_count=clean,
        late_event_count=late,
        failed_event_count=failed,
        max_lateness_seconds=max_lateness,
        degraded=degraded,
        qualifying=qualifying,
        flat_state=flat_state,
        suspension_detected=suspension_detected,
        reasons=tuple(reasons),
        qualification_reason=qualification_reason,
    )


# --------------------------------------------------------- §31.6 authority latch


class SessionAuthority(enum.StrEnum):
    """Where the session stands in its permission lifecycle (§14 state machine).

    Ordered and MONOTONIC. The rank below is the whole point: authority only
    ever advances, so a prohibition once reached can never be un-reached.
    """

    PRE_SESSION = "pre_session"
    ACTIVE = "active"  # new entries permitted
    MANAGE_ONLY = "manage_only"  # past 10:30 — no new entries, ever again today
    FLATTENING = "flattening"  # past 11:00 — out of ACTIVE, permanently
    RECONCILIATION = "reconciliation"  # §14: verifying the account after flatten
    CLOSED = "closed"
    HALTED = "halted"  # §14: any critical failure. Terminal, and highest rank.


# HALTED outranks everything so that `observe()` can never retreat out of it:
# once halted, no wall-clock reading un-halts the session. CLOSED sits below it
# for the same reason — a session that closed cleanly may still be halted by a
# later critical finding, but a halted session is never quietly closed.
_AUTHORITY_RANK = {
    SessionAuthority.PRE_SESSION: 0,
    SessionAuthority.ACTIVE: 1,
    SessionAuthority.MANAGE_ONLY: 2,
    SessionAuthority.FLATTENING: 3,
    SessionAuthority.RECONCILIATION: 4,
    SessionAuthority.CLOSED: 5,
    SessionAuthority.HALTED: 6,
}


class SessionAuthorityLatch:
    """Irreversible session authority (§31.6).

    The wall clock ESTABLISHES a prohibition; this latch makes it
    IRREVERSIBLE. `entry_permitted(now, cutoff)` is a pure comparison and
    therefore reversible: if wall-clock time moves backward — an NTP
    correction, a manual clock change, a system-time or timezone anomaly — the
    comparison silently answers "permitted" again. A trading prohibition that
    can be undone by a clock adjustment is not a prohibition.

    So the latch records the highest authority state ever observed and refuses
    to retreat below it. Crossing 10:30 ends new-entry authority for the rest
    of that session under every subsequent clock reading. Crossing 11:00 leaves
    ACTIVE permanently: a supervisor that wakes at 12:16 after a clamshell
    sleep cannot replay activation, and cannot re-enter a state that would
    create entry eligibility.

    Comparisons are between timezone-aware instants, so DST transitions are
    absolute-time arithmetic and cannot move a latched boundary.
    """

    def __init__(
        self,
        *,
        activation_at: dt.datetime,
        entry_cutoff_at: dt.datetime,
        flatten_at: dt.datetime,
    ) -> None:
        for name, value in (
            ("activation_at", activation_at),
            ("entry_cutoff_at", entry_cutoff_at),
            ("flatten_at", flatten_at),
        ):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware (§10.3)")
        self._activation_at = activation_at
        self._entry_cutoff_at = entry_cutoff_at
        self._flatten_at = flatten_at
        self._state = SessionAuthority.PRE_SESSION
        self._activated = False
        self.regressions_observed = 0

    def _wall_clock_state(self, now: dt.datetime) -> SessionAuthority:
        """What the clock alone would say — reversible, hence never used raw."""
        if now >= self._flatten_at:
            return SessionAuthority.FLATTENING
        if now >= self._entry_cutoff_at:
            return SessionAuthority.MANAGE_ONLY
        if now >= self._activation_at:
            return SessionAuthority.ACTIVE
        return SessionAuthority.PRE_SESSION

    def observe(self, now: dt.datetime) -> SessionAuthority:
        """Advance the latch to what the clock says, never retreat.

        A backward clock movement is counted rather than silently absorbed:
        `regressions_observed` becomes evidence in the session report, because
        a clock that moved backward mid-session is itself a finding.
        """
        computed = self._wall_clock_state(now)
        if _AUTHORITY_RANK[computed] > _AUTHORITY_RANK[self._state]:
            self._state = computed
        elif _AUTHORITY_RANK[computed] < _AUTHORITY_RANK[self._state]:
            self.regressions_observed += 1
        return self._state

    @property
    def state(self) -> SessionAuthority:
        return self._state

    @property
    def entry_permitted(self) -> bool:
        """New-entry authority. False forever once 10:30 has been observed."""
        return self._state is SessionAuthority.ACTIVE

    @property
    def may_activate(self) -> bool:
        """§31.6: activation cannot be replayed once the session has moved past
        ACTIVE. A wake after 10:30 or 11:00 grants nothing retroactively."""
        return _AUTHORITY_RANK[self._state] <= _AUTHORITY_RANK[SessionAuthority.ACTIVE]

    def mark_activated(self) -> None:
        self._activated = True

    @property
    def activated(self) -> bool:
        return self._activated

    def begin_reconciliation(self) -> SessionAuthority:
        """§14 FLATTENING -> RECONCILIATION. Advances only; never retreats."""
        if _AUTHORITY_RANK[SessionAuthority.RECONCILIATION] > _AUTHORITY_RANK[self._state]:
            self._state = SessionAuthority.RECONCILIATION
        return self._state

    def halt(self) -> SessionAuthority:
        """§14: any critical failure transitions to HALTED. Terminal.

        Deliberately INDEPENDENT of the health dimension. HALTED is a statement
        about what the session may still do; NOMINAL/DEGRADED is a statement
        about how it executed. §31.2 requires an unverified flat state to reach
        the recovery state, and that requirement is about authority, not about
        a report adjective — so the two axes are set separately and neither
        derives from the other.
        """
        self._state = SessionAuthority.HALTED
        return self._state

    @property
    def halted(self) -> bool:
        return self._state is SessionAuthority.HALTED

    def close(self) -> SessionAuthority:
        """Clean end of session. Refuses to downgrade a halted session."""
        if _AUTHORITY_RANK[SessionAuthority.CLOSED] > _AUTHORITY_RANK[self._state]:
            self._state = SessionAuthority.CLOSED
        return self._state
