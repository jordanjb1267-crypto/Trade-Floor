"""Feature metadata registry (§30.7): one registry, with the flat lists as
validated views. The consistency tests here are the CI enforcement of "do not
create a second independent registry" — if the policy manifest or firm.yaml
approves an id this file does not describe, the build fails."""

import pytest
import yaml
from pydantic import ValidationError

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.features.registry import (
    REGISTRY_PATH,
    FeatureRecord,
    FeatureRegistry,
    load_feature_registry,
)

ADAPTIVE_POLICY_PATH = BASE_CONFIG_PATH.parents[1] / "research" / "adaptive_policy.yaml"


@pytest.fixture(scope="module")
def registry() -> FeatureRegistry:
    return load_feature_registry(REGISTRY_PATH)


def _raw_record(**overrides) -> dict:
    base = dict(
        feature_id="session_features_v1.test_feature",
        status="research",
        asset_classes=["FX_SPOT"],
        instruments=["GBP_USD"],
        timeframes=["M5"],
        calculation_module="trading_firm.features.engine",
        required_inputs=["m5_bars"],
        lookback_requirements={"window": "asian"},
        output_type="pips",
        null_behavior="absent",
        warmup_behavior="full_window",
        freshness_policy="per_session",
        purpose="test",
        known_failure_modes=[],
        leakage_review_status="not_reviewed",
        validation_report_ids=[],
        owner_approval_id=None,
    )
    base.update(overrides)
    return base


class TestConsistencyWithTheFlatLists:
    def test_every_policy_approved_id_is_described(self, registry) -> None:
        policy = yaml.safe_load(ADAPTIVE_POLICY_PATH.read_text())
        missing = registry.missing_metadata(policy["approved_feature_registry"])
        assert missing == [], (
            f"adaptive_policy.yaml approves {missing} but the metadata registry "
            f"does not describe them — the two-registry drift §30.7 forbids"
        )

    def test_every_firm_family_is_described(self, registry) -> None:
        firm = load_config(BASE_CONFIG_PATH)
        families = set(firm.feature_registry.research_allowed) | set(
            firm.feature_registry.production_allowed
        )
        undescribed = sorted(families - registry.families)
        assert undescribed == [], (
            f"firm.yaml names feature families {undescribed} with no metadata "
            f"records (§30.7)"
        )

    def test_nothing_ships_at_production_status(self, registry) -> None:
        assert not any(r.status == "production" for r in registry.features)


class TestRefusedStates:
    def test_production_requires_approval_review_and_evidence(self) -> None:
        with pytest.raises(ValidationError, match="§30.7"):
            FeatureRecord.model_validate(_raw_record(status="production"))

    def test_production_with_the_full_evidence_chain_passes(self) -> None:
        record = FeatureRecord.model_validate(
            _raw_record(
                status="production",
                owner_approval_id="governance/approvals/example.md",
                leakage_review_status="passed",
                validation_report_ids=["reports/validation/example.md"],
            )
        )
        assert record.status == "production"

    @pytest.mark.parametrize(
        "bad_id", ["no_family", "Family.name", "session_features_v1.", "a.b.c"]
    )
    def test_unqualified_or_prose_ids_rejected(self, bad_id) -> None:
        with pytest.raises(ValidationError, match="family.name"):
            FeatureRecord.model_validate(_raw_record(feature_id=bad_id))

    def test_a_calculation_module_outside_the_firm_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="deterministic module"):
            FeatureRecord.model_validate(_raw_record(calculation_module="numpy"))

    def test_duplicates_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            FeatureRegistry.model_validate(
                {"version": "1.0.0", "features": [_raw_record(), _raw_record()]}
            )

    def test_a_retired_feature_counts_as_missing(self, registry) -> None:
        retired = FeatureRegistry.model_validate(
            {"version": "1.0.0", "features": [_raw_record(status="retired")]}
        )
        assert retired.missing_metadata(["session_features_v1.test_feature"]) == [
            "session_features_v1.test_feature"
        ]
