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


# ------------------------------------------------------------ validation gate

_SCHEMAS = {
    "context_report": ContextReport,
    "strategist_assessment": StrategistAssessment,
    "cro_verdict": CroVerdict,
    "approval_card": ApprovalCard,
    "post_session_report": PostSessionReport,
}


def validate_agent_payload(kind: str, payload: dict):
    """The single gate through which agent output enters the runtime (§6.5)."""
    schema = _SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"unknown agent payload kind: {kind}")
    return schema.model_validate(payload)
