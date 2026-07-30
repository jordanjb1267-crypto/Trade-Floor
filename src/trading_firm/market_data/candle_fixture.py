"""Research-fixture assembly for OANDA v20 candles (§8.1, §12.1).

Pure functions only — no network. The CLI wrapper is
scripts/fetch_oanda_candles.py; keeping the logic here lets the unit suite
exercise it against canned payloads.

Fixtures preserve the raw bid/ask/mid candles verbatim (traceability) and
carry a meta block with fetch provenance plus the quality events the
normalization pass raised. Timestamps in OANDA candles are RFC3339 UTC —
no timezone pinning question arises (unlike FMP, D-7 caveat).
"""

from __future__ import annotations

import datetime as dt

from trading_firm.market_data.bars import BarSeries, from_oanda_candles

UTC = dt.UTC


def chunk_ranges(
    start: dt.date, end: dt.date, *, days_per_request: int
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Split [start, end] (inclusive dates) into UTC from/to request windows.

    M5 yields 288 candles/day; OANDA caps a request at 5000 candles, so
    days_per_request must keep each window under that (the CLI uses 10).
    """
    if end < start:
        raise ValueError("end date before start date")
    if days_per_request < 1:
        raise ValueError("days_per_request must be >= 1")
    windows: list[tuple[dt.datetime, dt.datetime]] = []
    cursor = start
    final = end + dt.timedelta(days=1)  # exclusive upper bound
    while cursor < final:
        upper = min(cursor + dt.timedelta(days=days_per_request), final)
        windows.append(
            (
                dt.datetime.combine(cursor, dt.time.min, tzinfo=UTC),
                dt.datetime.combine(upper, dt.time.min, tzinfo=UTC),
            )
        )
        cursor = upper
    return windows


def build_fixture(
    candles: list[dict],
    *,
    instrument: str,
    granularity_minutes: int,
    host: str,
    fetched_at: dt.datetime,
) -> tuple[dict, BarSeries]:
    """Dedupe/sort raw candles, validate via the normalization pass, and
    return (fixture dict ready for JSON, normalized BarSeries).

    Incomplete candles are dropped (§8.1: they never enter the record).
    Raw bid/ask/mid blocks are preserved verbatim so replay can later use
    measured spreads instead of the 2-pip assumption.
    """
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware (§10.3)")
    by_time: dict[str, dict] = {}
    for candle in candles:
        if not candle.get("complete", True):
            continue
        by_time[str(candle["time"])] = candle
    ordered = [by_time[key] for key in sorted(by_time)]

    series = from_oanda_candles(
        ordered, instrument=instrument, granularity_minutes=granularity_minutes
    )
    fixture = {
        "meta": {
            "instrument": instrument,
            "granularity_minutes": granularity_minutes,
            "source": "oanda_v20_practice",
            "host": host,
            "price_components": "MAB (mid/ask/bid)",
            "fetched_at": fetched_at.astimezone(UTC).isoformat(),
            "candle_count": len(ordered),
            "normalized_bar_count": len(series.bars),
            "quality_events": list(series.quality_events),
            "note": (
                "Research fixture (§12.1) — practice-feed prices. F-5: usable "
                "for spread modeling; fills/slippage need live/licensed data."
            ),
        },
        "candles": ordered,
    }
    return fixture, series
