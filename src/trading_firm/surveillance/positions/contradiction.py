"""The Position Contradiction Monitor's deterministic core (§30.3.J, §30.10).

Operates only when an approved paper or live position exists — this module
is the ONE surveillance module allowed to see position state, and what it
sees is deliberately narrow: `OpenPositionView` carries the position's
identity and protective structure, never equity, P&L, or capacity. It is
excluded from the pressure-blind guard list with this rationale, and the
companion boundary test proves nothing on the market side can import it.

What it may do with a finding: record it, escalate it, mark the thesis
under review. It may not invent a new exit rule after entry — it can only
match conditions the plan registered, in a vocabulary fixed at registration.
Existing broker-native stops remain authoritative.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from trading_firm.surveillance.monitoring import (
    ContradictionClass,
    Escalation,
    PositionContradiction,
    ThesisMonitoringPlan,
)
from trading_firm.surveillance.schemas import DataQualityStatus, MarketStateObject


@dataclass(frozen=True)
class OpenPositionView:
    """The narrow view: identity and protective structure only. No equity,
    no realized or unrealized figures, no account linkage — the fields this
    type does NOT have are its contract."""

    instrument: str
    direction: Literal["long", "short"]
    entry_price: Decimal
    stop_price: Decimal
    opened_at_utc: dt.datetime

    def __post_init__(self) -> None:
        if self.opened_at_utc.tzinfo is None:
            raise ValueError("position timestamps must be timezone-aware (C-2)")


def condition_holds(condition: str, state: MarketStateObject) -> bool:
    """Does a registered condition hold in this Market State Object?

    The matcher understands exactly the registered vocabulary
    (`monitoring.CONDITION_PREFIXES` / `CONDITION_FLAGS`); anything else was
    already rejected at plan registration.
    """
    if condition == "news.unresolved_conflict":
        return state.news_state.unresolved_conflict
    if condition == "macro.blackout_active":
        return state.macro_state.blackout_active
    if condition == "data_quality:FAILED":
        return state.data_quality.overall_status is DataQualityStatus.FAILED
    if condition == "data_quality:DEGRADED":
        return state.data_quality.overall_status is DataQualityStatus.DEGRADED
    if condition.startswith("structure:"):
        return state.technical_state.structure_state == condition.removeprefix("structure:")
    if condition.startswith("regime.intraday:"):
        return state.market_regime.intraday == condition.removeprefix("regime.intraday:")
    if condition.startswith("regime.daily:"):
        return state.market_regime.daily == condition.removeprefix("regime.daily:")
    if condition.startswith("spread:"):
        return state.liquidity_state.spread_state == condition.removeprefix("spread:")
    if condition.startswith("liquidity:"):
        return state.liquidity_state.classification == condition.removeprefix("liquidity:")
    return False


def _finding(
    plan: ThesisMonitoringPlan,
    state: MarketStateObject,
    at: dt.datetime,
    classification: ContradictionClass,
    escalation: Escalation,
    evidence: list[str],
) -> PositionContradiction:
    digest = hashlib.sha256(
        f"{plan.monitoring_plan_id}|{classification}|{state.market_state_id}".encode()
    ).hexdigest()[:16]
    return PositionContradiction(
        contradiction_id=f"contradiction.{digest}",
        monitoring_plan_id=plan.monitoring_plan_id,
        observed_at_utc=at.astimezone(dt.UTC),
        classification=classification,
        escalation=escalation,
        market_state_id=state.market_state_id,
        evidence=evidence,
    )


def evaluate(
    plan: ThesisMonitoringPlan,
    position: OpenPositionView,
    state: MarketStateObject,
    now: dt.datetime,
) -> PositionContradiction:
    """One evaluation pass, precedence fixed: the boundary that must never be
    crossed first, then data health, then the plan's registered conditions
    from hardest to softest, then confirmation, then noise."""
    if now.tzinfo is None:
        raise ValueError("evaluation requires aware datetimes (C-2)")

    # F-5 first: past the flatten boundary the position must not exist at
    # all. That pages the owner regardless of what the market looks like.
    if now >= plan.flatten_boundary_utc:
        return _finding(
            plan, state, now, ContradictionClass.TIME_EXPIRED, Escalation.OWNER,
            [f"past the inviolate flatten boundary {plan.flatten_boundary_utc.isoformat()}"],
        )

    matched_data_health = [c for c in plan.data_health_rules if condition_holds(c, state)]
    if matched_data_health or state.data_quality.overall_status is DataQualityStatus.FAILED:
        return _finding(
            plan, state, now, ContradictionClass.DATA_HEALTH, Escalation.CRO,
            matched_data_health or ["data_quality:FAILED"],
        )

    if plan.time_expiration_utc is not None and now >= plan.time_expiration_utc:
        return _finding(
            plan, state, now, ContradictionClass.TIME_EXPIRED, Escalation.SENIOR_TRADERS,
            [f"plan expired at {plan.time_expiration_utc.isoformat()}"],
        )

    hard = [c for c in plan.hard_invalidation_conditions if condition_holds(c, state)]
    if hard:
        return _finding(
            plan, state, now, ContradictionClass.HARD_INVALIDATION, Escalation.CRO, hard
        )

    events = [c for c in plan.event_invalidation_rules if condition_holds(c, state)]
    if events:
        return _finding(
            plan, state, now, ContradictionClass.EVENT_INVALIDATED,
            Escalation.SENIOR_TRADERS, events,
        )

    execution = [c for c in plan.execution_degradation_rules if condition_holds(c, state)]
    if execution:
        return _finding(
            plan, state, now, ContradictionClass.EXECUTION_DEGRADED,
            Escalation.SENIOR_TRADERS, execution,
        )

    soft = [c for c in plan.soft_contradictions if condition_holds(c, state)]
    if soft:
        escalation = (
            Escalation.SENIOR_TRADERS
            if plan.review_required_on_soft_contradiction
            else Escalation.NONE
        )
        return _finding(
            plan, state, now, ContradictionClass.SOFT_CONTRADICTION, escalation, soft
        )

    confirmed = [c for c in plan.expected_confirmations if condition_holds(c, state)]
    if confirmed:
        return _finding(
            plan, state, now, ContradictionClass.CONFIRMATION, Escalation.NONE, confirmed
        )

    return _finding(plan, state, now, ContradictionClass.NOISE, Escalation.NONE, [])
