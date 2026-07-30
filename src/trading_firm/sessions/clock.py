"""Session clock (§8.1, §14): all boundaries anchored in Europe/London.

Never a fixed UTC offset (R: C-2). America/Chicago is display-only.
Rollover: nothing may hold or adjust positions through 21:00 UTC (F-5).
"""

from __future__ import annotations

import datetime as dt
import enum
from zoneinfo import ZoneInfo

from trading_firm.config import SessionSection

LONDON = ZoneInfo("Europe/London")
UTC = dt.UTC

ROLLOVER_UTC_TIME = dt.time(21, 0)
ROLLOVER_BLACKOUT_BEFORE = dt.timedelta(minutes=30)
ROLLOVER_BLACKOUT_AFTER = dt.timedelta(minutes=45)  # F-5: spreads still elevated +25 min


class SessionWindow(enum.Enum):
    """Time-derived windows of the §14 state machine (event states live in the runtime)."""

    PRE_STARTUP = "PRE_STARTUP"
    STARTUP = "STARTUP"
    BRIEFING = "BRIEFING"
    ACTIVE = "ACTIVE"
    MANAGE_ONLY = "MANAGE_ONLY"
    CLOSED = "CLOSED"


def _require_aware(moment: dt.datetime) -> dt.datetime:
    if moment.tzinfo is None:
        raise ValueError("naive datetimes are forbidden (§10.3: timezone-aware only)")
    return moment


class SessionClock:
    """Derives session boundaries for any date from the London-anchored config."""

    def __init__(self, session: SessionSection):
        self._times = {
            "startup": dt.time.fromisoformat(session.startup_london),
            "asian_range_final": dt.time.fromisoformat(session.asian_range_final_london),
            "briefing": dt.time.fromisoformat(session.briefing_london),
            "activation": dt.time.fromisoformat(session.activation_london),
            "entry_cutoff": dt.time.fromisoformat(session.entry_cutoff_london),
            "flatten": dt.time.fromisoformat(session.flatten_london),
        }
        self.display_zone = ZoneInfo(session.display_timezone)

    def boundaries(self, day: dt.date) -> dict[str, dt.datetime]:
        """Aware Europe/London datetimes for each boundary on the given London date."""
        return {
            name: dt.datetime.combine(day, time, tzinfo=LONDON)
            for name, time in self._times.items()
        }

    def window(self, moment: dt.datetime) -> SessionWindow:
        moment = _require_aware(moment).astimezone(LONDON)
        b = self.boundaries(moment.date())
        if moment < b["startup"]:
            return SessionWindow.PRE_STARTUP
        if moment < b["briefing"]:
            return SessionWindow.STARTUP
        if moment < b["activation"]:
            return SessionWindow.BRIEFING
        if moment < b["entry_cutoff"]:
            return SessionWindow.ACTIVE
        if moment < b["flatten"]:
            return SessionWindow.MANAGE_ONLY
        return SessionWindow.CLOSED

    def entries_allowed(self, moment: dt.datetime) -> bool:
        """§14: new entries only inside [activation, entry_cutoff)."""
        return self.window(moment) is SessionWindow.ACTIVE

    def must_be_flat(self, moment: dt.datetime) -> bool:
        """§14: at/after the flatten boundary no position may exist. Inviolate (F-5)."""
        return self.window(moment) is SessionWindow.CLOSED

    @staticmethod
    def week_key(moment: dt.datetime) -> tuple[int, int]:
        """ISO (year, week) evaluated in Europe/London (§3.4, D-6)."""
        local = _require_aware(moment).astimezone(LONDON)
        iso = local.isocalendar()
        return (iso.year, iso.week)

    @staticmethod
    def in_rollover_blackout(moment: dt.datetime) -> bool:
        """True inside the 21:00 UTC rollover blackout window (F-5)."""
        moment = _require_aware(moment).astimezone(UTC)
        rollover = dt.datetime.combine(moment.date(), ROLLOVER_UTC_TIME, tzinfo=UTC)
        for candidate in (rollover - dt.timedelta(days=1), rollover):
            if (
                candidate - ROLLOVER_BLACKOUT_BEFORE
                <= moment
                < candidate + ROLLOVER_BLACKOUT_AFTER
            ):
                return True
        return False

    def display(self, moment: dt.datetime) -> dt.datetime:
        """Owner-facing display conversion only (§14): never used for decisions."""
        return _require_aware(moment).astimezone(self.display_zone)
