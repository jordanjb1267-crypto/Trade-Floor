"""Event blackout windows (§30.4 macro component, §30.14 precondition input).

A blackout is active inside [scheduled - before, scheduled + after] of any
high-importance event whose currency touches the instrument. Pure function
of the normalized calendar — the existing firm-level calendar fail-closed
behavior (`reject_unknown_news_state`) is untouched; this only makes the
window computation reusable by the Market State builder.
"""

from __future__ import annotations

import datetime as dt

from trading_firm.surveillance.schemas import UpcomingEvent

DEFAULT_BEFORE = dt.timedelta(minutes=30)
DEFAULT_AFTER = dt.timedelta(minutes=15)


def instrument_currencies(instrument_id: str) -> frozenset[str]:
    return frozenset(instrument_id.split("_"))


def blackout_active(
    events: list[UpcomingEvent],
    instrument_id: str,
    at: dt.datetime,
    before: dt.timedelta = DEFAULT_BEFORE,
    after: dt.timedelta = DEFAULT_AFTER,
) -> bool:
    if at.tzinfo is None:
        raise ValueError("blackout evaluation requires aware datetimes (§30.4, C-2)")
    currencies = instrument_currencies(instrument_id)
    for event in events:
        if event.importance != "high" or event.currency not in currencies:
            continue
        if event.scheduled_utc - before <= at <= event.scheduled_utc + after:
            return True
    return False
