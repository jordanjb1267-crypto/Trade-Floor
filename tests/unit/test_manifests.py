"""Strategy manifest tests (§11: declarative, versioned, permissions follow promotion)."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from trading_firm.strategies import StrategyManifest, load_manifests

MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "research" / "strategies"


@pytest.fixture(scope="module")
def breakout_raw() -> dict:
    return yaml.safe_load((MANIFEST_DIR / "london_breakout.yaml").read_text())


class TestResearchManifestsLoad:
    def test_all_three_strategies_present(self) -> None:
        manifests = load_manifests(MANIFEST_DIR)
        assert set(manifests) == {
            "london_breakout",
            "asian_range_sweep_reversal",
            "london_continuation",
        }
        for manifest in manifests.values():
            assert manifest.status == "research"
            assert not manifest.risk_permissions.any_granted


class TestPromotionInvariants:
    def test_research_manifest_cannot_claim_permissions(self, breakout_raw: dict) -> None:
        raw = dict(breakout_raw)
        raw["risk_permissions"] = {**raw["risk_permissions"], "standard": True}
        with pytest.raises(ValidationError, match="promotion"):
            StrategyManifest.model_validate(raw)

    def test_live_status_requires_promotion_record(self, breakout_raw: dict) -> None:
        raw = dict(breakout_raw)
        raw["status"] = "live"
        raw["validation_record_id"] = "VAL-1"
        with pytest.raises(ValidationError, match="promotion record"):
            StrategyManifest.model_validate(raw)

    def test_paper_status_requires_validation_record(self, breakout_raw: dict) -> None:
        raw = dict(breakout_raw)
        raw["status"] = "paper"
        with pytest.raises(ValidationError, match="validation record"):
            StrategyManifest.model_validate(raw)

    def test_unknown_fields_rejected(self, breakout_raw: dict) -> None:
        raw = dict(breakout_raw)
        raw["surprise"] = 1
        with pytest.raises(ValidationError):
            StrategyManifest.model_validate(raw)
