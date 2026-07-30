"""Adaptive-layer types: novelty classes, evidence classes, thesis schema (v2 §5, §6.7, §6.8).

v2 makes the firm opportunity-driven: Senior Traders may construct a
situation-specific thesis rather than invoke a named playbook. The safety of
that freedom rests entirely on two classifications being impossible to fake —
how NEW the idea is (novelty) and how well EVIDENCED it is (evidence class).

Both permission tables are encoded as type-level constraints rather than
runtime checks, following the M-1 precedent: an agent payload that tries to
give an unvalidated idea live exposure fails to construct at all, before any
code reads it. §21 requires "N2/N3 theses cannot place live orders" and "N1
theses cannot receive Exceptional risk" as acceptance criteria; here they are
properties of the type system.
"""

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NoveltyClass(enum.StrEnum):
    """v2 §6.8. How new is the logic? Permissions narrow as novelty rises."""

    N0 = "N0"  # existing validated production playbook
    N1 = "N1"  # new combination of already-validated primitives
    N2 = "N2"  # new indicator, rule, parameterization, or strategy logic
    N3 = "N3"  # exploratory idea without a reproducible specification

    @property
    def may_trade_live(self) -> bool:
        """§6.8: N2 and N3 may NEVER place live orders."""
        return self in (NoveltyClass.N0, NoveltyClass.N1)

    @property
    def may_receive_exceptional(self) -> bool:
        """§6.8: no N1/N2/N3 thesis may receive Exceptional risk."""
        return self is NoveltyClass.N0


class EvidenceClass(enum.StrEnum):
    """v2 §5.2. What the evidence supports — a CEILING on the tier the
    deterministic risk gate may consider, never an authorization of size."""

    E0 = "E0"  # missing, stale, contradictory, or malformed -> reject
    E1 = "E1"  # new hypothesis or untested indicator -> research/shadow only
    E2 = "E2"  # recombination with limited analog support -> paper/tight probation
    E3 = "E3"  # validated playbook with acceptable regime fit -> Standard/Strong
    E4 = "E4"  # robustly validated subtype, strong fit -> High
    E5 = "E5"  # rare exceptional case, all §5.3 gates passed -> Exceptional

    @property
    def max_edge_tier(self) -> int:
        """Maximum EdgeTier value this evidence may unlock (models.EdgeTier)."""
        return {
            EvidenceClass.E0: 0,  # NONE
            EvidenceClass.E1: 0,
            EvidenceClass.E2: 0,
            EvidenceClass.E3: 2,  # STRONG
            EvidenceClass.E4: 3,  # HIGH
            EvidenceClass.E5: 4,  # EXCEPTIONAL
        }[self]

    @property
    def may_trade_live(self) -> bool:
        return self.max_edge_tier > 0


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MarketState(_Strict):
    regime: str = Field(min_length=1)
    volatility_state: str = Field(min_length=1)
    session_phase: str = Field(min_length=1)


class SelectedFeature(_Strict):
    """A feature the trader chose from the approved registry. `observed_value`
    must come from the deterministic engine — §6A forbids inventing one."""

    feature_id: str = Field(min_length=1)  # versioned id
    observed_value: Decimal
    relevance: str = Field(min_length=1)


class HistoricalAnalogs(_Strict):
    query_id: str | None = None
    sample_size: int = Field(ge=0)
    net_outcome_summary: str | None = None


class Thesis(_Strict):
    causal_or_behavioral_rationale: str = Field(min_length=1)
    expected_path: str = Field(min_length=1)
    failure_scenario: str = Field(min_length=1)  # §6.2: must state its own disproof


class TradePlan(_Strict):
    entry_rule: str = Field(min_length=1)
    invalidation_rule: str = Field(min_length=1)
    exit_rule: str = Field(min_length=1)
    expiration_rule: str = Field(min_length=1)


class AdaptiveThesis(_Strict):
    """v2 §6.7 Adaptive Trade Thesis Schema.

    Every field the spec marks required is mandatory and non-empty here: "free-
    form prose may accompany this schema but cannot replace it." A thesis with
    no deterministic evidence is rejected outright (§21 acceptance criterion
    "a narrative-only thesis with no deterministic evidence is rejected").
    """

    thesis_id: str = Field(min_length=1)
    trader_id: str = Field(pattern=r"^(alpha|beta)$")
    timestamp_utc: dt.datetime
    instrument: str = Field(min_length=1)
    direction: str = Field(pattern=r"^(long|short|none)$")
    market_state: MarketState
    observations: list[str] = Field(default_factory=list)
    selected_features: list[SelectedFeature] = Field(default_factory=list)
    specialist_consultations: list[str] = Field(default_factory=list)
    historical_analogs: HistoricalAnalogs | None = None
    thesis: Thesis
    trade_plan: TradePlan
    novelty_class: NoveltyClass
    evidence_class: EvidenceClass
    estimated_costs: Decimal = Field(ge=0)
    expected_value_basis: str = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list)
    confidence_calibration_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def _deterministic_evidence_required(self) -> AdaptiveThesis:
        # §21: narrative-only candidates are rejected. A directional thesis must
        # rest on at least one deterministically computed feature.
        if self.direction != "none" and not self.selected_features:
            raise ValueError(
                "a directional thesis must cite at least one deterministically "
                "computed feature from the approved registry — narrative-only "
                "candidates are rejected (§6A, §21)"
            )
        return self

    @model_validator(mode="after")
    def _timestamp_aware(self) -> AdaptiveThesis:
        if self.timestamp_utc.tzinfo is None:
            raise ValueError("timestamp_utc must be timezone-aware (§10.3)")
        return self

    @property
    def may_trade_live(self) -> bool:
        """Both gates must pass: novelty (§6.8) and evidence (§5.2)."""
        return self.novelty_class.may_trade_live and self.evidence_class.may_trade_live

    @property
    def max_edge_tier(self) -> int:
        """The tier ceiling this thesis may unlock — the STRICTER of the two
        classifications. Exceptional additionally requires N0 (§6.8)."""
        ceiling = self.evidence_class.max_edge_tier
        if not self.novelty_class.may_receive_exceptional:
            ceiling = min(ceiling, 3)  # below EXCEPTIONAL
        if not self.novelty_class.may_trade_live:
            ceiling = 0
        return ceiling
