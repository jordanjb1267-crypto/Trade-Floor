"""Capital tier and drawdown tests (§21 'Capital tier calculations',
'Tier promotion and contraction', 'Drawdown state')."""

import datetime as dt
from decimal import Decimal

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.models import DrawdownState, EdgeTier
from trading_firm.risk import (
    apply_promotion,
    arm_promotion,
    drawdown_state,
    max_tier_for_drawdown,
    max_trades_for_drawdown,
    promotion_conditions_met,
    tier_anchor,
)

UTC = dt.UTC
D = Decimal


class TestAnchors:
    def test_doubling_sequence(self) -> None:
        assert tier_anchor(0) == D("250")
        assert tier_anchor(1) == D("500")
        assert tier_anchor(3) == D("2000")
        assert tier_anchor(9) == D("128000")

    def test_negative_index_rejected(self) -> None:
        with pytest.raises(ValueError):
            tier_anchor(-1)


class TestDrawdownStates:
    """Boundaries at anchor 250, floor 200: CAUTION < 237.50, RESTRICTED < 225."""

    @pytest.mark.parametrize(
        "equity,expected",
        [
            (D("250"), DrawdownState.NORMAL),
            (D("237.50"), DrawdownState.NORMAL),
            (D("237.49"), DrawdownState.CAUTION),
            (D("225.00"), DrawdownState.CAUTION),
            (D("224.99"), DrawdownState.RESTRICTED),
            (D("200.01"), DrawdownState.RESTRICTED),
            (D("200.00"), DrawdownState.SHADOW),
            (D("150.00"), DrawdownState.SHADOW),
        ],
    )
    def test_boundaries(self, equity: Decimal, expected: DrawdownState) -> None:
        assert drawdown_state(equity, D("250"), D("200")) is expected

    def test_permission_caps(self) -> None:
        assert max_tier_for_drawdown(DrawdownState.NORMAL) is EdgeTier.EXCEPTIONAL
        assert max_tier_for_drawdown(DrawdownState.CAUTION) is EdgeTier.STRONG
        assert max_tier_for_drawdown(DrawdownState.RESTRICTED) is EdgeTier.STANDARD
        assert max_tier_for_drawdown(DrawdownState.SHADOW) is EdgeTier.NONE

    def test_trade_count_restriction(self) -> None:
        risk = load_config(BASE_CONFIG_PATH).risk
        assert max_trades_for_drawdown(DrawdownState.NORMAL, risk) == 2
        assert max_trades_for_drawdown(DrawdownState.RESTRICTED, risk) == 1
        assert max_trades_for_drawdown(DrawdownState.SHADOW, risk) == 0


class TestPromotion:
    """§4.2 as amended: deterministic arming, owner-only application (D-2/D-3)."""

    def _clean_conditions(self, trading_equity: Decimal) -> bool:
        return promotion_conditions_met(
            trading_closed_equity=trading_equity,
            next_anchor=D("500"),
            open_positions=0,
            reconciled=True,
            unresolved_issues=0,
            health_check_passed=True,
        )

    def test_conditions_met_on_trading_equity(self) -> None:
        assert self._clean_conditions(D("510"))

    def test_deposits_never_advance_milestones(self) -> None:
        # Raw account equity may be $510 after a deposit, but milestone
        # accounting sees trading P&L only (D-3): $260 < $500 -> not armed.
        assert not self._clean_conditions(D("260"))

    def test_open_position_blocks_arming(self) -> None:
        assert not promotion_conditions_met(
            trading_closed_equity=D("510"),
            next_anchor=D("500"),
            open_positions=1,
            reconciled=True,
            unresolved_issues=0,
            health_check_passed=True,
        )

    def test_owner_approval_required(self) -> None:
        now = dt.datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        pending = arm_promotion(D("250"), now)
        assert pending.to_anchor == D("500")
        assert apply_promotion(pending, owner_approved=False, now=now) is None
        assert apply_promotion(pending, owner_approved=True, now=now) == D("500")

    def test_pending_promotion_lapses_after_seven_days(self) -> None:
        now = dt.datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
        pending = arm_promotion(D("250"), now)
        late = now + dt.timedelta(days=8)
        assert apply_promotion(pending, owner_approved=True, now=late) is None
