"""Liquidity and auction observation (§30.3.D) — evidence-labeled, always.

OANDA practice supplies quotes and candles, not order-book depth, so almost
everything here is PRICE_ACTION_INFERENCE or BROKER_PROXY and says so on
every field. The label is the load-bearing part: an inference that presents
itself as observation is exactly what the required evidence vocabulary
(OBSERVED / BROKER_PROXY / PRICE_ACTION_INFERENCE / UNAVAILABLE) exists to
prevent.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from trading_firm.market_data.bars import BarSeries
from trading_firm.market_data.spreads import SpreadSeries
from trading_firm.surveillance.schemas import (
    EvidenceType,
    LiquidityObservation,
    LiquidityState,
)

LIQUIDITY_LOGIC_VERSION = "surveillance_liquidity_v1"

# A sweep pierces the level by at least this fraction of the range and closes
# back inside the same bar or the next. Versioned with the logic.
SWEEP_MIN_PENETRATION = Decimal("0.10")


def _sweep(
    series: BarSeries,
    level: Decimal,
    above: bool,
    window_start: dt.datetime,
    window_end: dt.datetime,
    reference_range: Decimal,
) -> bool:
    """Sweep-and-reclaim: a poke through the level that fails to hold."""
    if reference_range <= 0:
        return False
    bars = series.between(window_start, window_end)
    threshold = reference_range * SWEEP_MIN_PENETRATION
    for index, bar in enumerate(bars):
        pierced = (bar.high - level) >= threshold if above else (level - bar.low) >= threshold
        if not pierced:
            continue
        closes = [bar.close]
        if index + 1 < len(bars):
            closes.append(bars[index + 1].close)
        reclaimed = any(c < level for c in closes) if above else any(c > level for c in closes)
        if reclaimed:
            return True
    return False


def _window_spreads(
    spreads: SpreadSeries,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[Decimal]:
    return [
        spread
        for ts, spread in sorted(spreads.by_ts.items())
        if window_start <= ts < window_end
    ]


def observe_liquidity(
    series: BarSeries,
    spreads: SpreadSeries | None,
    asian_high: Decimal,
    asian_low: Decimal,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> LiquidityState:
    reference_range = asian_high - asian_low
    swept_high = _sweep(series, asian_high, True, window_start, window_end, reference_range)
    swept_low = _sweep(series, asian_low, False, window_start, window_end, reference_range)

    observations = [
        LiquidityObservation(
            name="asian_high_sweep_and_reclaim",
            value=str(swept_high),
            evidence=EvidenceType.PRICE_ACTION_INFERENCE,
        ),
        LiquidityObservation(
            name="asian_low_sweep_and_reclaim",
            value=str(swept_low),
            evidence=EvidenceType.PRICE_ACTION_INFERENCE,
        ),
    ]

    in_window = _window_spreads(spreads, window_start, window_end) if spreads else []
    if in_window:
        # Broker-measured close spreads (price units). The doubling test is
        # against the window's own median — a distribution, not a constant.
        current = in_window[-1]
        median = sorted(in_window)[len(in_window) // 2]
        widened = median > 0 and current > median * 2
        spread_state = "widened" if widened else "normal"
        spread_evidence = EvidenceType.OBSERVED
        observations.append(
            LiquidityObservation(
                name="spread_current_vs_window_median",
                value=f"{current}/{median}",
                evidence=EvidenceType.OBSERVED,
            )
        )
    else:
        spread_state = "unknown"
        spread_evidence = EvidenceType.UNAVAILABLE

    classification = "swept" if (swept_high or swept_low) else "undisturbed"
    return LiquidityState(
        classification=classification,
        evidence=EvidenceType.PRICE_ACTION_INFERENCE,
        observations=observations,
        spread_state=spread_state,
        spread_evidence=spread_evidence,
        spread_percentile=None,
    )
