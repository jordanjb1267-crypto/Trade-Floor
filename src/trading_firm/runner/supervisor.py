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
from trading_firm.runner.schedule import ScheduledEvent, SessionEvent, next_event
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

    def note(self, event: SessionEvent, at: dt.datetime, outcome: str) -> None:
        self.events.append(
            {"event": event.value, "at": at.isoformat(), "outcome": outcome}
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
    ) -> None:
        self._clock = clock
        self._probe = probe
        self._notify = notify
        self._report_dir = report_dir
        self._now = now
        self._sleep = sleep
        self._heartbeat = heartbeat
        self._sweep = sweep
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

    # ------------------------------------------------------------------ events

    def handle(self, scheduled: ScheduledEvent) -> None:
        """Run one session event. Public so tests drive the lifecycle directly."""
        if self._record is None or self._record.session_date != scheduled.session_date:
            self._record = SessionRecord(session_date=scheduled.session_date)
        record = self._record
        at = self._now()

        if scheduled.event is SessionEvent.PRE_STARTUP:
            health = self._checked_probe()
            record.note(scheduled.event, at, health.summary())
            if health.healthy:
                self._notify(
                    NotificationKind.SESSION_START_HEALTH,
                    f"{scheduled.session_date} session starting. {health.summary()}",
                )
            else:
                record.degraded = True
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
            record.note(scheduled.event, at, outcome)
            if self._sweep is not None and not record.degraded:
                try:
                    record.note(scheduled.event, at, f"sweep: {self._sweep(scheduled)}")
                except Exception as error:  # noqa: BLE001 — observe-only (§30.2)
                    record.note(
                        scheduled.event, at,
                        f"sweep FAILED (contained): {type(error).__name__}: {error}",
                    )

        elif scheduled.event is SessionEvent.ENTRY_CUTOFF:
            record.note(scheduled.event, at, "manage-only from here (§14)")

        elif scheduled.event is SessionEvent.FLATTEN:
            # Runs on degraded days too: "could not verify flat" must reach the
            # owner, not be skipped along with everything else (§14, F-5).
            health = self._checked_probe()
            if not health.broker_reachable:
                record.note(scheduled.event, at, f"UNVERIFIED: {health.summary()}")
                self._notify(
                    NotificationKind.DATA_OR_BROKER_FAILURE,
                    f"{scheduled.session_date} 11:00 flatten boundary: could NOT "
                    f"verify the account is flat — {health.summary()}. Check the "
                    f"broker directly (§14, F-5).",
                )
            elif not health.account_flat:
                record.note(scheduled.event, at, f"NOT FLAT: {health.summary()}")
                self._notify(
                    NotificationKind.RISK_HALT,
                    f"{scheduled.session_date} 11:00 flatten boundary: account is "
                    f"NOT flat ({health.open_position_count} open). The flatten "
                    f"boundary is inviolate — intervene now (§14, F-5).",
                )
            else:
                record.note(scheduled.event, at, "verified flat")
            self._write_report(record)
            self._notify(
                NotificationKind.DAILY_SESSION_REPORT,
                self._daily_summary(record),
            )
            self._record = None

    # ------------------------------------------------------------------ report

    def _write_report(self, record: SessionRecord) -> Path:
        self._report_dir.mkdir(parents=True, exist_ok=True)
        path = self._report_dir / f"{record.session_date}-session.json"
        payload = {
            "session_date": record.session_date.isoformat(),
            "degraded": record.degraded,
            "events": record.events,
            "environment": "shadow",
            "orders_placed": 0,  # structurally: this process cannot place any
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return path

    @staticmethod
    def _daily_summary(record: SessionRecord) -> str:
        status = "DEGRADED (failed closed)" if record.degraded else "nominal"
        kept = sum(1 for e in record.events if "UNVERIFIED" not in e["outcome"])
        return (
            f"{record.session_date} shadow session complete: {status}, "
            f"{kept}/{len(record.events)} events clean. Report written."
        )

    # ------------------------------------------------------------------ loop

    def run_forever(self) -> None:
        """Wake at each event until stopped. Sleeps in bounded slices and
        recomputes after every slice, so clock steps and DST transitions are
        absorbed within five minutes instead of compounding."""
        while not self.stopping:
            scheduled = next_event(self._clock, self._now())
            self._beat("waiting")
            while not self.stopping:
                remaining = scheduled.seconds_until(self._now())
                if remaining <= 0:
                    break
                self._sleep(min(remaining, MAX_SLEEP_SLICE_SECONDS))
                # One beat per slice, so a stalled loop is visible within a
                # slice rather than at the next session boundary hours away.
                self._beat("waiting")
            if not self.stopping:
                self.handle(scheduled)
                self._beat("handled")
