"""Market State Object and components (§30.4) — the market side only.

Everything in this module is a pure function of the market: no equity, no
P&L, no position state, no capacity. The post-entry types (thesis monitoring
plans, contradictions) live in `surveillance/monitoring.py` precisely so this
module can sit in the pressure-blind guard list (§5.1 [A-2]) — the type
boundary, not reviewer discipline, is what keeps firm state out of anything
that later feeds classification.

Checksums reuse the packet module's canonical serializer, so a Market State
Object's identity is deterministic across processes the same way the Market
State Packet's is (§30.4: Alpha and Beta receive the same object ID and
checksum for their independent first pass).
"""

from __future__ import annotations

import datetime as dt
import enum
import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_firm.packet import _digest

MARKET_STATE_SCHEMA_VERSION = "market_state_object_v1"

_FEATURE_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_INSTRUMENT_ID = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError(
            "naive datetimes are forbidden in Market State Objects: every timestamp "
            "is UTC or carries an explicit zone (§30.4, C-2)"
        )
    return value


class SurveillanceRegime(enum.StrEnum):
    """§30.3.E controlled regime vocabulary — nine labels, no prose."""

    TRENDING = "TRENDING"
    MEAN_REVERTING = "MEAN_REVERTING"
    COMPRESSING = "COMPRESSING"
    EXPANDING = "EXPANDING"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    ILLIQUID = "ILLIQUID"
    DISLOCATED = "DISLOCATED"
    TRANSITIONAL = "TRANSITIONAL"
    INDETERMINATE = "INDETERMINATE"


class EvidenceType(enum.StrEnum):
    """§30.3.D: inference can never impersonate observation."""

    OBSERVED = "OBSERVED"
    BROKER_PROXY = "BROKER_PROXY"
    PRICE_ACTION_INFERENCE = "PRICE_ACTION_INFERENCE"
    UNAVAILABLE = "UNAVAILABLE"


class DataQualityStatus(enum.StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class NewsPollState(enum.StrEnum):
    """§30.8: the absence of fetched news does not prove the absence of
    relevant news — the six states keep the difference representable."""

    NO_MATERIAL_ITEMS_FOUND = "NO_MATERIAL_ITEMS_FOUND"
    SOURCE_HEALTHY_NO_ITEMS = "SOURCE_HEALTHY_NO_ITEMS"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    POLL_FAILED = "POLL_FAILED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    UNKNOWN = "UNKNOWN"

    @property
    def is_confirming(self) -> bool:
        """Only a healthy poll that found nothing counts as 'no news'. Every
        other state is uncertainty, and uncertainty never confirms (§30.1
        rule 8)."""
        return self in (
            NewsPollState.NO_MATERIAL_ITEMS_FOUND,
            NewsPollState.SOURCE_HEALTHY_NO_ITEMS,
        )


class VerificationState(enum.StrEnum):
    """§30.3.H news verification vocabulary."""

    UNVERIFIED = "UNVERIFIED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    CORROBORATED = "CORROBORATED"
    OFFICIAL_SOURCE = "OFFICIAL_SOURCE"
    CONFLICTING = "CONFLICTING"
    CORRECTED = "CORRECTED"
    RETRACTED = "RETRACTED"


class SessionState(_Strict):
    """§30.4 session component. No local wall-clock strings (C-2): the
    session date plus the London anchor derive every boundary."""

    named_session: Literal["LONDON"]
    phase: Literal["PRE_SESSION", "ACTIVE", "POST_CUTOFF", "CLOSED"]
    session_date: dt.date
    anchor_timezone: Literal["Europe/London"]


class RegimeState(_Strict):
    intraday: SurveillanceRegime
    session: SurveillanceRegime
    daily: SurveillanceRegime
    evidence_feature_ids: list[str]
    classifier_version: str

    @field_validator("evidence_feature_ids")
    @classmethod
    def _evidence_is_registry_shaped(cls, value: list[str]) -> list[str]:
        bad = [f for f in value if not _FEATURE_ID.match(f)]
        if bad:
            raise ValueError(
                f"regime evidence {bad} is not qualified feature ids: a regime claim "
                f"cites the registry, never prose (§30.3, §30.7)"
            )
        return value

    @model_validator(mode="after")
    def _labels_need_evidence(self) -> RegimeState:
        substantive = {r for r in (self.intraday, self.session, self.daily)}
        if substantive != {SurveillanceRegime.INDETERMINATE} and not self.evidence_feature_ids:
            raise ValueError(
                "a regime label other than INDETERMINATE requires evidence feature ids "
                "(§30.3.E); a label with no evidence is prose wearing a vocabulary"
            )
        return self


class KeyLevel(_Strict):
    level_id: str
    price: Decimal
    kind: str

    @field_validator("level_id", "kind")
    @classmethod
    def _reproducible(cls, value: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_.]*$", value):
            raise ValueError(f"{value!r} is not a reproducible identifier (§30.4)")
        return value


class IndicatorObservation(_Strict):
    feature_id: str
    value: Decimal
    observed_at: dt.datetime

    _aware_ts = field_validator("observed_at")(_aware)

    @field_validator("feature_id")
    @classmethod
    def _registry_shaped(cls, value: str) -> str:
        if not _FEATURE_ID.match(value):
            raise ValueError(
                f"indicator observation {value!r} is not a qualified feature id: the "
                f"Indicator and Feature Monitor observes only registry members (§30.7)"
            )
        return value


class TechnicalState(_Strict):
    structure_state: str
    momentum_state: str
    volatility_percentile: Decimal | None = Field(default=None, ge=0, le=100)
    session_range_fraction_of_atr: Decimal | None = Field(default=None, ge=0)
    key_levels: list[KeyLevel]
    active_indicator_observations: list[IndicatorObservation]


class LiquidityObservation(_Strict):
    name: str
    value: str
    evidence: EvidenceType


class LiquidityState(_Strict):
    """Every field carries its evidence label — required, not optional
    (§30.3.D via config `liquidity_evidence_label_required`)."""

    classification: str
    evidence: EvidenceType
    observations: list[LiquidityObservation]
    spread_state: str
    spread_evidence: EvidenceType
    spread_percentile: Decimal | None = Field(default=None, ge=0, le=100)


class UpcomingEvent(_Strict):
    event_id: str
    scheduled_utc: dt.datetime
    importance: Literal["low", "medium", "high"]
    currency: str

    _aware_ts = field_validator("scheduled_utc")(_aware)


class MacroState(_Strict):
    active_drivers: list[str]
    upcoming_events: list[UpcomingEvent]
    blackout_active: bool
    uncertainty_state: str


class NewsState(_Strict):
    material_item_ids: list[str]
    poll_state: NewsPollState
    unresolved_conflict: bool
    last_successful_poll_utc: dt.datetime | None = None

    @field_validator("last_successful_poll_utc")
    @classmethod
    def _aware_or_none(cls, value: dt.datetime | None) -> dt.datetime | None:
        return None if value is None else _aware(value)


class CrossMarketState(_Strict):
    confirmations: list[str]
    divergences: list[str]
    relationship_versions: list[str]


class ExecutionState(_Strict):
    broker_health: str
    market_data_health: str
    expected_slippage_state: str
    tradability_state: str


class DataQuality(_Strict):
    overall_status: DataQualityStatus
    stale_components: list[str]
    missing_components: list[str]
    conflicting_components: list[str]

    @model_validator(mode="after")
    def _problems_forbid_healthy(self) -> DataQuality:
        problems = self.stale_components or self.missing_components or self.conflicting_components
        if problems and self.overall_status is DataQualityStatus.HEALTHY:
            raise ValueError(
                "data_quality cannot be HEALTHY while components are stale, missing, "
                "or conflicting — stale required data must never be treated as "
                "confirmation (§30.1 rule 8, §30.4)"
            )
        return self


class ChangeSummary(_Strict):
    prior_market_state_id: str | None = None
    supersedes_market_state_id: str | None = None
    material_changes: list[str]
    non_material_changes_suppressed: int = Field(ge=0)


class MarketStateObject(_Strict):
    """§30.4: versioned, immutable at publication, per instrument+horizon.

    `market_state_id` IS the content checksum: identity and integrity are the
    same property, exactly as `MarketStatePacket.market_id` works. The state
    builder computes content first, then identifies it; `verify()` recomputes.
    """

    market_state_id: str
    schema_version: Literal["market_state_object_v1"]
    instrument_id: str
    asset_class: str
    as_of_utc: dt.datetime
    valid_until_utc: dt.datetime
    source_snapshot_ids: list[str]
    feature_snapshot_id: str | None
    configuration_version: str
    session_state: SessionState
    market_regime: RegimeState
    technical_state: TechnicalState
    liquidity_state: LiquidityState
    macro_state: MacroState
    news_state: NewsState
    cross_market_state: CrossMarketState
    execution_state: ExecutionState
    data_quality: DataQuality
    change_summary: ChangeSummary

    _aware_asof = field_validator("as_of_utc")(_aware)
    _aware_valid = field_validator("valid_until_utc")(_aware)

    @field_validator("instrument_id")
    @classmethod
    def _instrument_shape(cls, value: str) -> str:
        if not _INSTRUMENT_ID.match(value):
            raise ValueError(f"instrument_id {value!r} is not an instrument id (§30.11)")
        return value

    @model_validator(mode="after")
    def _validity_window_is_forward(self) -> MarketStateObject:
        if self.valid_until_utc <= self.as_of_utc:
            raise ValueError(
                "valid_until_utc must be after as_of_utc: a state that expires "
                "before it exists cannot gate anything (§30.4)"
            )
        return self

    @property
    def content_checksum(self) -> str:
        payload = self.model_dump(mode="python")
        payload.pop("market_state_id")
        return _digest(payload)

    def verify(self, expected_market_state_id: str) -> None:
        """§30.4: Alpha and Beta receive the same object ID and checksum. A
        mismatch means the object was altered after identification."""
        if self.market_state_id != expected_market_state_id:
            raise ValueError(
                f"market state id mismatch: expected {expected_market_state_id}, "
                f"carrying {self.market_state_id} (§30.4)"
            )
        recomputed = self.content_checksum
        if recomputed != self.market_state_id:
            raise ValueError(
                f"market state content does not match its id: {recomputed} != "
                f"{self.market_state_id} — published objects are append-only; "
                f"corrections create a replacement object (§30.4)"
            )

    def identified(self) -> MarketStateObject:
        """Return the same content carrying its content checksum as its id."""
        return self.model_copy(update={"market_state_id": self.content_checksum})
