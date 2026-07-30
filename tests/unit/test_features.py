"""Feature engine tests (§8.1: deterministic, versioned, no future leakage)."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.features import FEATURES_VERSION, session_features
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.sessions import SessionClock

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 7, 29)


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def bar(hhmm: str, o: str, h: str, low: str, c: str, day: dt.date = DAY) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def series(*bars: Bar) -> BarSeries:
    return BarSeries(instrument="GBP_USD", granularity_minutes=15, bars=tuple(bars))


ASIAN_BARS = (
    bar("00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
    bar("02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
    bar("04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
    bar("06:45", "1.3320", "1.3330", "1.3312", "1.3326"),
    bar("07:15", "1.3326", "1.3332", "1.3318", "1.3328"),
)


class TestSessionFeatures:
    def test_known_range_exact(self, clock: SessionClock) -> None:
        features = session_features(series(*ASIAN_BARS), DAY, clock)
        assert features is not None
        assert features.feature_version == FEATURES_VERSION
        assert features.asian_high == Decimal("1.3340")
        assert features.asian_low == Decimal("1.3300")
        assert features.asian_width_pips == Decimal("40")
        assert features.asian_bar_count == 5

    def test_no_future_leakage_at_boundary(self, clock: SessionClock) -> None:
        # A bar opening exactly AT the 07:30 boundary must not contribute (§8.1).
        poison = bar("07:30", "1.3330", "1.9000", "1.3330", "1.8000")
        features = session_features(series(*ASIAN_BARS, poison), DAY, clock)
        assert features is not None
        assert features.asian_high == Decimal("1.3340")
        assert features.computed_at == clock.boundaries(DAY)["asian_range_final"]

    def test_pre_london_window_and_compression(self, clock: SessionClock) -> None:
        features = session_features(series(*ASIAN_BARS), DAY, clock)
        assert features is not None
        # Pre-London hour [06:30, 07:30): bars 06:45 and 07:15 ->
        # high 1.3332, low 1.3312 -> 20 pips; compression = 20/40 = 0.50.
        assert features.pre_london_range_pips == Decimal("20")
        assert features.compression_ratio == Decimal("0.50")

    def test_missing_data_fails_closed(self, clock: SessionClock) -> None:
        assert session_features(series(), DAY, clock) is None
