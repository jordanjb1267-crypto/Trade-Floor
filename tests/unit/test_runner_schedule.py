"""Supervisor schedule (§14, §18, C-2): London-anchored, DST-proof, weekend-aware.

The reason this module exists at all is that launchd fires in local time. These
tests therefore lean on the 2026 DST divergence days — the 27 days a
Chicago-local schedule would be wrong — because that is the failure the design
is meant to make impossible.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.runner.schedule import LONDON, ScheduledEvent, SessionEvent, next_event
from trading_firm.sessions import SessionClock

CHICAGO = ZoneInfo("America/Chicago")
UTC = dt.UTC


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def at_london(day: dt.date, hhmm: str) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=LONDON)


class TestOrdinaryDays:
    def test_the_five_events_fire_in_session_order(self, clock) -> None:
        moment = at_london(dt.date(2026, 7, 29), "00:05")  # Wednesday
        seen = []
        for _ in range(5):
            scheduled = next_event(clock, moment)
            seen.append(scheduled.event)
            moment = scheduled.at
        assert seen == [
            SessionEvent.PRE_STARTUP,
            SessionEvent.BRIEFING,
            SessionEvent.ACTIVATION,
            SessionEvent.ENTRY_CUTOFF,
            SessionEvent.FLATTEN,
        ]

    def test_activation_is_0800_london(self, clock) -> None:
        scheduled = next_event(clock, at_london(dt.date(2026, 7, 29), "07:59"))
        assert scheduled.event is SessionEvent.ACTIVATION
        assert scheduled.at.strftime("%H:%M") == "08:00"
        assert scheduled.at.tzinfo is LONDON

    def test_after_flatten_the_next_event_is_tomorrows_pre_startup(self, clock) -> None:
        scheduled = next_event(clock, at_london(dt.date(2026, 7, 29), "11:01"))
        assert scheduled.event is SessionEvent.PRE_STARTUP
        assert scheduled.session_date == dt.date(2026, 7, 30)

    def test_an_event_exactly_now_is_not_returned_again(self, clock) -> None:
        # A supervisor waking AT the boundary must be handed the next one, or
        # it loops on the same event forever.
        activation = next_event(clock, at_london(dt.date(2026, 7, 29), "07:59"))
        assert activation.event is SessionEvent.ACTIVATION
        following = next_event(clock, activation.at)
        assert following.event is SessionEvent.ENTRY_CUTOFF


class TestWeekends:
    def test_friday_flatten_rolls_to_monday(self, clock) -> None:
        scheduled = next_event(clock, at_london(dt.date(2026, 7, 31), "11:01"))  # Friday
        assert scheduled.event is SessionEvent.PRE_STARTUP
        assert scheduled.session_date == dt.date(2026, 8, 3)  # Monday
        assert scheduled.session_date.weekday() == 0

    def test_saturday_and_sunday_produce_no_events(self, clock) -> None:
        for day in (dt.date(2026, 8, 1), dt.date(2026, 8, 2)):
            scheduled = next_event(clock, at_london(day, "09:00"))
            assert scheduled.session_date == dt.date(2026, 8, 3)


class TestDstDivergence:
    """C-2, quantified: a Chicago-local 02:00 schedule is wrong on exactly the
    days these assertions cover."""

    @staticmethod
    def _divergence_days() -> list[dt.date]:
        days = []
        day = dt.date(2026, 1, 1)
        while day <= dt.date(2026, 12, 31):
            chi = dt.datetime.combine(day, dt.time(2, 0), tzinfo=CHICAGO)
            if chi.astimezone(LONDON).strftime("%H:%M") != "08:00":
                days.append(day)
            day += dt.timedelta(days=1)
        return days

    def test_the_hazard_is_the_documented_size(self) -> None:
        assert len(self._divergence_days()) == 27

    def test_activation_holds_at_0800_london_on_every_divergence_day(self, clock) -> None:
        for day in self._divergence_days():
            if day.weekday() not in (0, 1, 2, 3, 4):
                continue
            scheduled = next_event(clock, at_london(day, "07:59"))
            assert scheduled.event is SessionEvent.ACTIVATION
            assert scheduled.at.strftime("%H:%M") == "08:00"
            # The whole point: on these days the Chicago rendering is 03:00,
            # so a plist carrying "02:00" local would have fired an hour early.
            assert scheduled.at.astimezone(CHICAGO).strftime("%H:%M") == "03:00"

    def test_a_supervisor_sleeping_across_the_spring_transition_wakes_correctly(
        self, clock
    ) -> None:
        # UK springs forward 2026-03-29 (Sunday). Friday 27th's flatten -> the
        # next event is Monday 30th PRE_STARTUP, computed across the transition.
        scheduled = next_event(clock, at_london(dt.date(2026, 3, 27), "11:01"))
        assert scheduled.session_date == dt.date(2026, 3, 30)
        assert scheduled.event is SessionEvent.PRE_STARTUP
        # Wall clock holds; the UTC rendering shifts with the zone, which is
        # what "London-anchored" means (§14).
        assert scheduled.at.utcoffset() == dt.timedelta(hours=1)  # BST


class TestContracts:
    def test_naive_now_is_rejected(self, clock) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            next_event(clock, dt.datetime(2026, 7, 29, 9, 0))

    def test_seconds_until_rejects_naive_now(self, clock) -> None:
        scheduled = next_event(clock, at_london(dt.date(2026, 7, 29), "07:00"))
        with pytest.raises(ValueError, match="timezone-aware"):
            scheduled.seconds_until(dt.datetime(2026, 7, 29, 7, 30))

    def test_input_timezone_does_not_matter(self, clock) -> None:
        # The same instant expressed in UTC and Chicago yields the same event.
        instant_utc = dt.datetime(2026, 7, 29, 6, 30, tzinfo=UTC)
        from_utc = next_event(clock, instant_utc)
        from_chicago = next_event(clock, instant_utc.astimezone(CHICAGO))
        assert from_utc == from_chicago

    def test_events_carry_their_session_date(self, clock) -> None:
        scheduled = next_event(clock, at_london(dt.date(2026, 7, 29), "07:59"))
        assert isinstance(scheduled, ScheduledEvent)
        assert scheduled.session_date == dt.date(2026, 7, 29)
