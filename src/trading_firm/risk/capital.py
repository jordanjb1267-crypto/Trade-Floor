"""Capital tier system and drawdown-state machine (§4, D-2/D-3).

Milestone tiers only ever advance through owner-approved promotions armed by
deterministic conditions. Sizing always contracts on current closed equity.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from trading_firm.config import RiskSection
from trading_firm.models import DrawdownState, EdgeTier, PendingPromotion

PROMOTION_APPROVAL_WINDOW = dt.timedelta(days=7)  # §4.2 (v1.1.0): lapses unapproved


def tier_anchor(index: int, base: Decimal = Decimal("250")) -> Decimal:
    """§4.3: capital_anchor(n) = base * 2^n."""
    if index < 0:
        raise ValueError("tier index must be >= 0")
    return base * (Decimal(2) ** index)


def drawdown_state(
    closed_equity: Decimal,
    anchor: Decimal,
    live_floor: Decimal,
    caution_from_anchor: Decimal = Decimal("-0.05"),
    restricted_from_anchor: Decimal = Decimal("-0.10"),
) -> DrawdownState:
    """§4.5 state boundaries, measured from the current tier anchor."""
    if closed_equity <= live_floor:
        return DrawdownState.SHADOW
    if closed_equity < anchor * (1 + restricted_from_anchor):
        return DrawdownState.RESTRICTED
    if closed_equity < anchor * (1 + caution_from_anchor):
        return DrawdownState.CAUTION
    return DrawdownState.NORMAL


def max_tier_for_drawdown(state: DrawdownState) -> EdgeTier:
    """§4.5 per-state permission caps."""
    return {
        DrawdownState.NORMAL: EdgeTier.EXCEPTIONAL,
        DrawdownState.CAUTION: EdgeTier.STRONG,
        DrawdownState.RESTRICTED: EdgeTier.STANDARD,
        DrawdownState.SHADOW: EdgeTier.NONE,
    }[state]


def max_trades_for_drawdown(state: DrawdownState, risk: RiskSection) -> int:
    """§4.5: RESTRICTED tightens the session trade count to 1."""
    if state is DrawdownState.SHADOW:
        return 0
    if state is DrawdownState.RESTRICTED:
        return 1
    return risk.max_trades_per_session


def promotion_conditions_met(
    *,
    trading_closed_equity: Decimal,
    next_anchor: Decimal,
    open_positions: int,
    reconciled: bool,
    unresolved_issues: int,
    health_check_passed: bool,
) -> bool:
    """§4.2 deterministic arming conditions.

    trading_closed_equity is equity attributable to closed trading P&L only —
    deposits never advance milestones (D-3).
    """
    return (
        open_positions == 0
        and reconciled
        and unresolved_issues == 0
        and health_check_passed
        and trading_closed_equity >= next_anchor
    )


def arm_promotion(from_anchor: Decimal, now: dt.datetime) -> PendingPromotion:
    """Arm a pending promotion for owner approval (D-2). It lapses after 7 days."""
    if now.tzinfo is None:
        raise ValueError("naive datetimes are forbidden (§10.3)")
    return PendingPromotion(
        from_anchor=from_anchor,
        to_anchor=from_anchor * 2,
        armed_at=now,
        expires_at=now + PROMOTION_APPROVAL_WINDOW,
    )


def apply_promotion(
    pending: PendingPromotion, *, owner_approved: bool, now: dt.datetime
) -> Decimal | None:
    """Apply an armed promotion. Returns the new anchor, or None if not applied.

    No owner approval, or approval after the lapse window → no promotion.
    The caller re-arms automatically while conditions still hold (§4.2).
    """
    if not owner_approved:
        return None
    if now > pending.expires_at:
        return None
    return pending.to_anchor
