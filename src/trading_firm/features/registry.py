"""Feature metadata registry (§30.7) — the existing registry, extended.

§30.7 is explicit: extend the existing approved feature and indicator
registry. Do not create a second independent registry. Before this module the
"registry" was two flat lists — family names in `firm.yaml` and qualified ids
in the adaptive policy manifest — with no metadata behind them. This module
adds the metadata as the single source of truth and demotes the flat lists to
validated views: a consistency check (enforced in CI by
`tests/unit/test_feature_registry.py`) proves every id the policy approves
and every family the firm config names is described here.

`AdaptivePolicyManifest.permits_feature` semantics are unchanged — the policy
manifest remains the gate classification consults; this registry is what a
gated id *means*.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "registries" / "features.yaml"
)

_FEATURE_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FeatureRecord(_Strict):
    """§30.7 metadata for one production-capable feature.

    `feature_id` is the qualified `family.name` form the adaptive policy
    approves; the family carries the calculation version (the repo's
    `session_features_v1` convention), so a changed calculation is a new
    family, never a mutation.
    """

    feature_id: str
    status: Literal["research", "shadow", "paper", "production", "retired"]
    asset_classes: list[str]
    instruments: list[str]
    timeframes: list[str]
    calculation_module: str
    required_inputs: list[str]
    lookback_requirements: dict[str, str]
    output_type: str
    null_behavior: str
    warmup_behavior: str
    freshness_policy: str
    purpose: str
    known_failure_modes: list[str]
    leakage_review_status: Literal["not_reviewed", "in_review", "passed"]
    validation_report_ids: list[str]
    owner_approval_id: str | None = None

    @model_validator(mode="after")
    def _shape_and_gates(self) -> FeatureRecord:
        if not _FEATURE_ID.match(self.feature_id):
            raise ValueError(
                f"feature_id {self.feature_id!r} is not family.name form (§30.7)"
            )
        if not self.calculation_module.startswith("trading_firm."):
            raise ValueError(
                f"{self.feature_id}: calculation_module {self.calculation_module!r} "
                f"must name the deterministic module that computes it (§30.7)"
            )
        if self.status == "production":
            problems = []
            if self.owner_approval_id is None:
                problems.append("owner_approval_id is null")
            if self.leakage_review_status != "passed":
                problems.append(f"leakage_review_status is {self.leakage_review_status}")
            if not self.validation_report_ids:
                problems.append("validation_report_ids is empty")
            if problems:
                raise ValueError(
                    f"{self.feature_id}: production status requires approval, a passed "
                    f"leakage review, and validation evidence ({'; '.join(problems)}) "
                    f"(§30.7, §12.7)"
                )
        return self

    @property
    def family(self) -> str:
        return self.feature_id.split(".", 1)[0]


class FeatureRegistry(_Strict):
    version: str
    features: list[FeatureRecord]

    @model_validator(mode="after")
    def _ids_unique(self) -> FeatureRegistry:
        seen: set[str] = set()
        for record in self.features:
            if record.feature_id in seen:
                raise ValueError(f"duplicate feature_id {record.feature_id!r} (§30.7)")
            seen.add(record.feature_id)
        return self

    @property
    def by_id(self) -> Mapping[str, FeatureRecord]:
        return MappingProxyType({r.feature_id: r for r in self.features})

    @property
    def families(self) -> frozenset[str]:
        return frozenset(r.family for r in self.features)

    def missing_metadata(self, approved_ids: list[str]) -> list[str]:
        """Approved ids with no record here — the drift this registry exists
        to make impossible. Non-empty means the flat list and the metadata
        have diverged; CI fails on it."""
        described = self.by_id
        return sorted(
            fid for fid in approved_ids
            if fid not in described or described[fid].status == "retired"
        )


def load_feature_registry(path: str | Path = REGISTRY_PATH) -> FeatureRegistry:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or set(raw) != {"feature_registry"}:
        raise ValueError(f"{path}: expected a single top-level 'feature_registry' key (§30.7)")
    return FeatureRegistry.model_validate(raw["feature_registry"])
