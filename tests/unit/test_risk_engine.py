"""Risk engine tests (§21: risk ladder, session/weekly limits, exceptional
gates, margin overlay with per-instrument rates — audit F-1 golden numbers)."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.models import (
    AccountState,
    Candidate,
    Direction,
    EdgeTier,
    InstrumentSpec,
    tier_from_score,
)
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock

D = Decimal
LONDON = ZoneInfo("Europe/London")

# Broker-reported per-instrument margin rates from the 2026-07-29 practice audit (F-1).
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=D("0.05"))
EUR_USD = InstrumentSpec(name="EUR_USD", margin_rate=D("0.02"))

IN_SESSION = dt.datetime(2026, 7, 29, 9, 0, tzinfo=LONDON)  # ACTIVE window


@pytest.fixture(scope="module")
def engine() -> RiskEngine:
    config = load_config(BASE_CONFIG_PATH)
    return RiskEngine(config, SessionClock(config.session))


def candidate(
    *,
    instrument: str = "EUR_USD",
    entry: str = "1.1394",
    stop_pips: int = 25,
    score: int = 75,
    approval: bool = False,
    expires: dt.datetime | None = None,
    fresh: bool = True,
    news_known: bool = True,
) -> Candidate:
    entry_price = D(entry)
    return Candidate(
        instrument=instrument,
        strategy_id="london_breakout",
        strategy_version="0.0.1",
        direction=Direction.LONG,
        entry_price=entry_price,
        stop_price=entry_price - D(stop_pips) * D("0.0001"),
        edge_score=score,
        created_at=IN_SESSION - dt.timedelta(minutes=5),
        expires_at=expires or (IN_SESSION + dt.timedelta(minutes=30)),
        data_fresh=fresh,
        news_state_known=news_known,
        stop_broker_compatible=True,
        human_approval=approval,
    )


def account(equity: str = "250", **kwargs) -> AccountState:
    return AccountState(closed_equity=D(equity), tier_anchor=D("250"), **kwargs)


class TestTierFromScore:
    @pytest.mark.parametrize(
        "score,tier",
        [(0, EdgeTier.NONE), (69, EdgeTier.NONE), (70, EdgeTier.STANDARD),
         (79, EdgeTier.STANDARD), (80, EdgeTier.STRONG), (89, EdgeTier.STRONG),
         (90, EdgeTier.HIGH), (94, EdgeTier.HIGH), (95, EdgeTier.EXCEPTIONAL),
         (100, EdgeTier.EXCEPTIONAL)],
    )
    def test_thresholds(self, score: int, tier: EdgeTier) -> None:
        assert tier_from_score(score) is tier

    def test_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError):
            tier_from_score(101)


class TestMarginOverlayF1:
    """Audit F-1 golden numbers: per-instrument margin rate governs capacity."""

    def test_gbp_exceptional_collapses_to_margin_capacity(self, engine: RiskEngine) -> None:
        # GBP_USD @ 1.3298, 5% margin, 30% cap on $250 = $75 budget:
        # units_cap = 75 / (1.3298 x 0.05) ~= 1127.99 -> risk cap ~= $2.81 at a 25-pip stop.
        decision = engine.evaluate(
            candidate(instrument="GBP_USD", entry="1.3298", score=97, approval=True),
            account(),
            GBP_USD,
            IN_SESSION,
        )
        assert decision.approved
        assert decision.tier is EdgeTier.EXCEPTIONAL
        assert decision.allowed_risk_usd == D("2.81")
        assert "margin-safe" in decision.binding_constraint

    def test_eur_same_setup_gets_more_capacity(self, engine: RiskEngine) -> None:
        # EUR_USD @ 1.1394, 2% margin: units_cap ~= 3291.2 -> ~$8.22 at 25 pips.
        decision = engine.evaluate(
            candidate(instrument="EUR_USD", entry="1.1394", score=97, approval=True),
            account(),
            EUR_USD,
            IN_SESSION,
        )
        assert decision.approved
        assert decision.allowed_risk_usd == D("8.22")
        assert "margin-safe" in decision.binding_constraint


class TestLadderAndContraction:
    def test_standard_dollar_cap_binds_above_anchor(self, engine: RiskEngine) -> None:
        # Equity $310 > anchor: 1% of equity is $3.10 but the tier cap stays $2.50 (N-1).
        decision = engine.evaluate(
            candidate(stop_pips=20), account("310"), EUR_USD, IN_SESSION
        )
        assert decision.approved
        assert decision.allowed_risk_usd == D("2.50")
        assert "dollar cap" in decision.binding_constraint

    def test_fraction_contracts_below_anchor(self, engine: RiskEngine) -> None:
        # Equity $245 (NORMAL): 1% of 245 = $2.45 < $2.50 tier cap.
        decision = engine.evaluate(
            candidate(stop_pips=20), account("245"), EUR_USD, IN_SESSION
        )
        assert decision.approved
        assert decision.allowed_risk_usd == D("2.45")


class TestSessionAndWeeklyLimits:
    def test_session_loss_limit_ends_session(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(
            candidate(), account(session_realized_loss=D("25")), EUR_USD, IN_SESSION
        )
        assert not decision.approved
        assert any("session is over" in r for r in decision.reasons)

    def test_weekly_capacity_binds(self, engine: RiskEngine) -> None:
        # $25 lost earlier in the ISO week: $12.50 remains and caps an Exceptional trade.
        decision = engine.evaluate(
            candidate(score=97, approval=True, stop_pips=60),
            account(weekly_realized_loss=D("25")),
            EUR_USD,
            IN_SESSION,
        )
        assert decision.approved
        assert decision.allowed_risk_usd == D("12.50")
        assert "weekly" in decision.binding_constraint

    def test_trade_count_exhausted(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(
            candidate(), account(trades_this_session=2), EUR_USD, IN_SESSION
        )
        assert not decision.approved

    def test_open_position_blocks(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(candidate(), account(open_positions=1), EUR_USD, IN_SESSION)
        assert not decision.approved


class TestExceptionalGates:
    def test_session_loss_disables_exceptional(self, engine: RiskEngine) -> None:
        # §21 acceptance: 'No exceptional trade after a session loss' — demoted to High.
        decision = engine.evaluate(
            candidate(score=96, approval=True, stop_pips=60),
            account("245", session_realized_loss=D("5")),
            EUR_USD,
            IN_SESSION,
        )
        assert decision.approved
        assert decision.tier is EdgeTier.HIGH
        assert decision.allowed_risk_usd == D("12.25")  # 5% of $245

    def test_missing_human_approval_demotes(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(
            candidate(score=96, approval=False, stop_pips=60), account(), EUR_USD, IN_SESSION
        )
        assert decision.approved
        assert decision.tier is EdgeTier.HIGH

    def test_second_exceptional_demoted(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(
            candidate(score=96, approval=True, stop_pips=60),
            account(exceptional_trades_this_session=1),
            EUR_USD,
            IN_SESSION,
        )
        assert decision.approved
        assert decision.tier is EdgeTier.HIGH


class TestFailClosed:
    def test_stale_data_rejected(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(candidate(fresh=False), account(), EUR_USD, IN_SESSION)
        assert not decision.approved

    def test_unknown_news_state_rejected(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(candidate(news_known=False), account(), EUR_USD, IN_SESSION)
        assert not decision.approved

    def test_expired_candidate_rejected(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(
            candidate(expires=IN_SESSION - dt.timedelta(minutes=1)),
            account(),
            EUR_USD,
            IN_SESSION,
        )
        assert not decision.approved

    def test_outside_entry_window_rejected(self, engine: RiskEngine) -> None:
        before_open = dt.datetime(2026, 7, 29, 7, 30, tzinfo=LONDON)
        decision = engine.evaluate(
            candidate(expires=before_open + dt.timedelta(hours=1)),
            account(),
            EUR_USD,
            before_open,
        )
        assert not decision.approved

    def test_no_qualified_edge_rejected(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(candidate(score=69), account(), EUR_USD, IN_SESSION)
        assert not decision.approved

    def test_shadow_state_rejected(self, engine: RiskEngine) -> None:
        decision = engine.evaluate(candidate(), account("200"), EUR_USD, IN_SESSION)
        assert not decision.approved
