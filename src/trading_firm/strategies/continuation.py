"""London Continuation rule logic, v0.1.0 — RESEARCH ONLY, unvalidated.

Deterministic translation of the london_continuation manifest, deliberately
built as a one-variable experiment against the champion: IDENTICAL
london_breakout mechanics (same triggers, stops, targets, regime filter)
plus exactly one filter — trade only in the direction of the prior
session's validated London-window structure (|net move| >= a declared
threshold). Any performance difference vs the champion is attributable to
the trend-alignment filter alone.

Single-signal discipline: the session's FIRST breakout decides. If it is
counter-trend, the session is no-trade — there is no re-scanning for a
later aligned breakout (declared before any replay ran, §12.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_firm.features.engine import PriorSessionStructure, SessionFeatures
from trading_firm.market_data.bars import Bar
from trading_firm.models import Direction
from trading_firm.strategies.breakout import (
    BreakoutParams,
    BreakoutSignal,
    first_breakout_signal,
)


@dataclass(frozen=True)
class ContinuationParams:
    min_prior_move_pips: Decimal = Decimal("20")
    buffer_pips: Decimal = Decimal("2")
    stop_max_pips: Decimal = Decimal("40")
    target_r: Decimal = Decimal("1.5")
    min_range_pips: Decimal = Decimal("15")
    max_range_pips: Decimal = Decimal("60")

    @classmethod
    def from_manifest_params(cls, params: dict) -> ContinuationParams:
        return cls(**{key: Decimal(str(value)) for key, value in params.items()})

    def breakout_params(self) -> BreakoutParams:
        return BreakoutParams(
            buffer_pips=self.buffer_pips,
            stop_max_pips=self.stop_max_pips,
            target_r=self.target_r,
            min_range_pips=self.min_range_pips,
            max_range_pips=self.max_range_pips,
        )


def first_continuation_signal(
    features: SessionFeatures,
    structure: PriorSessionStructure | None,
    active_bars: tuple[Bar, ...],
    params: ContinuationParams,
    pip_size: Decimal = Decimal("0.0001"),
) -> BreakoutSignal | None:
    """Champion breakout signal, kept only when trend-aligned.

    No prior structure (fail closed) or an unvalidated prior move
    (|net| < min_prior_move_pips) means no setup.
    """
    if structure is None:
        return None
    if abs(structure.net_move_pips) < params.min_prior_move_pips:
        return None
    signal = first_breakout_signal(features, active_bars, params.breakout_params(), pip_size)
    if signal is None:
        return None
    wanted = Direction.LONG if structure.net_move_pips > 0 else Direction.SHORT
    return signal if signal.direction is wanted else None
