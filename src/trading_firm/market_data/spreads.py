"""Per-bar spread series from bid/ask fixtures (§8.1, research §12.1).

Gives replay a measured spread for each bar instead of the flat sizing
assumption. The per-bar figure is the CLOSE spread (ask.c - bid.c): within
the London trading window spreads are stable (2026-07-30 measurement:
GBP_USD p95 within 0.2 pips of median), so close-of-bar is a fair estimate
for any fill inside the bar. The firm never holds through the rollover
regime where that would break down (§14, F-5).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

UTC = dt.UTC


@dataclass(frozen=True)
class SpreadSeries:
    """Measured spread (price units, not pips) per bar-open timestamp."""

    instrument: str
    by_ts: dict[dt.datetime, Decimal]

    @classmethod
    def from_oanda_candles(cls, candles: list[dict], *, instrument: str) -> SpreadSeries:
        by_ts: dict[dt.datetime, Decimal] = {}
        for candle in candles:
            if not candle.get("complete", True):
                continue
            if "bid" not in candle or "ask" not in candle:
                raise ValueError(
                    "candle lacks bid/ask blocks — fetch fixtures with price=MAB "
                    "(scripts/fetch_oanda_candles.py does)"
                )
            ts = dt.datetime.fromisoformat(str(candle["time"]).replace("Z", "+00:00"))
            spread = Decimal(str(candle["ask"]["c"])) - Decimal(str(candle["bid"]["c"]))
            if spread < 0:
                raise ValueError(f"negative spread at {ts.isoformat()} (crossed quote)")
            by_ts[ts.astimezone(UTC)] = spread
        return cls(instrument=instrument, by_ts=by_ts)

    def at(self, ts: dt.datetime) -> Decimal:
        """Spread for the bar opening at ts. Fails closed on a gap (§0.6):
        replay must not silently substitute an assumption mid-run."""
        try:
            return self.by_ts[ts.astimezone(UTC)]
        except KeyError:
            raise KeyError(
                f"no measured spread for bar {ts.isoformat()} — spread series and "
                "bar series must come from the same fixture"
            ) from None
