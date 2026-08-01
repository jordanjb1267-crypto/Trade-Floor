"""London-anchored wakeup schedule for the laptop supervisor (§14, §18, C-2).

The §18 supervisor on macOS is launchd, and launchd's `StartCalendarInterval`
fires in the machine's LOCAL time zone. A Chicago laptop configured to wake at
"02:00" would fire at London 07:00 on the 27 days in 2026 when the two zones'
DST transitions diverge — inside the window the Asian range is computed from.
That is finding C-2, the exact defect v2.0.0's §24 draft reintroduced and
v2.1.0 removed, now waiting to be reintroduced a third time through a plist.

So no wall-clock time appears in any launchd configuration. The plist keeps a
single long-running agent alive; the agent asks THIS module — which computes
from `SessionClock` in Europe/London via zoneinfo — what happens next and when,
and sleeps until then. DST correctness lives in one tested place instead of a
config file that would need editing twice a year.

Pure functions only: given a moment, return the next event. The supervisor
loop owns sleeping, notifying, and failing closed; none of that belongs where
it would make the schedule untestable.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from trading_firm.sessions.clock import SessionClock

LONDON = ZoneInfo("Europe/London")

# London-session FX weekdays. Saturday has no session; Sunday's 21:00 UTC open
# belongs to Monday's session and the supervisor has nothing to do before its
# own PRE_STARTUP anyway.
_TRADING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})


class SessionEvent(enum.StrEnum):
    """The moments the supervisor must be awake for, in session order (§14)."""

    PRE_STARTUP = "pre_startup"  # health checks, data warm-up, §19 health report
    BRIEFING = "briefing"  # features final; context packet built
    ACTIVATION = "activation"  # session ACTIVE; shadow evaluation begins
    ENTRY_CUTOFF = "entry_cutoff"  # MANAGE_ONLY; no new evaluations
    FLATTEN = "flatten"  # inviolate (§14): verify flat, then post-session report


# boundaries() key per event. PRE_STARTUP uses the startup boundary: §14's state
# machine enters STARTUP there, and that is when the §19 session-start health
# report is due.
_BOUNDARY_KEY = {
    SessionEvent.PRE_STARTUP: "startup",
    SessionEvent.BRIEFING: "briefing",
    SessionEvent.ACTIVATION: "activation",
    SessionEvent.ENTRY_CUTOFF: "entry_cutoff",
    SessionEvent.FLATTEN: "flatten",
}


@dataclass(frozen=True)
class ScheduledEvent:
    event: SessionEvent
    at: dt.datetime  # timezone-aware, Europe/London
    session_date: dt.date

    def seconds_until(self, now: dt.datetime) -> float:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware (§10.3)")
        return (self.at - now).total_seconds()


def _events_for(clock: SessionClock, day: dt.date) -> list[ScheduledEvent]:
    boundaries = clock.boundaries(day)
    return [
        ScheduledEvent(event=event, at=boundaries[key], session_date=day)
        for event, key in _BOUNDARY_KEY.items()
    ]


def next_event(clock: SessionClock, now: dt.datetime) -> ScheduledEvent:
    """The next session moment strictly after `now`, skipping weekends.

    Deliberately has no notion of holidays: on a holiday the supervisor wakes,
    runs its health checks, finds no market data or a closed calendar, and
    fails closed with a §19 report — which is the correct behaviour, and
    exercises the fail-closed path on exactly the days it is cheapest to. A
    schedule that silently skipped holidays would leave that path untested
    until a real outage needed it.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (§10.3)")
    moment = now.astimezone(LONDON)
    day = moment.date()
    for _ in range(8):  # bounded: never more than a weekend + holiday cluster away
        if day.weekday() in _TRADING_WEEKDAYS:
            for scheduled in _events_for(clock, day):
                if scheduled.at > moment:
                    return scheduled
        day += dt.timedelta(days=1)
    raise RuntimeError(
        "no session event found within eight days: the session configuration "
        "no longer describes a weekly cycle (§14)"
    )
