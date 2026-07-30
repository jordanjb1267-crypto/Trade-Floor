"""Strategy manifest schema and loader (§11).

Manifests are declarative and versioned; production manifests are immutable
(any modification creates a new version). Risk permissions are granted only
through the §12.5 promotion process — the schema enforces that a manifest
cannot claim permissions its status has not earned.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskPermissions(_StrictModel):
    standard: bool = False
    strong: bool = False
    high: bool = False
    exceptional: bool = False

    @property
    def any_granted(self) -> bool:
        return self.standard or self.strong or self.high or self.exceptional


class StrategyManifest(_StrictModel):
    strategy_id: str
    version: str
    status: Literal["research", "replay", "shadow", "paper", "live"]
    instruments: list[str]
    session_definition: str
    features: list[str]
    entry_rules: list[str]
    invalidation_rules: list[str]
    exit_rules: list[str]
    expiration_rules: list[str]
    regime_filters: list[str]
    news_filters: list[str]
    spread_limits: dict[str, float]
    slippage_limits: dict[str, float]
    params: dict[str, str | int | float] = {}
    risk_permissions: RiskPermissions
    validation_record_id: str | None = None
    promotion_record_id: str | None = None

    @model_validator(mode="after")
    def _permissions_follow_promotion(self) -> StrategyManifest:
        if self.status != "live" and self.risk_permissions.any_granted:
            raise ValueError(
                f"{self.strategy_id} v{self.version}: risk permissions require live status "
                "earned through the promotion process (§11, §12.5)"
            )
        if self.status == "live" and self.promotion_record_id is None:
            raise ValueError(
                f"{self.strategy_id} v{self.version}: live status requires a signed "
                "promotion record (§12.5)"
            )
        if self.status in ("paper", "live") and self.validation_record_id is None:
            raise ValueError(
                f"{self.strategy_id} v{self.version}: {self.status} status requires a "
                "validation record (§12.2)"
            )
        return self


def load_manifests(directory: str | Path) -> dict[str, StrategyManifest]:
    """Load and validate every *.yaml manifest in a directory, keyed by strategy_id."""
    manifests: dict[str, StrategyManifest] = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        manifest = StrategyManifest.model_validate(yaml.safe_load(path.read_text()))
        if manifest.strategy_id in manifests:
            raise ValueError(f"duplicate strategy_id {manifest.strategy_id} in {directory}")
        manifests[manifest.strategy_id] = manifest
    return manifests
