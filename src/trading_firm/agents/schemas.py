"""Structured agent-output schemas (§6.5): every agent payload is
machine-validated here before anything downstream may read it.

The M-1 containment rule is a TYPE CONSTRAINT: tier adjustments are bounded
at ≤ 0, so an LLM output attempting to raise a tier fails validation before
any deterministic code ever sees it. Unknown fields are rejected everywhere.
"""

from __future__ import annotations

import datetime as dt
import enum
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_firm.models import cents


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetimes are forbidden in agent payloads (§10.3)")
    return value


# --------------------------------------------------------------- context agent


class RegimeLabel(enum.StrEnum):
    TREND = "trend"
    BALANCE = "balance"
    COMPRESSION = "compression"
    EXPANSION = "expansion"
    ELEVATED_VOLATILITY = "elevated_volatility"
    SUPPRESSED_VOLATILITY = "suppressed_volatility"
    EVENT_DISTORTED = "event_distorted"


class CalendarEvent(_StrictModel):
    time_utc: dt.datetime
    currency: str
    impact: Literal["High", "Medium", "Low"]
    name: str
    blackout: bool

    _aware = field_validator("time_utc")(_require_aware)


class StructuralLevel(_StrictModel):
    price: Decimal
    level_type: str
    timeframe: str
    validation_basis: str


class ContextReport(_StrictModel):
    """Context Analyst output (§6.3.E). calendar_state != 'fresh' fails closed."""

    regime: RegimeLabel
    regime_evidence: str
    calendar_state: Literal["fresh", "stale", "missing"]
    events: list[CalendarEvent]
    levels: list[StructuralLevel]
    data_freshness_doubts: list[str] = []

    @property
    def news_state_known(self) -> bool:
        return self.calendar_state == "fresh" and not self.data_freshness_doubts


# ------------------------------------------------------------ strategist agent


class LlmAssessedComponent(enum.StrEnum):
    """The §5.1 components an LLM may assess — and only ever lower."""

    REGIME_MATCH = "regime_match"
    STRUCTURAL_CONFIRMATION = "structural_confirmation"
    HIGHER_TIMEFRAME_ALIGNMENT = "higher_timeframe_alignment"


class TierAdjustment(_StrictModel):
    """M-1 as a type: adjustment is bounded at ≤ 0. Raising is unrepresentable."""

    component: LlmAssessedComponent
    adjustment: int = Field(le=0)
    evidence: str


class StrategistAssessment(_StrictModel):
    """Session Strategist output (§6.2.D). direction None means no setup (§0.6)."""

    strategy_id: str
    strategy_version: str
    instrument: str
    direction: Literal["LONG", "SHORT"] | None
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    target_price: Decimal | None = None
    expiration_utc: dt.datetime | None = None
    feature_readings: dict[str, str] = {}
    tier_adjustments: list[TierAdjustment] = []
    no_setup_reason: str | None = None

    @field_validator("expiration_utc")
    @classmethod
    def _aware_expiry(cls, value: dt.datetime | None) -> dt.datetime | None:
        return _require_aware(value) if value is not None else None

    def model_post_init(self, _context) -> None:  # noqa: ANN001
        if self.direction is not None:
            missing = [
                name
                for name in ("entry_price", "stop_price", "expiration_utc")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    f"a directional assessment requires {missing} (§3.3: stop comes first)"
                )
        elif self.no_setup_reason is None:
            raise ValueError("no-setup assessments must state a reason (§0.6)")


# -------------------------------------------------------------------- CRO agent


class CroVerdict(_StrictModel):
    """Chief Risk Officer output (§6.1.C): advisory veto with citations."""

    verdict: Literal["REJECT", "NO_OBJECTION"]
    rule_citations: list[str] = Field(min_length=1)
    conditions: list[str] = []
    reasoning: str


# --------------------------------------------------------- trade approval card


class ApprovalCard(_StrictModel):
    """§13 trade approval card — every field the owner must see, none optional."""

    instrument: str
    strategy_id: str
    strategy_version: str
    direction: Literal["LONG", "SHORT"]
    proposed_entry: Decimal
    technical_stop: Decimal
    target: Decimal
    exit_method: str
    maximum_dollar_loss: Decimal
    position_size_units: int
    estimated_spread_pips: Decimal
    estimated_commission_usd: Decimal
    estimated_slippage_pips: Decimal
    expected_net_reward_to_risk: Decimal
    edge_tier: str
    edge_components: dict[str, str]
    regime: RegimeLabel
    economic_event_status: str
    candidate_expiration_utc: dt.datetime
    risk_engine_status: str
    session_loss_capacity_usd: Decimal
    weekly_loss_capacity_usd: Decimal

    _aware = field_validator("candidate_expiration_utc")(_require_aware)

    def render_markdown(self) -> str:
        lines = [
            f"## Trade approval — {self.instrument} {self.direction}",
            f"strategy: {self.strategy_id} v{self.strategy_version} | tier: {self.edge_tier}",
            f"entry {self.proposed_entry} | stop {self.technical_stop} | "
            f"target {self.target} ({self.exit_method})",
            f"max loss ${cents(self.maximum_dollar_loss)} | size {self.position_size_units} units"
            f" | net R:R {self.expected_net_reward_to_risk}",
            f"costs: spread {self.estimated_spread_pips}p, "
            f"commission ${self.estimated_commission_usd}, "
            f"slippage {self.estimated_slippage_pips}p",
            f"regime {self.regime.value} | events: {self.economic_event_status}",
            f"risk engine: {self.risk_engine_status}",
            f"capacity: session ${cents(self.session_loss_capacity_usd)}, "
            f"weekly ${cents(self.weekly_loss_capacity_usd)}",
            f"expires {self.candidate_expiration_utc.isoformat()}",
        ]
        return "\n".join(lines)


# ------------------------------------------------------------- learning agent


class OutcomeLabel(enum.StrEnum):
    GOOD_WIN = "good_win"
    LUCKY_WIN = "lucky_win"
    GOOD_LOSS = "good_loss"
    BAD_LOSS = "bad_loss"
    EXECUTION_ERROR = "execution_error"
    STRATEGY_ERROR = "strategy_error"
    RISK_ERROR = "risk_error"
    DATA_ERROR = "data_error"
    OPERATIONAL_ERROR = "operational_error"


class OutcomeClassification(_StrictModel):
    reference: str  # trade/candidate/session identifier
    label: OutcomeLabel
    reasoning: str


class ChallengerHypothesis(_StrictModel):
    hypothesis: str
    evidence_required: str  # tied to the §12.6 table


class PostSessionReport(_StrictModel):
    """Learning and Audit Director output (§6.4.F)."""

    session_date: dt.date
    classifications: list[OutcomeClassification]
    process_findings: list[str]
    drift_observations: list[str]
    challenger_hypotheses: list[ChallengerHypothesis]


# ------------------------------------------------- surveillance agents (§30)


class SurveillanceOverallState(enum.StrEnum):
    NORMAL = "NORMAL"
    MATERIAL_CHANGE = "MATERIAL_CHANGE"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class SurveillanceSituationReport(_StrictModel):
    """Technical Surveillance Lead output (§30.13): a concise,
    evidence-grounded current-state report bound to one Market State Object."""

    report_id: str
    market_state_id: str
    agent_id: str
    agent_version: str
    generated_at_utc: dt.datetime
    overall_state: SurveillanceOverallState
    material_changes: list[str]
    active_market_drivers: list[str]
    technical_observations: list[str]
    macro_observations: list[str]
    news_observations: list[str]
    cross_market_observations: list[str]
    contradictions: list[str]
    data_limitations: list[str]
    specialists_to_consult: list[str]
    escalation_required: bool
    expiration_utc: dt.datetime

    _aware_generated = field_validator("generated_at_utc")(_require_aware)
    _aware_expiry = field_validator("expiration_utc")(_require_aware)


class OpportunityAlert(_StrictModel):
    """Opportunity Alert Agent output (§30.13).

    `trade_direction` is annotated `None` — the same move as TierAdjustment's
    `le=0`: §30.13 says trade_direction must remain null at the
    surveillance-alert layer, and here a non-null direction is a validation
    error rather than a review finding. An alert says what changed, never
    what to do about it (§30.3.I: no BUY or SELL instructions).
    """

    alert_id: str
    market_state_id: str
    severity: Literal["INFO", "WATCH", "MATERIAL", "CRITICAL"]
    instrument_ids: list[str]
    change_type: str
    what_changed: str
    supporting_observation_ids: list[str]
    conflicting_observation_ids: list[str]
    data_quality_status: str
    suggested_recipients: list[str]
    trade_direction: None = None
    expires_at_utc: dt.datetime

    _aware_expiry = field_validator("expires_at_utc")(_require_aware)


class NewsRelevanceReview(_StrictModel):
    """News Verification and Relevance Agent output (§30.13). The
    recommended states are all restrictive or neutral — there is no
    'trade this news' member to output."""

    review_id: str
    news_item_id: str
    verification_state: Literal[
        "UNVERIFIED", "SINGLE_SOURCE", "CORROBORATED", "OFFICIAL_SOURCE",
        "CONFLICTING", "CORRECTED", "RETRACTED",
    ]
    event_time_utc: dt.datetime | None = None
    publication_time_utc: dt.datetime
    potentially_affected_instruments: list[str]
    materiality: Literal["NONE", "LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    already_known_or_recirculated: bool
    conflicting_facts: list[str]
    pricing_assessment: Literal[
        "UNKNOWN", "POSSIBLY_PRICED", "REACTION_ONGOING", "NOT_OBSERVED"
    ]
    recommended_state: Literal["IGNORE", "WATCH", "ESCALATE", "PAUSE_NEW_ENTRIES"]

    _aware_published = field_validator("publication_time_utc")(_require_aware)

    @field_validator("event_time_utc")
    @classmethod
    def _aware_event_or_none(cls, value: dt.datetime | None) -> dt.datetime | None:
        return None if value is None else _require_aware(value)

    @property
    def can_support_material_alert(self) -> bool:
        """§30.8: an unverified item cannot drive a MATERIAL alert."""
        return self.verification_state in ("CORROBORATED", "OFFICIAL_SOURCE")


# ------------------------------------------------------------ validation gate

_SCHEMAS = {
    "context_report": ContextReport,
    "strategist_assessment": StrategistAssessment,
    "cro_verdict": CroVerdict,
    "approval_card": ApprovalCard,
    "post_session_report": PostSessionReport,
    "surveillance_situation_report": SurveillanceSituationReport,
    "opportunity_alert": OpportunityAlert,
    "news_relevance_review": NewsRelevanceReview,
}


def validate_agent_payload(kind: str, payload: dict):
    """The single gate through which agent output enters the runtime (§6.5)."""
    schema = _SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"unknown agent payload kind: {kind}")
    return schema.model_validate(payload)
