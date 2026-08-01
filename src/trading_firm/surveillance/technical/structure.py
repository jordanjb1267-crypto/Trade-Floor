"""Price-structure observation (§30.3.B): levels, breaks, failed breaks.

Deterministic detection over closed bars only. A "break" is a close beyond a
level on its breakout side; a "failed break" is a break whose price closes
back through the level within the confirmation window — the
sweep-and-reject shape the Liquidity and Auction Monitor consumes. No bar
that is still forming contributes (no-lookahead, §30.17 replay row).

Every level carries its side explicitly. Inferring direction from a level's
name is how "asian_high" and a mislabeled custom level silently swap breakout
semantics; an explicit side makes the mistake a construction error.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from trading_firm.market_data.bars import BarSeries
from trading_firm.surveillance.schemas import KeyLevel

# Bars a break has to hold beyond the level before "failed break" stops being
# available. Versioned with the logic: changing it is a new version.
FAILED_BREAK_CONFIRMATION_BARS = 3
STRUCTURE_LOGIC_VERSION = "surveillance_structure_v1"


class StructureEventKind(enum.StrEnum):
    LEVEL_REACHED = "level_reached"
    BREAK = "break"
    FAILED_BREAK = "failed_break"


@dataclass(frozen=True)
class SidedLevel:
    """A key level plus the side a breakout closes on: 'above' for highs,
    'below' for lows."""

    level: KeyLevel
    breakout_side: Literal["above", "below"]


@dataclass(frozen=True)
class StructureObservation:
    level_id: str
    kind: StructureEventKind
    at: dt.datetime
    price: Decimal
    logic_version: str = STRUCTURE_LOGIC_VERSION


def key_levels(
    asian_high: Decimal,
    asian_low: Decimal,
    prior_session_high: Decimal | None,
    prior_session_low: Decimal | None,
) -> list[SidedLevel]:
    levels = [
        SidedLevel(
            KeyLevel(level_id="asian_high", price=asian_high, kind="session_extreme"),
            breakout_side="above",
        ),
        SidedLevel(
            KeyLevel(level_id="asian_low", price=asian_low, kind="session_extreme"),
            breakout_side="below",
        ),
    ]
    if prior_session_high is not None:
        levels.append(
            SidedLevel(
                KeyLevel(
                    level_id="prior_session_high", price=prior_session_high, kind="prior_extreme"
                ),
                breakout_side="above",
            )
        )
    if prior_session_low is not None:
        levels.append(
            SidedLevel(
                KeyLevel(
                    level_id="prior_session_low", price=prior_session_low, kind="prior_extreme"
                ),
                breakout_side="below",
            )
        )
    return levels


def observe_structure(
    series: BarSeries,
    levels: list[SidedLevel],
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[StructureObservation]:
    """Walk closed bars in [window_start, window_end) against each level.

    Emits at most one LEVEL_REACHED, one BREAK, and one FAILED_BREAK per
    level per window — the state-change-only discipline (§30.6) starts at
    detection, not at the alert layer, or a choppy session floods everything
    downstream.
    """
    bars = series.between(window_start, window_end)
    out: list[StructureObservation] = []
    for sided in levels:
        level = sided.level
        above = sided.breakout_side == "above"
        touched = broke = failed = None
        broke_index = None
        for index, bar in enumerate(bars):
            if touched is None and bar.high >= level.price >= bar.low:
                touched = StructureObservation(
                    level_id=level.level_id,
                    kind=StructureEventKind.LEVEL_REACHED,
                    at=bar.ts,
                    price=level.price,
                )
            closed_beyond = bar.close > level.price if above else bar.close < level.price
            if broke is None and closed_beyond:
                broke = StructureObservation(
                    level_id=level.level_id,
                    kind=StructureEventKind.BREAK,
                    at=bar.ts,
                    price=bar.close,
                )
                broke_index = index
                continue
            if broke is not None and failed is None and broke_index is not None:
                back_inside = bar.close < level.price if above else bar.close > level.price
                if back_inside and index - broke_index <= FAILED_BREAK_CONFIRMATION_BARS:
                    failed = StructureObservation(
                        level_id=level.level_id,
                        kind=StructureEventKind.FAILED_BREAK,
                        at=bar.ts,
                        price=bar.close,
                    )
        out.extend(o for o in (touched, broke, failed) if o is not None)
    return out
