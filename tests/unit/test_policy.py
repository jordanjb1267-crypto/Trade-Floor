"""Adaptive policy manifest schema (§11, §12.5, §6.8).

Follows `test_config.py`'s pattern: assert the shipped manifest is valid, then
inject each violation the schema exists to reject. A validator with no test
proving it rejects is a comment.
"""

from decimal import Decimal

import pytest
import yaml
from pydantic import ValidationError

from trading_firm.adaptive import EvidenceClass, NoveltyClass
from trading_firm.policy import AdaptivePolicyManifest, load_adaptive_policy

POLICY_PATH = "config/research/adaptive_policy.yaml"


@pytest.fixture(scope="module")
def raw() -> dict:
    with open(POLICY_PATH) as handle:
        return yaml.safe_load(handle)


def build(raw: dict, **overrides) -> AdaptivePolicyManifest:
    payload = dict(raw)
    payload.update(overrides)
    return AdaptivePolicyManifest.model_validate(payload)


class TestShippedPolicy:
    def test_loads(self) -> None:
        policy = load_adaptive_policy(POLICY_PATH)
        assert policy.adaptive_policy_id == "senior_trader_policy"
        assert policy.status == "research"

    def test_no_novelty_class_may_trade_live_today(self) -> None:
        # The Pass 2 equivalent of `live_allowed: []` — nothing is live.
        assert load_adaptive_policy(POLICY_PATH).allowed_novelty_classes_live == []

    def test_registry_matches_features_the_engine_computes(self) -> None:
        from trading_firm.features.engine import FEATURES_VERSION

        policy = load_adaptive_policy(POLICY_PATH)
        assert policy.approved_feature_registry, "an empty registry caps every thesis at E1"
        for feature_id in policy.approved_feature_registry:
            assert feature_id.startswith(f"{FEATURES_VERSION}."), (
                f"{feature_id} is not versioned against the current feature engine "
                f"({FEATURES_VERSION}) — §11 requires versioned ids"
            )

    def test_pressure_escalation_is_named_prohibited(self) -> None:
        policy = load_adaptive_policy(POLICY_PATH)
        assert "post_loss_risk_escalation" in policy.prohibited_behaviors
        assert "target_driven_risk_escalation" in policy.prohibited_behaviors


class TestNoveltyGates:
    @pytest.mark.parametrize("illegal", [NoveltyClass.N2, NoveltyClass.N3])
    def test_unvalidated_novelty_cannot_be_listed_live(self, raw, illegal) -> None:
        with pytest.raises(ValidationError, match="cannot place live orders"):
            build(raw, status="live", allowed_novelty_classes_live=[illegal])

    @pytest.mark.parametrize("illegal", [NoveltyClass.N2, NoveltyClass.N3])
    def test_probation_is_not_a_backdoor(self, raw, illegal) -> None:
        with pytest.raises(ValidationError, match="not a route around"):
            build(raw, limited_probation_classes=[illegal])


class TestPromotionControls:
    def test_live_novelty_requires_live_status(self, raw) -> None:
        with pytest.raises(ValidationError, match="promotion process"):
            build(raw, allowed_novelty_classes_live=[NoveltyClass.N0])

    def test_live_status_requires_a_promotion_record(self, raw) -> None:
        with pytest.raises(ValidationError, match="signed promotion record"):
            build(raw, status="live", validation_record_id="v-1")

    def test_paper_status_requires_a_validation_record(self, raw) -> None:
        with pytest.raises(ValidationError, match="validation record"):
            build(raw, status="paper")


class TestEvidenceMapping:
    def test_exceptional_below_e5_is_rejected(self, raw) -> None:
        mapping = dict(raw["required_evidence_class_by_risk_tier"])
        mapping["exceptional"] = EvidenceClass.E4
        with pytest.raises(ValidationError, match="requires E5"):
            build(raw, required_evidence_class_by_risk_tier=mapping)

    def test_unknown_tier_is_rejected(self, raw) -> None:
        mapping = dict(raw["required_evidence_class_by_risk_tier"])
        mapping["heroic"] = EvidenceClass.E3
        with pytest.raises(ValidationError, match="unknown tiers"):
            build(raw, required_evidence_class_by_risk_tier=mapping)


class TestProhibitedBehaviors:
    @pytest.mark.parametrize(
        "dropped",
        [
            "post_loss_risk_escalation",
            "narrative_only_edge_claim",
            "lookahead_data",
            "intraday_parameter_fitting",
            "unversioned_indicator_creation",
        ],
    )
    def test_the_floor_cannot_be_shortened(self, raw, dropped) -> None:
        remaining = [b for b in raw["prohibited_behaviors"] if b != dropped]
        with pytest.raises(ValidationError, match="never shorten"):
            build(raw, prohibited_behaviors=remaining)

    def test_the_list_may_be_lengthened(self, raw) -> None:
        extended = [*raw["prohibited_behaviors"], "chasing_a_missed_move"]
        policy = build(raw, prohibited_behaviors=extended)
        assert "chasing_a_missed_move" in policy.prohibited_behaviors


class TestSchemaHygiene:
    def test_unknown_key_is_rejected(self, raw) -> None:
        with pytest.raises(ValidationError):
            build(raw, allow_bigger_size_when_behind=True)

    def test_manifest_is_immutable(self, raw) -> None:
        policy = build(raw)
        with pytest.raises(ValidationError):
            policy.status = "live"

    def test_spread_limit_must_be_positive(self, raw) -> None:
        with pytest.raises(ValidationError):
            build(raw, max_spread_pips=Decimal("0"))
