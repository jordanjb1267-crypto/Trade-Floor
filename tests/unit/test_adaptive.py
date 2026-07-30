"""Adaptive-layer gates (v2 §5.2, §6.7, §6.8) and the §21 acceptance criteria
for them that do not require live agents.

The point of these tests is that the dangerous states are UNREPRESENTABLE, not
merely rejected at runtime: an unvalidated idea cannot be constructed into a
live-eligible thesis, however persuasive its prose.
"""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_firm.adaptive import (
    AdaptiveThesis,
    EvidenceClass,
    HistoricalAnalogs,
    MarketState,
    NoveltyClass,
    SelectedFeature,
    Thesis,
    TradePlan,
)

UTC = dt.UTC


def thesis(**overrides) -> AdaptiveThesis:
    base = dict(
        thesis_id="t-001",
        trader_id="alpha",
        timestamp_utc=dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC),
        instrument="GBP_USD",
        direction="long",
        market_state=MarketState(
            regime="compression", volatility_state="low", session_phase="briefing"
        ),
        selected_features=[
            SelectedFeature(
                feature_id="session_features_v1.asian_width_pips",
                observed_value=Decimal("38"),
                relevance="inside the 15-60 tradeable band",
            )
        ],
        historical_analogs=HistoricalAnalogs(sample_size=0),
        thesis=Thesis(
            causal_or_behavioral_rationale="overnight balance, London seeks liquidity",
            expected_path="expansion beyond the range edge, continuation",
            failure_scenario="rotation back inside within two bars",
        ),
        trade_plan=TradePlan(
            entry_rule="first print beyond the range + buffer",
            invalidation_rule="opposite range side",
            exit_rule="1.5R or flatten",
            expiration_rule="entry cutoff",
        ),
        novelty_class=NoveltyClass.N0,
        evidence_class=EvidenceClass.E3,
        estimated_costs=Decimal("0.02"),
        expected_value_basis="validated playbook expectancy",
        confidence_calibration_reference="calibration_v1",
    )
    base.update(overrides)
    return AdaptiveThesis(**base)


class TestNoveltyGates:
    def test_n2_and_n3_can_never_trade_live(self) -> None:
        # §21 acceptance criterion, and §6.8.
        for novelty in (NoveltyClass.N2, NoveltyClass.N3):
            assert novelty.may_trade_live is False
            t = thesis(novelty_class=novelty, evidence_class=EvidenceClass.E5)
            assert t.may_trade_live is False
            assert t.max_edge_tier == 0, "E5 evidence must not rescue N2/N3"

    def test_n1_can_never_receive_exceptional(self) -> None:
        # §21 acceptance criterion, and §6.8.
        t = thesis(novelty_class=NoveltyClass.N1, evidence_class=EvidenceClass.E5)
        assert t.may_trade_live is True
        assert t.max_edge_tier == 3, "N1 caps below EXCEPTIONAL(4) even at E5"

    def test_only_n0_reaches_exceptional(self) -> None:
        best = thesis(novelty_class=NoveltyClass.N0, evidence_class=EvidenceClass.E5)
        assert best.max_edge_tier == 4
        for n in (NoveltyClass.N1, NoveltyClass.N2, NoveltyClass.N3):
            assert n.may_receive_exceptional is False


class TestEvidenceGates:
    def test_unvalidated_evidence_cannot_trade_live(self) -> None:
        for ev in (EvidenceClass.E0, EvidenceClass.E1, EvidenceClass.E2):
            assert ev.may_trade_live is False
            assert thesis(evidence_class=ev).max_edge_tier == 0

    def test_evidence_ceiling_matches_spec_table(self) -> None:
        # §5.2: a class determines only the MAXIMUM tier the gate may consider.
        assert EvidenceClass.E3.max_edge_tier == 2  # Standard/Strong
        assert EvidenceClass.E4.max_edge_tier == 3  # High
        assert EvidenceClass.E5.max_edge_tier == 4  # Exceptional

    def test_stricter_of_the_two_classifications_wins(self) -> None:
        # High evidence, new logic -> novelty binds.
        novelty_bound = thesis(novelty_class=NoveltyClass.N1, evidence_class=EvidenceClass.E4)
        assert novelty_bound.max_edge_tier == 3
        # Validated logic, weak evidence -> evidence binds.
        evidence_bound = thesis(novelty_class=NoveltyClass.N0, evidence_class=EvidenceClass.E1)
        assert evidence_bound.max_edge_tier == 0


class TestThesisSchema:
    def test_narrative_only_thesis_is_rejected(self) -> None:
        # §21: "a narrative-only thesis with no deterministic evidence is rejected"
        with pytest.raises(ValidationError, match="narrative-only"):
            thesis(selected_features=[])

    def test_no_trade_thesis_needs_no_features(self) -> None:
        # §0 rule 6: "no trade" is always valid and must stay cheap to express.
        t = thesis(direction="none", selected_features=[])
        assert t.direction == "none"

    def test_failure_scenario_is_mandatory(self) -> None:
        # §6.2: a trader must state what would disprove its own thesis.
        with pytest.raises(ValidationError):
            thesis(
                thesis=Thesis(
                    causal_or_behavioral_rationale="x",
                    expected_path="y",
                    failure_scenario="",
                )
            )

    def test_naive_timestamp_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            thesis(timestamp_utc=dt.datetime(2026, 7, 30, 7, 40))

    def test_trader_id_restricted_to_the_pair(self) -> None:
        with pytest.raises(ValidationError):
            thesis(trader_id="gamma")

    def test_thesis_is_immutable_once_locked(self) -> None:
        # §6.2 independence protocol: first-pass reports are immutable.
        t = thesis()
        with pytest.raises(ValidationError):
            t.novelty_class = NoveltyClass.N0
