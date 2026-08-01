"""Surveillance configuration schema (§30.12).

Same contract as `test_config.py`: the shipped layers must load, and every
constitutional invariant must be enforced by the schema — a config edited to
contradict §30 must FAIL to load, with a §-citation in the error.
"""

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from trading_firm.surveillance.config import (
    BASE_SURVEILLANCE_CONFIG_PATH,
    AlertSeverity,
    SurveillanceConfig,
    load_surveillance_config,
)

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def base_raw() -> dict:
    return yaml.safe_load(BASE_SURVEILLANCE_CONFIG_PATH.read_text())


@pytest.fixture(scope="module")
def base_config() -> SurveillanceConfig:
    return load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)


def _mutated(base_raw: dict, dotted: str, value) -> SurveillanceConfig:
    raw = copy.deepcopy(base_raw)["surveillance"]
    node = raw
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node[key]
    node[leaf] = value
    return SurveillanceConfig.model_validate(raw)


class TestShippedLayersLoad:
    def test_base_loads_disabled_observe_only(self, base_config) -> None:
        assert base_config.enabled is False
        assert base_config.mode == "observe_only"
        assert base_config.influence_candidate_generation is False
        assert base_config.influence_live_eligibility is False

    def test_research_layer_loads(self) -> None:
        cfg = load_surveillance_config(REPO / "config" / "research" / "surveillance.yaml")
        assert cfg.enabled is False

    def test_no_live_layer_exists(self) -> None:
        """§30.12: the live surveillance layer is created in Phase H by the
        owner, not by this build — its absence is part of the contract."""
        assert not (REPO / "config" / "live" / "surveillance.yaml").exists()

    def test_phone_delivery_is_severe_only(self, base_config) -> None:
        assert base_config.alerts.telegram_minimum_severity is AlertSeverity.MATERIAL


class TestTheMasterSwitchDominates:
    """§30.12: while `enabled` is false every sub-block is inert regardless of
    its own flags. Consumers read the *_active properties."""

    def test_disabled_master_makes_everything_inactive(self, base_config) -> None:
        # technical.enabled and alerts.enabled are TRUE in the baseline file,
        # which is exactly what makes this test meaningful.
        assert base_config.technical.enabled is True
        assert base_config.alerts.enabled is True
        assert base_config.technical_active is False
        assert base_config.alerts_active is False
        assert base_config.publishing_active is False
        assert base_config.macro_active is False
        assert base_config.news_active is False
        assert base_config.cross_market_active is False
        assert base_config.claude_agents_active is False
        assert base_config.contradiction_monitoring_active is False

    def test_enabled_master_activates_enabled_blocks_only(self, base_raw) -> None:
        cfg = _mutated(base_raw, "enabled", True)
        assert cfg.technical_active is True
        assert cfg.publishing_active is True
        assert cfg.macro_active is False  # macro.enabled is false in the file
        assert cfg.news_active is False

    def test_contradiction_monitoring_needs_all_three_switches(self, base_raw) -> None:
        raw = copy.deepcopy(base_raw)["surveillance"]
        raw["enabled"] = True
        raw["positions"]["contradiction_monitoring_enabled"] = True
        cfg = SurveillanceConfig.model_validate(raw)
        # post_entry_monitoring_enabled is still false: not active.
        assert cfg.contradiction_monitoring_active is False


class TestIllegalStatesAreUnrepresentable:
    @pytest.mark.parametrize(
        "dotted",
        ["influence_candidate_generation", "influence_live_eligibility"],
    )
    def test_influence_flags_refuse_true(self, base_raw, dotted) -> None:
        with pytest.raises(ValidationError, match="§30.12"):
            _mutated(base_raw, dotted, True)

    def test_fail_open_component_failure_rejected(self, base_raw) -> None:
        with pytest.raises(ValidationError, match="never be treated as confirming"):
            _mutated(base_raw, "fail_closed_on_required_component_failure", False)

    @pytest.mark.parametrize("section", ["macro", "news"])
    def test_fail_open_unknown_state_rejected(self, base_raw, section) -> None:
        with pytest.raises(ValidationError):
            _mutated(base_raw, f"{section}.unknown_state_behavior", "fail_open")

    def test_severe_throttle_bypass_refuses_false(self, base_raw) -> None:
        with pytest.raises(ValidationError, match="never be\\s+suppressed"):
            _mutated(base_raw, "alerts.severe_alerts_never_throttled", False)

    @pytest.mark.parametrize("value", ["INFO", "WATCH"])
    def test_phone_delivery_below_material_rejected(self, base_raw, value) -> None:
        with pytest.raises(ValidationError, match="owner decision"):
            _mutated(base_raw, "alerts.telegram_minimum_severity", value)

    def test_automatic_order_changes_refuse_true(self, base_raw) -> None:
        with pytest.raises(ValidationError, match="order"):
            _mutated(base_raw, "positions.automatic_order_changes_enabled", True)

    @pytest.mark.parametrize("dotted", ["options_scaffold.enabled", "options_scaffold.registered"])
    def test_options_scaffold_refuses_activation(self, base_raw, dotted) -> None:
        with pytest.raises(ValidationError, match="§30.11"):
            _mutated(base_raw, dotted, True)

    def test_unregistered_asset_class_rejected(self, base_raw) -> None:
        with pytest.raises(ValidationError, match="FX_SPOT is the only"):
            _mutated(base_raw, "asset_classes_enabled", ["FX_SPOT", "EQUITY_OPTIONS"])

    def test_unverified_material_news_rejected(self, base_raw) -> None:
        with pytest.raises(ValidationError, match="unverified"):
            _mutated(base_raw, "news.verification_required_for_material_alert", False)

    def test_unregistered_feature_observation_rejected(self, base_raw) -> None:
        with pytest.raises(ValidationError, match="§30.7"):
            _mutated(base_raw, "technical.approved_feature_registry_only", False)

    def test_a_mode_other_than_observe_only_is_unrepresentable(self, base_raw) -> None:
        with pytest.raises(ValidationError):
            _mutated(base_raw, "mode", "influence")

    def test_unknown_keys_rejected(self, base_raw) -> None:
        raw = copy.deepcopy(base_raw)["surveillance"]
        raw["enable_everything"] = True
        with pytest.raises(ValidationError):
            SurveillanceConfig.model_validate(raw)

    def test_a_file_without_the_surveillance_key_is_rejected(self, tmp_path) -> None:
        bad = tmp_path / "surveillance.yaml"
        bad.write_text("enabled: false\n")
        with pytest.raises(ValueError, match="§30.12"):
            load_surveillance_config(bad)


class TestSeverityOrdering:
    def test_ranks_are_total_and_ordered(self) -> None:
        ranks = [s.rank for s in (
            AlertSeverity.INFO, AlertSeverity.WATCH,
            AlertSeverity.MATERIAL, AlertSeverity.CRITICAL,
        )]
        assert ranks == sorted(ranks) and len(set(ranks)) == 4

    def test_at_least_is_the_delivery_comparison(self) -> None:
        assert AlertSeverity.CRITICAL.at_least(AlertSeverity.MATERIAL)
        assert AlertSeverity.MATERIAL.at_least(AlertSeverity.MATERIAL)
        assert not AlertSeverity.WATCH.at_least(AlertSeverity.MATERIAL)


class TestValidateConfigScriptCoversSurveillance:
    def test_the_ci_validator_discovers_the_new_layers(self) -> None:
        """The CI step's glob was firm.yaml-only; a surveillance.yaml that no
        tool loads is how a config drifts stale with CI green."""
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "validate_config.py")],
            capture_output=True, text=True, cwd=REPO,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "config/base/surveillance.yaml" in result.stdout
        assert "config/research/surveillance.yaml" in result.stdout
