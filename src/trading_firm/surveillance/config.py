"""Surveillance configuration (§30.12) — a separate file with its own loader.

The firm schema (`config.py`) is one strict file per layer; the precedent for
a second configuration surface with its own loader is the adaptive policy
manifest and the strategy manifests. Surveillance follows it:
`config/<layer>/surveillance.yaml`, validated here, never merged into
`firm.yaml`.

Two rules are structural rather than advisory:

* **The master switch dominates.** While `enabled` is false every sub-block is
  inert regardless of its own flags (§30.12). Consumers read the `*_active`
  properties, never the raw sub-flags, so a sub-block that was pre-configured
  for a later phase cannot leak behavior into the present one.
* **Illegal states are unrepresentable.** Influence flags, fail-open unknown
  states, automatic order changes, options code, and sub-MATERIAL phone
  delivery are rejected at load with the § an operator can follow — the same
  style as `config.py`, and for the same reason: a validator is the one
  reviewer that never gets tired.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BASE_SURVEILLANCE_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "base" / "surveillance.yaml"
)


class AlertSeverity(enum.StrEnum):
    """§30.13 alert severities, orderable so thresholds are comparisons."""

    INFO = "INFO"
    WATCH = "WATCH"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return ("INFO", "WATCH", "MATERIAL", "CRITICAL").index(self.value)

    def at_least(self, threshold: AlertSeverity) -> bool:
        return self.rank >= threshold.rank


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SchedulesSection(_Strict):
    """§30.9 briefing checkpoints. These bind to the §14 SessionClock
    boundaries — they are switches, never wall-clock times (C-2)."""

    asia_context_enabled: bool
    pre_london_briefing_enabled: bool
    london_activation_briefing_enabled: bool
    material_change_only_mid_session: bool
    entry_cutoff_briefing_enabled: bool
    post_session_review_enabled: bool


class TechnicalSection(_Strict):
    enabled: bool
    approved_feature_registry_only: bool
    structure_monitoring_enabled: bool
    regime_monitoring_enabled: bool
    liquidity_inference_enabled: bool
    liquidity_evidence_label_required: bool

    @field_validator("approved_feature_registry_only")
    @classmethod
    def _registry_only(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "technical.approved_feature_registry_only may not be false: the "
                "Indicator and Feature Monitor observes only registry members (§30.7)"
            )
        return value

    @field_validator("liquidity_evidence_label_required")
    @classmethod
    def _evidence_labels_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "technical.liquidity_evidence_label_required may not be false: every "
                "liquidity field carries OBSERVED/BROKER_PROXY/PRICE_ACTION_INFERENCE/"
                "UNAVAILABLE so inference can never impersonate observation (§30.3)"
            )
        return value


class MacroSection(_Strict):
    enabled: bool
    source_ids: list[str]
    unknown_state_behavior: Literal["fail_closed"]
    # fail-open is unrepresentable: unknown calendar state disables entries
    # (§0.10, §30.8), and a config key must not be able to say otherwise.


class NewsSection(_Strict):
    enabled: bool
    source_ids: list[str]
    verification_required_for_material_alert: bool
    duplicate_window_seconds: int = Field(gt=0)
    unknown_state_behavior: Literal["fail_closed"]

    @field_validator("verification_required_for_material_alert")
    @classmethod
    def _material_needs_verification(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "news.verification_required_for_material_alert may not be false: an "
                "unverified item cannot drive a MATERIAL alert (§30.8, §30.13)"
            )
        return value


class CrossMarketSection(_Strict):
    enabled: bool
    context_instruments: list[str]
    relationship_registry_only: bool

    @field_validator("relationship_registry_only")
    @classmethod
    def _registry_only(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "cross_market.relationship_registry_only may not be false: the "
                "Cross-Market Monitor tracks approved contextual instruments only (§30.3)"
            )
        return value


class AlertsSection(_Strict):
    enabled: bool
    minimum_severity: AlertSeverity
    telegram_minimum_severity: AlertSeverity
    state_change_only: bool
    severe_alerts_never_throttled: bool

    @field_validator("severe_alerts_never_throttled")
    @classmethod
    def _severe_bypass_is_inviolate(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "alerts.severe_alerts_never_throttled may not be false: severe risk, "
                "source-failure, broker, or position-protection alerts must never be "
                "suppressed by normal throttling (§30.6)"
            )
        return value

    @field_validator("telegram_minimum_severity")
    @classmethod
    def _phone_is_severe_only(cls, value: AlertSeverity) -> AlertSeverity:
        if not value.at_least(AlertSeverity.MATERIAL):
            raise ValueError(
                f"alerts.telegram_minimum_severity is {value.value}; delivery below "
                f"MATERIAL requires a new owner decision recorded in the decision log "
                f"(§30.12, owner decision 2026-07-31) — INFO/WATCH alerts stay in the "
                f"local event log and the daily report"
            )
        return value


class ClaudeAgentsSection(_Strict):
    enabled: bool
    scheduled_briefings: bool
    event_driven_analysis: bool
    highest_quality_for_material_events: bool


class PositionsSection(_Strict):
    contradiction_monitoring_enabled: bool
    automatic_order_changes_enabled: bool

    @field_validator("automatic_order_changes_enabled")
    @classmethod
    def _no_order_authority_ever(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "positions.automatic_order_changes_enabled may not be true: the "
                "Position Contradiction Monitor may not independently alter an order "
                "(§30.3, §30.10), and no surveillance component holds order authority "
                "(§0.3, §30.1 rule 6)"
            )
        return value


class OptionsScaffoldSection(_Strict):
    enabled: bool
    registered: bool

    @model_validator(mode="after")
    def _options_are_prose(self) -> OptionsScaffoldSection:
        if self.enabled or self.registered:
            raise ValueError(
                "options_scaffold may not be enabled or registered: the options "
                "scaffold is documentation only (owner decision 2026-07-31, §30.11); "
                "a separate owner-approved options amendment must come first"
            )
        return self


class SurveillanceConfig(_Strict):
    """§30.12 baseline. Read the `*_active` properties, not the raw flags."""

    enabled: bool
    mode: Literal["observe_only"]
    asset_classes_enabled: list[str]
    instruments_enabled: list[str]
    publish_market_state: bool
    influence_candidate_generation: bool
    influence_live_eligibility: bool
    post_entry_monitoring_enabled: bool
    fail_closed_on_required_component_failure: bool
    schedules: SchedulesSection
    technical: TechnicalSection
    macro: MacroSection
    news: NewsSection
    cross_market: CrossMarketSection
    alerts: AlertsSection
    claude_agents: ClaudeAgentsSection
    positions: PositionsSection
    options_scaffold: OptionsScaffoldSection

    @field_validator("asset_classes_enabled")
    @classmethod
    def _fx_spot_only_for_now(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - {"FX_SPOT"})
        if unknown:
            raise ValueError(
                f"asset_classes_enabled contains {unknown}: FX_SPOT is the only "
                f"registered asset class; any other requires its own owner-approved "
                f"amendment (§30.11, D-1)"
            )
        return value

    @field_validator("influence_candidate_generation", "influence_live_eligibility")
    @classmethod
    def _observation_is_not_influence(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "surveillance influence flags may not be true: influence requires the "
                "§30.18 phase evidence, §12.7-cleared numbers, and owner approval — "
                "enabling it is a spec revision, not a config edit (§30.12, §30.14)"
            )
        return value

    @field_validator("fail_closed_on_required_component_failure")
    @classmethod
    def _fail_closed_is_inviolate(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "fail_closed_on_required_component_failure may not be false: missing, "
                "stale, conflicting, or unhealthy required live-intelligence data must "
                "never be treated as confirming evidence (§30.1 rule 8)"
            )
        return value

    # ------------------------------------------------------------------
    # Effective views: the master switch dominates (§30.12).

    @property
    def publishing_active(self) -> bool:
        return self.enabled and self.publish_market_state

    @property
    def technical_active(self) -> bool:
        return self.enabled and self.technical.enabled

    @property
    def macro_active(self) -> bool:
        return self.enabled and self.macro.enabled

    @property
    def news_active(self) -> bool:
        return self.enabled and self.news.enabled

    @property
    def cross_market_active(self) -> bool:
        return self.enabled and self.cross_market.enabled

    @property
    def alerts_active(self) -> bool:
        return self.enabled and self.alerts.enabled

    @property
    def claude_agents_active(self) -> bool:
        return self.enabled and self.claude_agents.enabled

    @property
    def contradiction_monitoring_active(self) -> bool:
        return (
            self.enabled
            and self.post_entry_monitoring_enabled
            and self.positions.contradiction_monitoring_enabled
        )


def load_surveillance_config(path: str | Path) -> SurveillanceConfig:
    """Load and validate one layer's surveillance.yaml.

    The file's single top-level key is `surveillance`, mirroring the §30.12
    baseline verbatim so the YAML in the spec and the YAML on disk diff clean.
    """
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or set(raw) != {"surveillance"}:
        raise ValueError(
            f"{path}: expected a single top-level 'surveillance' key (§30.12)"
        )
    return SurveillanceConfig.model_validate(raw["surveillance"])
