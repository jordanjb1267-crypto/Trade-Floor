"""Scheduled-event windows over the normalized calendar (§30.3.F).

Pure filters: which normalized events are upcoming within a horizon, and
which have passed their scheduled time without a recorded release — the
"calendar reports wrong or revised time" failure mode surfaces as an
overdue event, never as silence.
"""

from __future__ import annotations

import datetime as dt

from trading_firm.surveillance.schemas import UpcomingEvent


def upcoming(
    events: list[UpcomingEvent], now: dt.datetime, horizon: dt.timedelta
) -> list[UpcomingEvent]:
    if now.tzinfo is None:
        raise ValueError("aware datetimes required (§30.4, C-2)")
    return [e for e in events if now <= e.scheduled_utc <= now + horizon]


def overdue(
    events: list[UpcomingEvent],
    released_event_ids: frozenset[str],
    now: dt.datetime,
    grace: dt.timedelta = dt.timedelta(minutes=10),
) -> list[UpcomingEvent]:
    """Scheduled, past due beyond the grace window, and no release recorded —
    either the release is late, the calendar time was wrong, or the source
    is quiet. All three are uncertainty; none is 'no event' (§30.8)."""
    if now.tzinfo is None:
        raise ValueError("aware datetimes required (§30.4, C-2)")
    return [
        e
        for e in events
        if e.event_id not in released_event_ids and e.scheduled_utc + grace < now
    ]
