"""Configuration schema and loader (Master Handoff v1.1.4 §24).

Every constitutional constant is a validated configuration value, not a
scattered literal (§3.4). Validators enforce the invariants the spec states
in prose, so an edited config that contradicts the constitution fails to load.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Environment = Literal["research", "replay", "shadow", "paper", "live"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FirmSection(_StrictModel):
    name: str
    environment: Environment
    starting_capital_usd: float
    profit_target: None  # §3.5: the firm has no profit target, ever
    control_timezone: str
    market_timezone: str

    @field_validator("market_timezone")
    @classmethod
    def _market_tz_is_london(cls, v: str) -> str:
        if v != "Europe/London":
            raise ValueError("market_timezone must be Europe/London (§14, R: C-2)")
        return v


class DrawdownStates(_StrictModel):
    caution_from_anchor: float
    restricted_from_anchor: float

    @model_validator(mode="after")
    def _ordered(self) -> DrawdownStates:
        if not (0 > self.caution_from_anchor > self.restricted_from_anchor):
            raise ValueError(
                "drawdown boundaries must be negative and ordered: caution > restricted (§4.5)"
            )
        return self


class RiskSection(_StrictModel):
    tier_anchor_usd: float
    scaling_multiplier: float
    current_equity_risk_contraction: bool
    max_open_positions: int
    max_trades_per_session: int
    max_exceptional_trades_per_session: int
    initial_session_loss_limit_usd: float
    initial_weekly_loss_limit_usd: float
    initial_live_floor_usd: float
    week_boundary: Literal["iso_week_europe_london"]
    tier_promotion_requires_owner_approval: bool
    deposits_advance_milestones: bool
    margin_utilization_cap_fraction: float
    drawdown_states: DrawdownStates
    stop_widening: bool
    averaging_down: bool
    martingale: bool
    recovery_sizing: bool

    @model_validator(mode="after")
    def _constitution(self) -> RiskSection:
        # §0.7 / §3.4: recovery behavior is prohibited as architecture.
        for flag in ("stop_widening", "averaging_down", "martingale", "recovery_sizing"):
            if getattr(self, flag):
                raise ValueError(f"{flag} must be false (§0.7 prohibition)")
        if not self.current_equity_risk_contraction:
            raise ValueError("current_equity_risk_contraction must be true (§4.4)")
        if not self.tier_promotion_requires_owner_approval:
            raise ValueError("tier promotion requires owner approval (§4.2, R: C-3, D-2)")
        if self.deposits_advance_milestones:
            raise ValueError("deposits must not advance milestone tiers (§4.2, D-3)")
        if self.initial_weekly_loss_limit_usd <= self.initial_session_loss_limit_usd:
            raise ValueError("weekly loss limit must exceed session loss limit (§3.4)")
        if self.initial_live_floor_usd >= self.tier_anchor_usd:
            raise ValueError("live floor must sit below the tier anchor (§3.4)")
        if not (0 < self.margin_utilization_cap_fraction <= 1):
            raise ValueError("margin_utilization_cap_fraction must be in (0, 1] (§3.2)")
        return self


class LadderTier(_StrictModel):
    initial_usd: float
    initial_equity_fraction: float


class ExceptionalTier(LadderTier):
    prohibited_after_session_loss: bool
    human_approval_during_probation: bool

    @model_validator(mode="after")
    def _gates(self) -> ExceptionalTier:
        if not self.prohibited_after_session_loss:
            raise ValueError("exceptional risk is prohibited after a session loss (§3.4)")
        if not self.human_approval_during_probation:
            raise ValueError("exceptional risk requires human approval during probation (§5.3)")
        return self


class RiskLadder(_StrictModel):
    standard: LadderTier
    strong: LadderTier
    high: LadderTier
    exceptional: ExceptionalTier


class ExecutionSection(_StrictModel):
    require_broker_stop_confirmation: bool
    reject_stale_data: bool
    reject_abnormal_spread: bool
    reject_unknown_news_state: bool
    reject_minimum_size_overrisk: bool
    idempotency_required: bool
    fail_closed: bool

    @model_validator(mode="after")
    def _fail_closed(self) -> ExecutionSection:
        # §0.10: every fail-closed flag is constitutional; none may be false.
        for name, value in self.__dict__.items():
            if value is False:
                raise ValueError(f"execution.{name} must be true (§0.10 fail-closed doctrine)")
        return self


class DataSection(_StrictModel):
    economic_calendar_source: str
    economic_calendar_endpoint: str
    economic_calendar_min_plan: str


class SessionSection(_StrictModel):
    anchor_timezone: Literal["Europe/London"]  # §14, R: C-2
    startup_london: str
    asian_range_final_london: str
    briefing_london: str
    activation_london: str
    entry_cutoff_london: str
    flatten_london: str
    display_timezone: str
    holiday_calendar_required: bool

    @field_validator(
        "startup_london",
        "asian_range_final_london",
        "briefing_london",
        "activation_london",
        "entry_cutoff_london",
        "flatten_london",
    )
    @classmethod
    def _valid_time(cls, v: str) -> str:
        _dt.time.fromisoformat(v)
        return v

    @model_validator(mode="after")
    def _ordered(self) -> SessionSection:
        names = [
            "startup_london",
            "asian_range_final_london",
            "briefing_london",
            "activation_london",
            "entry_cutoff_london",
            "flatten_london",
        ]
        times = [_dt.time.fromisoformat(getattr(self, n)) for n in names]
        if times != sorted(times) or len(set(times)) != len(times):
            raise ValueError("session boundaries must be strictly increasing (§14)")
        if not self.holiday_calendar_required:
            raise ValueError("holiday_calendar_required must be true (§14, R: N-11)")
        return self


class StrategiesSection(_StrictModel):
    live_allowed: list[str]
    research_allowed: list[str]
    specialist_research_allowed: list[str] = []


class InstrumentsSection(_StrictModel):
    research_priority: list[str]
    live_allowed: list[str]


class AdaptiveTradingSection(_StrictModel):
    """v2 §6/§6A/§6.8 senior-trader controls."""

    senior_trader_pair_enabled: bool
    independent_first_pass_required: bool
    market_state_packet_checksum_required: bool
    allowed_live_novelty_classes: list[str]
    exceptional_risk_allowed_novelty_classes: list[str]
    narrative_only_candidates_rejected: bool

    @field_validator("allowed_live_novelty_classes")
    @classmethod
    def _live_novelty(cls, value: list[str]) -> list[str]:
        illegal = [c for c in value if c in ("N2", "N3")]
        if illegal:
            raise ValueError(
                f"allowed_live_novelty_classes may never contain {illegal}: N2 and N3 "
                f"theses cannot place live orders (§6.8)"
            )
        return value

    @field_validator("exceptional_risk_allowed_novelty_classes")
    @classmethod
    def _exceptional_novelty(cls, value: list[str]) -> list[str]:
        illegal = [c for c in value if c != "N0"]
        if illegal:
            raise ValueError(
                f"exceptional_risk_allowed_novelty_classes may only contain N0; got "
                f"{illegal}. No N1/N2/N3 thesis may receive Exceptional risk (§6.8)"
            )
        return value

    @field_validator("independent_first_pass_required", "market_state_packet_checksum_required")
    @classmethod
    def _independence_not_optional(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "senior-trader independence controls cannot be disabled: agreement "
                "earns value only from materially independent evidence (§6.2)"
            )
        return value

    @field_validator("narrative_only_candidates_rejected")
    @classmethod
    def _narrative_rejected(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "narrative_only_candidates_rejected cannot be false: a persuasive "
                "story is not evidence of edge (§0 rule 5, §21)"
            )
        return value


class FeatureRegistrySection(_StrictModel):
    """v2 §11: senior traders may only select from approved features."""

    production_allowed: list[str]
    research_allowed: list[str]

    @model_validator(mode="after")
    def _production_subset_of_research(self) -> FeatureRegistrySection:
        unknown = set(self.production_allowed) - set(self.research_allowed)
        if unknown:
            raise ValueError(
                f"feature_registry.production_allowed contains features absent from "
                f"research_allowed: {sorted(unknown)}. A feature reaches production "
                f"only through validation (§11, §12.5)"
            )
        return self


class FirmConfig(_StrictModel):
    firm: FirmSection
    risk: RiskSection
    risk_ladder: RiskLadder
    execution: ExecutionSection
    data: DataSection
    session: SessionSection
    strategies: StrategiesSection
    instruments: InstrumentsSection
    adaptive_trading: AdaptiveTradingSection
    feature_registry: FeatureRegistrySection

    @model_validator(mode="after")
    def _cross_section(self) -> FirmConfig:
        anchor = self.risk.tier_anchor_usd
        for tier_name in ("standard", "strong", "high", "exceptional"):
            tier: LadderTier = getattr(self.risk_ladder, tier_name)
            expected = round(anchor * tier.initial_equity_fraction, 2)
            if abs(tier.initial_usd - expected) > 0.005:
                raise ValueError(
                    f"risk_ladder.{tier_name}: initial_usd {tier.initial_usd} != "
                    f"{tier.initial_equity_fraction:.0%} of anchor ${anchor} (= {expected}) (§3.2)"
                )
        if self.firm.environment != "live" and (
            self.strategies.live_allowed or self.instruments.live_allowed
        ):
            raise ValueError(
                "live_allowed must be empty outside the live environment (§24); live permission "
                "is granted only through the promotion process with owner approval (§12.5)"
            )
        return self


def load_config(path: str | Path) -> FirmConfig:
    """Load and validate a firm configuration file. Raises on any violation."""
    raw = yaml.safe_load(Path(path).read_text())
    return FirmConfig.model_validate(raw)


BASE_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "base" / "firm.yaml"
