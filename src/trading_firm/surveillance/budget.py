"""Claude invocation budgets (§30.15) — cost control as configuration.

Pure decision over explicit counters. The one §30.15 sentence that shapes
the design: budget exhaustion must reduce interpretation frequency, not
disable deterministic risk or source-health monitoring — so this module is
consulted ONLY before an agent invocation, and nothing deterministic ever
asks it for permission.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace

from pydantic import BaseModel, ConfigDict, Field

from trading_firm.surveillance.config import AlertSeverity


class InvocationBudget(BaseModel):
    """§30.15 controls, all required, all bounded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_scheduled_per_session: int = Field(ge=0)
    max_noncritical_event_driven_per_hour: int = Field(ge=0)
    minimum_materiality: AlertSeverity
    cooldown_seconds: int = Field(ge=0)
    max_context_bytes: int = Field(gt=0)


@dataclass(frozen=True)
class BudgetState:
    scheduled_used: int = 0
    event_driven_this_hour: int = 0
    hour_started_at: dt.datetime | None = None
    last_invocation_at: dt.datetime | None = None


@dataclass(frozen=True)
class BudgetDecision:
    may_invoke: bool
    reason: str
    state: BudgetState = field(default_factory=BudgetState)


def _rolled(state: BudgetState, now: dt.datetime) -> BudgetState:
    if state.hour_started_at is None or (now - state.hour_started_at) >= dt.timedelta(hours=1):
        return replace(state, event_driven_this_hour=0, hour_started_at=now)
    return state


def request_scheduled(
    state: BudgetState, budget: InvocationBudget, now: dt.datetime
) -> BudgetDecision:
    if state.scheduled_used >= budget.max_scheduled_per_session:
        return BudgetDecision(False, "scheduled budget exhausted for this session", state)
    return BudgetDecision(
        True,
        "scheduled invocation permitted",
        replace(state, scheduled_used=state.scheduled_used + 1, last_invocation_at=now),
    )


def request_event_driven(
    state: BudgetState,
    budget: InvocationBudget,
    now: dt.datetime,
    severity: AlertSeverity,
) -> BudgetDecision:
    if now.tzinfo is None:
        raise ValueError("budget decisions require aware datetimes (§30.4, C-2)")
    state = _rolled(state, now)

    # CRITICAL interpretation is outside the noncritical budget; everything
    # else must clear materiality, cooldown, and the hourly cap in turn.
    if severity is not AlertSeverity.CRITICAL:
        if not severity.at_least(budget.minimum_materiality):
            return BudgetDecision(
                False, f"below materiality floor {budget.minimum_materiality}", state
            )
        if (
            state.last_invocation_at is not None
            and (now - state.last_invocation_at).total_seconds() < budget.cooldown_seconds
        ):
            return BudgetDecision(False, "inside cooldown", state)
        if state.event_driven_this_hour >= budget.max_noncritical_event_driven_per_hour:
            return BudgetDecision(
                False,
                "hourly noncritical budget exhausted: interpretation frequency reduced, "
                "deterministic monitoring unaffected (§30.15)",
                state,
            )

    return BudgetDecision(
        True,
        "event-driven invocation permitted",
        replace(
            state,
            event_driven_this_hour=state.event_driven_this_hour
            + (0 if severity is AlertSeverity.CRITICAL else 1),
            last_invocation_at=now,
        ),
    )


def fits_context(payload_bytes: int, budget: InvocationBudget) -> bool:
    return payload_bytes <= budget.max_context_bytes
