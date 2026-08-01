"""Thesis monitoring plans and contradictions (§30.10) — the post-entry side.

These types live OUTSIDE `surveillance/schemas.py` on purpose: the market
side sits in the pressure-blind guard list, and the post-entry side reads
position state by design, so the two must not share a module. Nothing here
may flow back into classification or materiality — that direction is fenced
by the a2 boundary test.

Two §30.10 sentences are types rather than reviews:

* *It may not invent a new exit rule after entry.* Plan conditions are drawn
  from a registered vocabulary and fixed at registration; a condition the
  vocabulary cannot express fails validation, and the evaluator can only
  match what the plan registered.
* The plan's time bounds are capped by the flatten boundary (F-5): a plan
  that expects to monitor past the moment the position must not exist is
  unrepresentable.

Policy actions are the same discipline: a registered set of restrictive and
escalation actions. Order-touching actions have no member to name.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

MONITORING_PLAN_VERSION = "thesis_monitoring_plan_v1"

# §30.10 action boundary: record, escalate, mark under review — and only
# preconfigured, already-authorized deterministic actions, which today is
# this list exactly. There is no close/widen/resize member to register.
REGISTERED_POLICY_ACTIONS = frozenset(
    {
        "record_contradiction",
        "escalate_senior_traders",
        "escalate_arbiter",
        "escalate_cro",
        "escalate_owner",
        "mark_thesis_under_review",
    }
)

# The condition vocabulary plans may reference. Prefixed entries take a
# value after the colon; bare entries are boolean state flags.
CONDITION_PREFIXES = (
    "structure:",
    "regime.intraday:",
    "regime.daily:",
    "spread:",
    "liquidity:",
)
CONDITION_FLAGS = frozenset(
    {
        "news.unresolved_conflict",
        "macro.blackout_active",
        "data_quality:FAILED",
        "data_quality:DEGRADED",
    }
)


def condition_is_registered(condition: str) -> bool:
    return condition in CONDITION_FLAGS or condition.startswith(CONDITION_PREFIXES)


class ContradictionClass(enum.StrEnum):
    CONFIRMATION = "confirmation"
    NOISE = "noise"
    SOFT_CONTRADICTION = "soft_contradiction"
    HARD_INVALIDATION = "hard_invalidation"
    TIME_EXPIRED = "time_expired"
    EVENT_INVALIDATED = "event_invalidated"
    EXECUTION_DEGRADED = "execution_degraded"
    DATA_HEALTH = "data_health"


class Escalation(enum.StrEnum):
    NONE = "none"
    SENIOR_TRADERS = "senior_traders"
    ARBITER = "arbiter"
    CRO = "cro"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return ("none", "senior_traders", "arbiter", "cro", "owner").index(self.value)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError("monitoring timestamps must be timezone-aware (§30.4, C-2)")
    return value


class ThesisMonitoringPlan(_Strict):
    """§30.10 minimum schema, registered before entry, immutable after."""

    monitoring_plan_id: str
    candidate_id: str
    schema_version: Literal["thesis_monitoring_plan_v1"]
    expected_confirmations: list[str]
    acceptable_noise_conditions: list[str]
    soft_contradictions: list[str]
    hard_invalidation_conditions: list[str]
    time_expiration_utc: dt.datetime | None
    event_invalidation_rules: list[str]
    execution_degradation_rules: list[str]
    data_health_rules: list[str]
    review_required_on_soft_contradiction: bool
    policy_actions: list[str]
    flatten_boundary_utc: dt.datetime

    _aware_flatten = field_validator("flatten_boundary_utc")(_aware)

    @field_validator("time_expiration_utc")
    @classmethod
    def _aware_or_none(cls, value: dt.datetime | None) -> dt.datetime | None:
        return None if value is None else _aware(value)

    @field_validator("policy_actions")
    @classmethod
    def _actions_are_registered(cls, value: list[str]) -> list[str]:
        rogue = sorted(set(value) - REGISTERED_POLICY_ACTIONS)
        if rogue:
            raise ValueError(
                f"policy_actions {rogue} are not registered: the monitor may record, "
                f"escalate, and mark under review — it may not independently alter an "
                f"order, and there is no action member that touches one (§30.10, "
                f"§30.1 rule 6)"
            )
        return value

    @model_validator(mode="after")
    def _conditions_speak_the_vocabulary(self) -> ThesisMonitoringPlan:
        every = (
            self.expected_confirmations
            + self.acceptable_noise_conditions
            + self.soft_contradictions
            + self.hard_invalidation_conditions
            + self.event_invalidation_rules
            + self.execution_degradation_rules
            + self.data_health_rules
        )
        unregistered = sorted(c for c in every if not condition_is_registered(c))
        if unregistered:
            raise ValueError(
                f"conditions {unregistered} are not in the registered vocabulary — "
                f"a condition the vocabulary cannot express cannot be registered, and "
                f"the monitor may not invent a new exit rule after entry (§30.10)"
            )
        return self

    @model_validator(mode="after")
    def _bounded_by_the_flatten_boundary(self) -> ThesisMonitoringPlan:
        if (
            self.time_expiration_utc is not None
            and self.time_expiration_utc > self.flatten_boundary_utc
        ):
            raise ValueError(
                f"time_expiration_utc {self.time_expiration_utc.isoformat()} exceeds "
                f"the flatten boundary {self.flatten_boundary_utc.isoformat()}: no "
                f"plan may expect a position past the point it must not exist "
                f"(§30.10, §14, F-5)"
            )
        return self


class PositionContradiction(_Strict):
    """One evaluation outcome, escalated according to severity (§30.10)."""

    contradiction_id: str
    monitoring_plan_id: str
    observed_at_utc: dt.datetime
    classification: ContradictionClass
    escalation: Escalation
    market_state_id: str
    evidence: list[str]

    _aware_observed = field_validator("observed_at_utc")(_aware)

    @model_validator(mode="after")
    def _severity_reaches_someone(self) -> PositionContradiction:
        if (
            self.classification is ContradictionClass.HARD_INVALIDATION
            and self.escalation.rank < Escalation.CRO.rank
        ):
            raise ValueError(
                "a hard invalidation escalates to the CRO or the owner — recording "
                "it quietly is not an available outcome (§30.10)"
            )
        return self
