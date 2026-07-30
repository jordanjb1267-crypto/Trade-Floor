"""Market-data normalization tests (§8.1: normalize, detect stale/missing data)."""

import datetime as dt
from decimal import Decimal

import pytest

from trading_firm.market_data import from_fmp_rows, from_oanda_candles

UTC = dt.UTC


def fmp_row(date: str, o: str, h: str, low: str, c: str, v: int = 100) -> dict:
    return {"date": date, "open": o, "high": h, "low": low, "close": c, "volume": v}


class TestFmpNormalization:
    def test_naive_timestamps_pinned_to_declared_zone(self) -> None:
        series = from_fmp_rows(
            [fmp_row("2026-07-28 17:00:00", "1.33", "1.34", "1.32", "1.335")],
            instrument="GBP_USD",
            granularity_minutes=15,
            source_tz="America/New_York",
        )
        # 17:00 New York in July (EDT, UTC-4) is 21:00 UTC.
        assert series.bars[0].ts == dt.datetime(2026, 7, 28, 21, 0, tzinfo=UTC)
        assert series.bars[0].open == Decimal("1.33")

    def test_aware_timestamp_rejected(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            from_fmp_rows(
                [fmp_row("2026-07-28 17:00:00+00:00", "1.33", "1.34", "1.32", "1.335")],
                instrument="GBP_USD",
                granularity_minutes=15,
                source_tz="America/New_York",
            )

    def test_duplicates_dropped_with_event(self) -> None:
        rows = [
            fmp_row("2026-07-28 17:00:00", "1.33", "1.34", "1.32", "1.335"),
            fmp_row("2026-07-28 17:00:00", "9.99", "9.99", "9.99", "9.99"),
        ]
        series = from_fmp_rows(
            rows, instrument="GBP_USD", granularity_minutes=15, source_tz="UTC"
        )
        assert len(series.bars) == 1
        assert any("duplicate" in event for event in series.quality_events)

    def test_intraday_gap_flagged(self) -> None:
        rows = [
            fmp_row("2026-07-28 17:00:00", "1.33", "1.34", "1.32", "1.335"),
            fmp_row("2026-07-28 17:45:00", "1.33", "1.34", "1.32", "1.335"),  # skipped 17:15/17:30
        ]
        series = from_fmp_rows(
            rows, instrument="GBP_USD", granularity_minutes=15, source_tz="UTC"
        )
        assert any("gap" in event for event in series.quality_events)

    def test_weekend_gap_not_flagged(self) -> None:
        rows = [
            fmp_row("2026-07-24 16:45:00", "1.33", "1.34", "1.32", "1.335"),
            fmp_row("2026-07-26 17:00:00", "1.33", "1.34", "1.32", "1.335"),
        ]
        series = from_fmp_rows(
            rows, instrument="GBP_USD", granularity_minutes=15, source_tz="UTC"
        )
        assert not any("gap" in event for event in series.quality_events)

    def test_malformed_ohlc_dropped_with_event(self) -> None:
        rows = [fmp_row("2026-07-28 17:00:00", "1.33", "1.32", "1.31", "1.335")]  # high < close
        series = from_fmp_rows(
            rows, instrument="GBP_USD", granularity_minutes=15, source_tz="UTC"
        )
        assert len(series.bars) == 0
        assert any("malformed" in event for event in series.quality_events)


class TestOandaNormalization:
    def test_nanosecond_rfc3339_parsed(self) -> None:
        candles = [
            {
                "time": "2026-07-29T08:00:00.000000000Z",
                "mid": {"o": "1.3298", "h": "1.3305", "l": "1.3290", "c": "1.3300"},
                "volume": 120,
                "complete": True,
            }
        ]
        series = from_oanda_candles(candles, instrument="GBP_USD", granularity_minutes=15)
        assert series.bars[0].ts == dt.datetime(2026, 7, 29, 8, 0, tzinfo=UTC)

    def test_incomplete_candle_excluded(self) -> None:
        candles = [
            {
                "time": "2026-07-29T08:00:00Z",
                "mid": {"o": "1.3298", "h": "1.3305", "l": "1.3290", "c": "1.3300"},
                "complete": False,
            }
        ]
        series = from_oanda_candles(candles, instrument="GBP_USD", granularity_minutes=15)
        assert len(series.bars) == 0


class TestBetween:
    def test_half_open_interval_and_awareness(self) -> None:
        rows = [
            fmp_row("2026-07-29 08:00:00", "1.33", "1.34", "1.32", "1.335"),
            fmp_row("2026-07-29 08:15:00", "1.33", "1.34", "1.32", "1.335"),
        ]
        series = from_fmp_rows(
            rows, instrument="GBP_USD", granularity_minutes=15, source_tz="UTC"
        )
        start = dt.datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
        end = dt.datetime(2026, 7, 29, 8, 15, tzinfo=UTC)
        assert len(series.between(start, end)) == 1  # end excluded
        with pytest.raises(ValueError):
            series.between(start.replace(tzinfo=None), end)
