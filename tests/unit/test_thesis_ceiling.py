"""Thesis ceiling and tier provenance in the risk decision (A-2, §25, §5.2, §6.8).

§25's definition of done requires that "the audit record distinguishes a
gate-bound decision from a thesis-bound one". Before A-2 it could not: a trader
that under-classified its own opportunity produced a decision indistinguishable
from one the risk engine correctly restrained, so the miss was invisible and
caution was free.

The other half matters just as much and is tested here too: the thesis ceiling
must only ever LOWER. If a thesis could raise the tier its evidence score set,
A-2 would have created exactly the escalation route it exists to close.
"""

import datetime as dt
from decimal import Decimal

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.models import AccountState, Candidate, Direction, EdgeTier, InstrumentSpec
from trading_firm.risk.engine import RiskEngine
from trading_firm.sessions import SessionClock

UTC = dt.UTC
NOW = dt.datetime(2026, 7, 29, 8, 30, tzinfo=UTC)  # inside the London entry window


@pytest.fixture(scope="module")
def engine() -> RiskEngine:
    config = load_config(BASE_CONFIG_PATH)
    return RiskEngine(config, SessionClock(config.session))


@pytest.fixture(scope="module")
def spec() -> InstrumentSpec:
    # F-1: GBP_USD's per-instrument margin rate is 5%, not the account-level 2%.
    return InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))


@pytest.fixture
def account() -> AccountState:
    return AccountState(closed_equity=Decimal("250"), tier_anchor=Decimal("250"))


def candidate(**overrides) -> Candidate:
    base = dict(
        instrument="GBP_USD",
        strategy_id="london_breakout",
        strategy_version="1.0.0",
        direction=Direction.LONG,
        entry_price=Decimal("1.28500"),
        stop_price=Decimal("1.28250"),  # 25 pips
        edge_score=96,  # EXCEPTIONAL by score
        created_at=NOW,
        expires_at=NOW + dt.timedelta(minutes=10),
        data_fresh=True,
        news_state_known=True,
        stop_broker_compatible=True,
        human_approval=True,
    )
    base.update(overrides)
    return Candidate(**base)


class TestCeilingOnlyLowers:
    def test_a_thesis_cannot_raise_the_score_derived_tier(self, engine, account, spec) -> None:
        """The load-bearing A-2 invariant. A thesis claiming EXCEPTIONAL on a
        STANDARD-scoring candidate gets STANDARD, not EXCEPTIONAL."""
        low = engine.evaluate(
            candidate(edge_score=72, thesis_ceiling=EdgeTier.EXCEPTIONAL), account, spec, NOW
        )
        assert low.tier is EdgeTier.STANDARD
        assert low.tier_bound_by == "edge score (§5.2)"

    def test_ceiling_lowers_when_stricter(self, engine, account, spec) -> None:
        decision = engine.evaluate(
            candidate(edge_score=96, thesis_ceiling=EdgeTier.STRONG), account, spec, NOW
        )
        assert decision.tier is EdgeTier.STRONG
        assert "thesis classification" in decision.tier_bound_by

    @pytest.mark.parametrize("score", [72, 84, 92, 96])
    @pytest.mark.parametrize(
        "ceiling",
        [EdgeTier.STANDARD, EdgeTier.STRONG, EdgeTier.HIGH, EdgeTier.EXCEPTIONAL],
    )
    def test_resulting_tier_never_exceeds_either_input(
        self, engine, account, spec, score, ceiling
    ) -> None:
        """Property over the whole grid, not a spot check."""
        from trading_firm.models import tier_from_score

        decision = engine.evaluate(
            candidate(edge_score=score, thesis_ceiling=ceiling), account, spec, NOW
        )
        assert decision.tier <= tier_from_score(score)
        assert decision.tier <= ceiling


class TestUnvalidatedThesisIsRejected:
    def test_ceiling_of_none_rejects_with_its_own_reason(self, engine, account, spec) -> None:
        """An N2/N3 or E0-E2 thesis yields ceiling NONE. The rejection must say
        so rather than blaming the edge score, which was fine."""
        decision = engine.evaluate(
            candidate(edge_score=96, thesis_ceiling=EdgeTier.NONE), account, spec, NOW
        )
        assert decision.approved is False
        assert any("thesis classification permits no live tier" in r for r in decision.reasons)
        assert not any("edge score below 70" in r for r in decision.reasons), (
            "the edge score was 96; blaming it would misdirect an operator during an incident"
        )

    def test_low_score_still_blames_the_score(self, engine, account, spec) -> None:
        decision = engine.evaluate(
            candidate(edge_score=40, thesis_ceiling=EdgeTier.EXCEPTIONAL), account, spec, NOW
        )
        assert decision.approved is False
        assert any("edge score below 70" in r for r in decision.reasons)


class TestProvenanceRecord:
    """§25: the audit record distinguishes gate-bound from thesis-bound."""

    def test_gate_bound_decision_names_the_gate(self, engine, spec) -> None:
        # A session loss demotes Exceptional -> High. That is the FIRM's state
        # restraining the trade, not the thesis's evidence.
        account = AccountState(
            closed_equity=Decimal("250"),
            tier_anchor=Decimal("250"),
            session_realized_loss=Decimal("5.00"),
        )
        decision = engine.evaluate(
            candidate(thesis_ceiling=EdgeTier.EXCEPTIONAL), account, spec, NOW
        )
        assert decision.tier is EdgeTier.HIGH
        assert decision.tier_bound_by == "session loss disables Exceptional (§3.4)"

    def test_thesis_bound_decision_names_the_thesis(self, engine, account, spec) -> None:
        decision = engine.evaluate(candidate(thesis_ceiling=EdgeTier.HIGH), account, spec, NOW)
        assert decision.tier is EdgeTier.HIGH
        assert "thesis classification" in decision.tier_bound_by

    def test_the_two_cases_are_distinguishable(self, engine, spec) -> None:
        """The whole point of the field: same tier, different cause."""
        lossy = AccountState(
            closed_equity=Decimal("250"),
            tier_anchor=Decimal("250"),
            session_realized_loss=Decimal("5.00"),
        )
        clean = AccountState(closed_equity=Decimal("250"), tier_anchor=Decimal("250"))

        gate_bound = engine.evaluate(
            candidate(thesis_ceiling=EdgeTier.EXCEPTIONAL), lossy, spec, NOW
        )
        thesis_bound = engine.evaluate(candidate(thesis_ceiling=EdgeTier.HIGH), clean, spec, NOW)

        assert gate_bound.tier is thesis_bound.tier is EdgeTier.HIGH
        assert gate_bound.tier_bound_by != thesis_bound.tier_bound_by, (
            "two decisions at the same tier for opposite reasons must not look identical "
            "in the audit trail (A-2, §25)"
        )

    def test_ceiling_is_echoed_on_approval_and_rejection(self, engine, account, spec) -> None:
        approved = engine.evaluate(candidate(thesis_ceiling=EdgeTier.HIGH), account, spec, NOW)
        assert approved.approved is True
        assert approved.thesis_ceiling is EdgeTier.HIGH

        rejected = engine.evaluate(
            candidate(thesis_ceiling=EdgeTier.HIGH, data_fresh=False), account, spec, NOW
        )
        assert rejected.approved is False
        assert rejected.thesis_ceiling is EdgeTier.HIGH, (
            "a rejected candidate's thesis ceiling is still audit evidence"
        )


class TestBackwardCompatibility:
    def test_absent_ceiling_changes_nothing(self, engine, account, spec) -> None:
        """A named-strategy candidate carries no adaptive thesis. It must behave
        exactly as it did before A-2 — the amendment adds a record, not a gate."""
        without = engine.evaluate(candidate(), account, spec, NOW)
        assert without.thesis_ceiling is None
        assert without.tier is EdgeTier.EXCEPTIONAL
        assert without.tier_bound_by == "edge score (§5.2)"
        assert without.approved is True

    def test_ceiling_equal_to_score_tier_is_not_recorded_as_binding(
        self, engine, account, spec
    ) -> None:
        # Agreement between the two is not the thesis restraining anything.
        decision = engine.evaluate(
            candidate(edge_score=96, thesis_ceiling=EdgeTier.EXCEPTIONAL), account, spec, NOW
        )
        assert decision.tier is EdgeTier.EXCEPTIONAL
        assert decision.tier_bound_by == "edge score (§5.2)"


class TestGoldenNumbersUnchanged:
    """F-1 regression: A-2 must not have moved sizing by a cent.

    Reuses the canonical inputs from `test_risk_engine.py::TestMarginOverlayF1`
    — GBP_USD at 1.3298, 5% per-instrument margin, 30% cap on $250 — so this is
    a genuine cross-check rather than a second golden number with its own
    fixture, which is how golden numbers quietly diverge.
    """

    def test_exceptional_capacity_still_margin_bound_on_gbp(self, engine, account, spec) -> None:
        decision = engine.evaluate(
            candidate(entry_price=Decimal("1.3298"), stop_price=Decimal("1.3273")),
            account,
            spec,
            NOW,
        )
        assert decision.tier is EdgeTier.EXCEPTIONAL
        assert decision.binding_constraint == "margin-safe capacity (§3.2, F-1)"
        assert decision.allowed_risk_usd == Decimal("2.81")

    def test_a_thesis_ceiling_does_not_move_capacity_at_the_same_tier(
        self, engine, account, spec
    ) -> None:
        # Same tier reached two ways must size identically: A-2 records provenance,
        # it does not touch the §3.3 capacity minimum.
        args = dict(entry_price=Decimal("1.3298"), stop_price=Decimal("1.3273"), edge_score=92)
        plain = engine.evaluate(candidate(**args), account, spec, NOW)
        ceilinged = engine.evaluate(
            candidate(**args, thesis_ceiling=EdgeTier.HIGH), account, spec, NOW
        )
        assert plain.tier is ceilinged.tier is EdgeTier.HIGH
        assert plain.allowed_risk_usd == ceilinged.allowed_risk_usd
