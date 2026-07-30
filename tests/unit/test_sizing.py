"""Position-sizing tests (§21: position sizing, pip conversion, rounding)."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_firm.models import Candidate, Direction, InstrumentSpec
from trading_firm.sizing import size_position

D = Decimal
LONDON = ZoneInfo("Europe/London")
NOW = dt.datetime(2026, 7, 29, 9, 0, tzinfo=LONDON)

GBP_UNIT = InstrumentSpec(name="GBP_USD", margin_rate=D("0.05"))
GBP_MICRO_ONLY = InstrumentSpec(name="GBP_USD", margin_rate=D("0.05"), minimum_trade_size=1000)


def gbp_candidate(stop_pips: int) -> Candidate:
    entry = D("1.3298")
    return Candidate(
        instrument="GBP_USD",
        strategy_id="london_breakout",
        strategy_version="0.0.1",
        direction=Direction.LONG,
        entry_price=entry,
        stop_price=entry - D(stop_pips) * D("0.0001"),
        edge_score=75,
        created_at=NOW,
        expires_at=NOW + dt.timedelta(minutes=30),
        data_fresh=True,
        news_state_known=True,
        stop_broker_compatible=True,
    )


def test_golden_case_units_round_down() -> None:
    # allowed $2.81 (the F-1 margin-capped figure), 25-pip stop + 2-pip spread
    # -> loss/unit 0.0027 -> 1040 units, $2.80 effective risk, margin $69.14.
    result = size_position(
        gbp_candidate(25),
        GBP_UNIT,
        D("2.81"),
        closed_equity=D("250"),
        margin_utilization_cap_fraction=D("0.30"),
    )
    assert result.approved
    assert result.units == 1040
    assert result.effective_risk_usd == D("2.80")
    assert result.margin_required_usd == D("69.14")


def test_spread_assumption_included_in_loss_per_unit() -> None:
    # Same approval without spread would give 1124 units (2.81/0.0025);
    # the conservative 2-pip assumption must shrink the size.
    result = size_position(
        gbp_candidate(25),
        GBP_UNIT,
        D("2.81"),
        closed_equity=D("250"),
        margin_utilization_cap_fraction=D("0.30"),
        spread_pips_assumption=D("0"),
    )
    assert result.units == 1124


def test_micro_lot_minimum_rejects_small_risk() -> None:
    # M-7: a 1,000-unit-minimum broker cannot express $2.50 risk at a 40-pip stop.
    result = size_position(
        gbp_candidate(40),
        GBP_MICRO_ONLY,
        D("2.50"),
        closed_equity=D("250"),
        margin_utilization_cap_fraction=D("0.30"),
    )
    assert not result.approved
    assert any("minimum size" in r for r in result.reasons)


def test_margin_defense_in_depth() -> None:
    # If a caller ever passes uncapped risk, sizing still enforces the §3.2
    # overlay with the per-instrument rate (F-1) and rejects.
    result = size_position(
        gbp_candidate(25),
        GBP_UNIT,
        D("75.00"),
        closed_equity=D("250"),
        margin_utilization_cap_fraction=D("0.30"),
    )
    assert not result.approved
    assert any("margin" in r for r in result.reasons)


def test_zero_allowed_risk_rejected() -> None:
    result = size_position(
        gbp_candidate(25),
        GBP_UNIT,
        D("0"),
        closed_equity=D("250"),
        margin_utilization_cap_fraction=D("0.30"),
    )
    assert not result.approved
