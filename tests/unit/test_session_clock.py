"""Session clock tests (§21 'DST logic'; §14; F-5 rollover blackout)."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.sessions import SessionClock, SessionWindow

LONDON = ZoneInfo("Europe/London")
CHICAGO = ZoneInfo("America/Chicago")
UTC = dt.UTC


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def at_london(day: dt.date, hhmm: str) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=LONDON)


class TestDstAnchoring:
    """C-2: activation is 08:00 Europe/London on every date, including divergence weeks."""

    def test_aligned_period_maps_to_2am_chicago(self, clock: SessionClock) -> None:
        activation = clock.boundaries(dt.date(2026, 7, 29))["activation"]
        assert activation.astimezone(UTC).hour == 7  # BST = UTC+1
        assert activation.astimezone(CHICAGO).hour == 2

    def test_march_divergence_maps_to_3am_chicago(self, clock: SessionClock) -> None:
        # 2026-03-15: US already on CDT, UK still on GMT (divergence window Mar 9-28).
        activation = clock.boundaries(dt.date(2026, 3, 15))["activation"]
        assert activation.hour == 8 and activation.tzinfo is LONDON
        assert activation.astimezone(UTC).hour == 8  # GMT = UTC
        assert activation.astimezone(CHICAGO).hour == 3

    def test_october_divergence_maps_to_3am_chicago(self, clock: SessionClock) -> None:
        # 2026-10-28: UK back on GMT (Oct 25), US still on CDT (until Nov 1).
        activation = clock.boundaries(dt.date(2026, 10, 28))["activation"]
        assert activation.astimezone(CHICAGO).hour == 3


class TestWindows:
    def test_transitions(self, clock: SessionClock) -> None:
        day = dt.date(2026, 7, 29)
        cases = {
            "06:00": SessionWindow.PRE_STARTUP,
            "07:20": SessionWindow.STARTUP,
            "07:45": SessionWindow.BRIEFING,
            "08:00": SessionWindow.ACTIVE,
            "10:29": SessionWindow.ACTIVE,
            "10:30": SessionWindow.MANAGE_ONLY,
            "11:00": SessionWindow.CLOSED,
        }
        for hhmm, expected in cases.items():
            assert clock.window(at_london(day, hhmm)) is expected, hhmm

    def test_entries_allowed_only_in_active(self, clock: SessionClock) -> None:
        day = dt.date(2026, 7, 29)
        assert clock.entries_allowed(at_london(day, "08:00"))
        assert not clock.entries_allowed(at_london(day, "07:59"))
        assert not clock.entries_allowed(at_london(day, "10:30"))

    def test_flatten_boundary_inviolate(self, clock: SessionClock) -> None:
        day = dt.date(2026, 7, 29)
        assert clock.must_be_flat(at_london(day, "11:00"))
        assert not clock.must_be_flat(at_london(day, "10:59"))

    def test_naive_datetime_rejected(self, clock: SessionClock) -> None:
        with pytest.raises(ValueError):
            clock.window(dt.datetime(2026, 7, 29, 9, 0))


class TestWeekKey:
    def test_iso_week_boundary_in_london_terms(self, clock: SessionClock) -> None:
        # 2026-08-02 23:30 UTC is already Monday 00:30 in London (BST):
        # the weekly limit resets on London's Monday, not UTC's (D-6).
        sunday_utc = dt.datetime(2026, 8, 2, 20, 0, tzinfo=UTC)
        late_sunday_utc = dt.datetime(2026, 8, 2, 23, 30, tzinfo=UTC)
        assert clock.week_key(sunday_utc) == (2026, 31)
        assert clock.week_key(late_sunday_utc) == (2026, 32)


class TestRolloverBlackout:
    """F-5: ~10x spread, near-zero depth around 21:00 UTC."""

    @pytest.mark.parametrize(
        "hhmm,expected",
        [("20:25", False), ("20:30", True), ("21:00", True), ("21:10", True),
         ("21:44", True), ("21:45", False), ("22:00", False)],
    )
    def test_window(self, clock: SessionClock, hhmm: str, expected: bool) -> None:
        moment = dt.datetime.combine(
            dt.date(2026, 7, 29), dt.time.fromisoformat(hhmm), tzinfo=UTC
        )
        assert clock.in_rollover_blackout(moment) is expected
