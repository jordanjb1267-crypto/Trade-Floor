"""Market-data normalization (§8.1 Market Data Service).

Normalizes source candles into aware-UTC Decimal bars, detects quality
problems (duplicates, gaps, malformed OHLC), and never guesses timezones:
sources with naive timestamps require an explicit source timezone.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

UTC = dt.UTC


@dataclass(frozen=True)
class Bar:
    """One completed candle. ts is the bar OPEN time, aware UTC. Prices are mid."""

    instrument: str
    ts: dt.datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = 0
    complete: bool = True

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware (§10.3)")
        if not (self.high >= max(self.open, self.close) and self.low <= min(self.open, self.close)):
            raise ValueError(f"malformed OHLC at {self.ts}: {self}")
        if self.low <= 0:
            raise ValueError(f"non-positive price at {self.ts}")


@dataclass(frozen=True)
class BarSeries:
    """Ascending, de-duplicated bars of one instrument/granularity + quality events."""

    instrument: str
    granularity_minutes: int
    bars: tuple[Bar, ...]
    quality_events: tuple[str, ...] = field(default_factory=tuple)

    def between(self, start: dt.datetime, end: dt.datetime) -> tuple[Bar, ...]:
        """Bars with start <= ts < end (aware datetimes required)."""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("aware datetimes required (§10.3)")
        return tuple(b for b in self.bars if start <= b.ts < end)


def _assemble(
    instrument: str, granularity_minutes: int, raw: list[tuple[dt.datetime, dict]]
) -> BarSeries:
    events: list[str] = []
    bars: list[Bar] = []
    seen: set[dt.datetime] = set()
    step = dt.timedelta(minutes=granularity_minutes)

    for ts, values in sorted(raw, key=lambda item: item[0]):
        if ts in seen:
            events.append(f"duplicate bar dropped at {ts.isoformat()}")
            continue
        seen.add(ts)
        try:
            bar = Bar(instrument=instrument, ts=ts, **values)
        except ValueError as err:
            events.append(f"malformed bar dropped: {err}")
            continue
        if bars:
            gap = bar.ts - bars[-1].ts
            # weekend/holiday gaps are expected; flag only intra-day anomalies
            if step < gap < dt.timedelta(hours=24):
                events.append(
                    f"gap of {gap} before {bar.ts.isoformat()} (expected {step})"
                )
        bars.append(bar)
    return BarSeries(
        instrument=instrument,
        granularity_minutes=granularity_minutes,
        bars=tuple(bars),
        quality_events=tuple(events),
    )


def from_fmp_rows(
    rows: list[dict],
    *,
    instrument: str,
    granularity_minutes: int,
    source_tz: str,
) -> BarSeries:
    """Normalize FMP intraday rows ({date, open, high, low, close, volume}).

    FMP intraday timestamps are naive local times; the caller MUST state the
    source timezone explicitly (calendar audit precedent: unmarked timestamps
    get pinned, never assumed — §10.3, D-7 caveat).
    """
    zone = ZoneInfo(source_tz)
    raw: list[tuple[dt.datetime, dict]] = []
    for row in rows:
        naive = dt.datetime.fromisoformat(str(row["date"]))
        if naive.tzinfo is not None:
            raise ValueError("from_fmp_rows expects naive timestamps plus source_tz")
        ts = naive.replace(tzinfo=zone).astimezone(UTC)
        raw.append(
            (
                ts,
                {
                    "open": Decimal(str(row["open"])),
                    "high": Decimal(str(row["high"])),
                    "low": Decimal(str(row["low"])),
                    "close": Decimal(str(row["close"])),
                    "volume": int(row.get("volume") or 0),
                },
            )
        )
    return _assemble(instrument, granularity_minutes, raw)


def from_oanda_candles(
    candles: list[dict], *, instrument: str, granularity_minutes: int
) -> BarSeries:
    """Normalize OANDA v20 candles ({time, mid:{o,h,l,c}, volume, complete})."""
    raw: list[tuple[dt.datetime, dict]] = []
    for candle in candles:
        if not candle.get("complete", True):
            continue  # incomplete candles never enter the record (§8.1)
        ts = dt.datetime.fromisoformat(str(candle["time"]).replace("Z", "+00:00"))
        ts = ts.astimezone(UTC)
        mid = candle["mid"]
        raw.append(
            (
                ts,
                {
                    "open": Decimal(str(mid["o"])),
                    "high": Decimal(str(mid["h"])),
                    "low": Decimal(str(mid["l"])),
                    "close": Decimal(str(mid["c"])),
                    "volume": int(candle.get("volume") or 0),
                },
            )
        )
    return _assemble(instrument, granularity_minutes, raw)
