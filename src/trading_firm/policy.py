"""Adaptive policy manifest (§11) — what senior traders may combine live.

§11 requires a separate versioned manifest, under the same promotion and
approval controls as a strategy manifest, governing the registries a senior
trader may draw on and the novelty classes it may take live. Like a strategy
manifest, a production version is immutable: any modification creates a new
version.

The validators here refuse to construct a policy that contradicts a §0 iron
rule or a ratified amendment, in the same style as `config.py`: rejection with
a §-citation an operator can follow during an incident.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_firm.adaptive import EvidenceClass, NoveltyClass

# §11 names these five; the list is a floor, not a ceiling.
REQUIRED_PROHIBITED_BEHAVIORS = frozenset(
    {
        "intraday_parameter_fitting",
        "unversioned_indicator_creation",
        "lookahead_data",
        "post_loss_risk_escalation",
        "narrative_only_edge_claim",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AdaptivePolicyManifest(_StrictModel):
    """§11 adaptive policy manifest."""

    adaptive_policy_id: str
    version: str
    status: Literal["research", "replay", "shadow", "paper", "live"]
    approved_feature_registry: list[str]
    approved_indicator_registry: list[str]
    approved_trading_primitives: list[str]
    allowed_novelty_classes_live: list[NoveltyClass]
    limited_probation_classes: list[NoveltyClass]
    required_analog_sample_size: int | None = None
    max_spread_pips: Decimal = Field(gt=0)
    required_evidence_class_by_risk_tier: dict[str, EvidenceClass]
    prohibited_behaviors: list[str]
    validation_record_id: str | None = None
    promotion_record_id: str | None = None

    @field_validator("allowed_novelty_classes_live")
    @classmethod
    def _no_unvalidated_live(cls, value: list[NoveltyClass]) -> list[NoveltyClass]:
        illegal = [c for c in value if not c.may_trade_live]
        if illegal:
            raise ValueError(
                f"allowed_novelty_classes_live may never contain {[c.value for c in illegal]}: "
                f"N2 and N3 theses cannot place live orders (§6.8)"
            )
        return value

    @field_validator("limited_probation_classes")
    @classmethod
    def _probation_is_not_a_backdoor(cls, value: list[NoveltyClass]) -> list[NoveltyClass]:
        illegal = [c for c in value if not c.may_trade_live]
        if illegal:
            raise ValueError(
                f"limited_probation_classes may never contain "
                f"{[c.value for c in illegal]}: probation is not a route around §6.8"
            )
        return value

    @field_validator("prohibited_behaviors")
    @classmethod
    def _floor_is_not_negotiable(cls, value: list[str]) -> list[str]:
        missing = sorted(REQUIRED_PROHIBITED_BEHAVIORS - set(value))
        if missing:
            raise ValueError(
                f"prohibited_behaviors is missing {missing}: §11 names these explicitly "
                f"and a policy may add to the list but never shorten it"
            )
        return value

    @model_validator(mode="after")
    def _exceptional_requires_e5(self) -> AdaptivePolicyManifest:
        required = self.required_evidence_class_by_risk_tier
        unknown = sorted(set(required) - {"standard", "strong", "high", "exceptional"})
        if unknown:
            raise ValueError(
                f"required_evidence_class_by_risk_tier has unknown tiers {unknown}; "
                f"the ladder is standard/strong/high/exceptional (§3.2)"
            )
        exceptional = required.get("exceptional")
        if exceptional is not None and exceptional is not EvidenceClass.E5:
            raise ValueError(
                f"required_evidence_class_by_risk_tier['exceptional'] is "
                f"{exceptional.value}; Exceptional risk requires E5 (§5.2, §5.3)"
            )
        return self

    @model_validator(mode="after")
    def _permissions_follow_promotion(self) -> AdaptivePolicyManifest:
        # Mirrors StrategyManifest: a policy change is a production change and
        # carries the same §12.5 controls.
        if self.status != "live" and self.allowed_novelty_classes_live:
            raise ValueError(
                f"{self.adaptive_policy_id} v{self.version}: allowed_novelty_classes_live "
                f"requires live status earned through the promotion process (§11, §12.5)"
            )
        if self.status == "live" and self.promotion_record_id is None:
            raise ValueError(
                f"{self.adaptive_policy_id} v{self.version}: live status requires a signed "
                f"promotion record (§12.5)"
            )
        if self.status in ("paper", "live") and self.validation_record_id is None:
            raise ValueError(
                f"{self.adaptive_policy_id} v{self.version}: {self.status} status requires a "
                f"validation record (§12.2)"
            )
        return self

    def permits_feature(self, feature_id: str) -> bool:
        return feature_id in self.approved_feature_registry


def load_adaptive_policy(path: str | Path) -> AdaptivePolicyManifest:
    return AdaptivePolicyManifest.model_validate(yaml.safe_load(Path(path).read_text()))
