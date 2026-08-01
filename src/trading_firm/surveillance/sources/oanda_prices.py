"""OANDA practice price freshness (§30.8; source `oanda_practice`).

The bar and spread series already exist (`market_data`); this adapter only
answers the source-health questions about them: when did the price picture
last update, and did this poll cycle succeed. It never opens a connection —
the read-only transport is composed elsewhere, and this module works on
whatever series it is handed (fixtures in research, live candles later).
"""

from __future__ import annotations

import datetime as dt

from trading_firm.market_data.bars import BarSeries

SOURCE_ID = "oanda_practice"


def last_price_update(series: BarSeries, before: dt.datetime) -> dt.datetime | None:
    """Close time of the last complete bar strictly before `before` — the
    timestamp the freshness component for `prices` runs on. None when the
    series has nothing yet (missing, not stale: fail closed distinguishes)."""
    if before.tzinfo is None:
        raise ValueError("aware datetimes required (§30.4, C-2)")
    bars = [b for b in series.bars if b.ts < before]
    if not bars:
        return None
    last = bars[-1]
    return last.ts + dt.timedelta(minutes=series.granularity_minutes)
