"""London Breakout rule logic, v0.1.0 — RESEARCH ONLY, unvalidated.

Deterministic translation of the london_breakout manifest rules: first print
beyond the Asian range plus a buffer during the ACTIVE window becomes the
session's single signal; the technical stop is the opposite range side,
capped; the target is a fixed R-multiple. No order code exists here (§12.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_firm.features.engine import SessionFeatures
from trading_firm.market_data.bars import Bar
from trading_firm.models import Direction


@dataclass(frozen=True)
class BreakoutParams:
    buffer_pips: Decimal = Decimal("2")
    stop_max_pips: Decimal = Decimal("40")
    target_r: Decimal = Decimal("1.5")
    min_range_pips: Decimal = Decimal("15")
    max_range_pips: Decimal = Decimal("60")

    @classmethod
    def from_manifest_params(cls, params: dict) -> BreakoutParams:
        return cls(**{key: Decimal(str(value)) for key, value in params.items()})


@dataclass(frozen=True)
class BreakoutSignal:
    direction: Direction
    trigger_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    triggered_by: Bar


def first_breakout_signal(
    features: SessionFeatures,
    active_bars: tuple[Bar, ...],
    params: BreakoutParams,
    pip_size: Decimal = Decimal("0.0001"),
) -> BreakoutSignal | None:
    """First qualifying breakout in the ACTIVE window, or None.

    Regime filter: the Asian range width must sit inside
    [min_range_pips, max_range_pips]; outside it there is no setup (§0.6).
    """
    if not (params.min_range_pips <= features.asian_width_pips <= params.max_range_pips):
        return None

    buffer = params.buffer_pips * pip_size
    long_trigger = features.asian_high + buffer
    short_trigger = features.asian_low - buffer

    for bar in active_bars:
        long_hit = bar.high >= long_trigger
        short_hit = bar.low <= short_trigger
        if long_hit and short_hit:
            return None  # both sides in one bar: ambiguous, no trade (§0.6)
        if long_hit:
            stop = max(features.asian_low, long_trigger - params.stop_max_pips * pip_size)
            risk = long_trigger - stop
            return BreakoutSignal(
                direction=Direction.LONG,
                trigger_price=long_trigger,
                stop_price=stop,
                target_price=long_trigger + params.target_r * risk,
                triggered_by=bar,
            )
        if short_hit:
            stop = min(features.asian_high, short_trigger + params.stop_max_pips * pip_size)
            risk = stop - short_trigger
            return BreakoutSignal(
                direction=Direction.SHORT,
                trigger_price=short_trigger,
                stop_price=stop,
                target_price=short_trigger - params.target_r * risk,
                triggered_by=bar,
            )
    return None
