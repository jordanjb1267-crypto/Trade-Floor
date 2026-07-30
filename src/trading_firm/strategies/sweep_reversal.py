"""Asian Range Sweep & Reversal rule logic, v0.1.0 — RESEARCH ONLY, unvalidated.

Deterministic translation of the asian_range_sweep_reversal manifest rules:
a sweep beyond an Asian-range extreme (bounded depth) that fails acceptance
by CLOSING back inside the range within a declared bar budget becomes the
session's single signal, entered at that re-entry close, invalidated beyond
the sweep extreme, targeting the opposing range liquidity. No order code
exists here (§12.1).

First-guess parameters live in the manifest and were declared before any
replay of this strategy ran (§12.4). A sweep deeper than max_sweep_pips is
ACCEPTANCE (a real breakout, not a sweep): that side is dead for the
session. A required stop wider than stop_max_pips is no-setup (§0.6) — the
stop is never pulled inside the invalidation level to fit a cap.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_firm.features.engine import SessionFeatures
from trading_firm.market_data.bars import Bar
from trading_firm.models import Direction


@dataclass(frozen=True)
class SweepReversalParams:
    min_sweep_pips: Decimal = Decimal("3")
    max_sweep_pips: Decimal = Decimal("25")
    reentry_within_bars: int = 3
    stop_buffer_pips: Decimal = Decimal("2")
    stop_max_pips: Decimal = Decimal("40")
    min_range_pips: Decimal = Decimal("15")
    max_range_pips: Decimal = Decimal("60")

    @classmethod
    def from_manifest_params(cls, params: dict) -> SweepReversalParams:
        kwargs: dict = {}
        for key, value in params.items():
            kwargs[key] = int(value) if key == "reentry_within_bars" else Decimal(str(value))
        return cls(**kwargs)


@dataclass(frozen=True)
class SweepReversalSignal:
    direction: Direction
    trigger_price: Decimal  # re-entry bar CLOSE: entry is at-close, not a stop order
    stop_price: Decimal
    target_price: Decimal
    triggered_by: Bar
    entry_at_close: bool = True  # replay must not exit on pre-entry price action


@dataclass
class _SideState:
    start_index: int | None = None  # first bar at/past the sweep threshold
    extreme: Decimal | None = None
    dead: bool = False


def first_sweep_reversal_signal(
    features: SessionFeatures,
    active_bars: tuple[Bar, ...],
    params: SweepReversalParams,
    pip_size: Decimal = Decimal("0.0001"),
) -> SweepReversalSignal | None:
    """First qualifying sweep-reversal in the ACTIVE window, or None.

    Both sides completing on the same bar is ambiguous: no trade (§0.6),
    mirroring the breakout rule.
    """
    if not (params.min_range_pips <= features.asian_width_pips <= params.max_range_pips):
        return None

    sweep = params.min_sweep_pips * pip_size
    accept = params.max_sweep_pips * pip_size
    buffer = params.stop_buffer_pips * pip_size
    high_side = _SideState()  # sweep above asian_high -> SHORT on failure
    low_side = _SideState()  # sweep below asian_low -> LONG on failure

    for index, bar in enumerate(active_bars):
        if not high_side.dead:
            if bar.high >= features.asian_high + accept:
                high_side.dead = True  # acceptance: genuine breakout, not a sweep
            elif high_side.start_index is None and bar.high >= features.asian_high + sweep:
                high_side.start_index = index
                high_side.extreme = bar.high
            elif high_side.start_index is not None:
                high_side.extreme = max(high_side.extreme, bar.high)
                if index - high_side.start_index >= params.reentry_within_bars:
                    high_side.dead = True  # held outside too long: accepted
        if not low_side.dead:
            if bar.low <= features.asian_low - accept:
                low_side.dead = True
            elif low_side.start_index is None and bar.low <= features.asian_low - sweep:
                low_side.start_index = index
                low_side.extreme = bar.low
            elif low_side.start_index is not None:
                low_side.extreme = min(low_side.extreme, bar.low)
                if index - low_side.start_index >= params.reentry_within_bars:
                    low_side.dead = True

        # "Back inside the range" means inside on BOTH sides: a re-entry close
        # that has already blown through the opposite extreme would put the
        # opposing-liquidity target BEHIND the entry (negative reward), which
        # replay would then score as a TARGET win. Require strictly inside.
        closed_inside = features.asian_low < bar.close < features.asian_high
        short_ready = (
            not high_side.dead
            and high_side.start_index is not None
            and index - high_side.start_index < params.reentry_within_bars
            and closed_inside
        )
        long_ready = (
            not low_side.dead
            and low_side.start_index is not None
            and index - low_side.start_index < params.reentry_within_bars
            and closed_inside
        )
        if short_ready and long_ready:
            return None  # both sides resolved on one bar: ambiguous (§0.6)
        if short_ready:
            stop = high_side.extreme + buffer
            if stop - bar.close > params.stop_max_pips * pip_size:
                return None  # never tighten the stop inside invalidation (§0.6)
            return SweepReversalSignal(
                direction=Direction.SHORT,
                trigger_price=bar.close,
                stop_price=stop,
                target_price=features.asian_low,
                triggered_by=bar,
            )
        if long_ready:
            stop = low_side.extreme - buffer
            if bar.close - stop > params.stop_max_pips * pip_size:
                return None
            return SweepReversalSignal(
                direction=Direction.LONG,
                trigger_price=bar.close,
                stop_price=stop,
                target_price=features.asian_high,
                triggered_by=bar,
            )
    return None
