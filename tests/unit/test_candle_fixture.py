"""Fixture assembly for OANDA candles (candle_fixture) — no network."""

import datetime as dt
from decimal import Decimal

import pytest

from trading_firm.market_data.candle_fixture import build_fixture, chunk_ranges

UTC = dt.UTC


def candle(time: str, o: str, h: str, low: str, c: str, *, complete: bool = True) -> dict:
    def block(shift: str) -> dict:
        delta = Decimal(shift)
        return {
            "o": str(Decimal(o) + delta),
            "h": str(Decimal(h) + delta),
            "l": str(Decimal(low) + delta),
            "c": str(Decimal(c) + delta),
        }

    return {
        "time": time,
        "complete": complete,
        "volume": 100,
        "mid": block("0"),
        "ask": block("0.0001"),  # 2-pip synthetic spread around mid
        "bid": block("-0.0001"),
    }


class TestChunkRanges:
    def test_splits_inclusive_dates_into_utc_windows(self) -> None:
        windows = chunk_ranges(
            dt.date(2026, 7, 1), dt.date(2026, 7, 25), days_per_request=10
        )
        assert [(w[0].date(), w[1].date()) for w in windows] == [
            (dt.date(2026, 7, 1), dt.date(2026, 7, 11)),
            (dt.date(2026, 7, 11), dt.date(2026, 7, 21)),
            (dt.date(2026, 7, 21), dt.date(2026, 7, 26)),  # end date inclusive
        ]
        assert all(w[0].tzinfo is UTC and w[1].tzinfo is UTC for w in windows)

    def test_single_day(self) -> None:
        (window,) = chunk_ranges(
            dt.date(2026, 7, 1), dt.date(2026, 7, 1), days_per_request=10
        )
        assert window[1] - window[0] == dt.timedelta(days=1)

    def test_rejects_reversed_range(self) -> None:
        with pytest.raises(ValueError):
            chunk_ranges(dt.date(2026, 7, 2), dt.date(2026, 7, 1), days_per_request=10)


class TestBuildFixture:
    FETCHED = dt.datetime(2026, 7, 30, 12, 0, tzinfo=UTC)

    def test_dedupes_sorts_and_drops_incomplete(self) -> None:
        candles = [
            candle("2026-07-01T08:05:00.000000000Z", "1.33", "1.34", "1.32", "1.335"),
            candle("2026-07-01T08:00:00.000000000Z", "1.32", "1.33", "1.31", "1.33"),
            candle("2026-07-01T08:00:00.000000000Z", "1.32", "1.33", "1.31", "1.33"),
            candle(
                "2026-07-01T08:10:00.000000000Z", "1.335", "1.34", "1.33", "1.34",
                complete=False,
            ),
        ]
        fixture, series = build_fixture(
            candles,
            instrument="GBP_USD",
            granularity_minutes=5,
            host="api-fxpractice.oanda.com",
            fetched_at=self.FETCHED,
        )
        assert fixture["meta"]["candle_count"] == 2  # dupe and incomplete dropped
        assert len(series.bars) == 2
        times = [c["time"] for c in fixture["candles"]]
        assert times == sorted(times)

    def test_preserves_raw_bid_ask_blocks(self) -> None:
        fixture, _ = build_fixture(
            [candle("2026-07-01T08:00:00.000000000Z", "1.33", "1.34", "1.32", "1.335")],
            instrument="GBP_USD",
            granularity_minutes=5,
            host="api-fxpractice.oanda.com",
            fetched_at=self.FETCHED,
        )
        raw = fixture["candles"][0]
        spread = Decimal(raw["ask"]["c"]) - Decimal(raw["bid"]["c"])
        assert spread == Decimal("0.0002")  # bid/ask survive for spread research

    def test_quality_events_surface_in_meta(self) -> None:
        fixture, _ = build_fixture(
            [
                candle("2026-07-01T08:00:00.000000000Z", "1.33", "1.34", "1.32", "1.335"),
                # 15-minute hole in an M5 series -> gap event from _assemble
                candle("2026-07-01T08:20:00.000000000Z", "1.335", "1.34", "1.33", "1.34"),
            ],
            instrument="GBP_USD",
            granularity_minutes=5,
            host="api-fxpractice.oanda.com",
            fetched_at=self.FETCHED,
        )
        assert any("gap" in event for event in fixture["meta"]["quality_events"])

    def test_rejects_naive_fetched_at(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            build_fixture(
                [],
                instrument="GBP_USD",
                granularity_minutes=5,
                host="api-fxpractice.oanda.com",
                fetched_at=dt.datetime(2026, 7, 30, 12, 0),
            )
