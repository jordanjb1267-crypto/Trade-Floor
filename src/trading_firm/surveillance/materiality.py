"""Deterministic material-change detection (§30.6, §30.9).

State-change-only: a material change is a difference between two published
Market State Objects, never a level of anything in isolation. This is what
keeps briefings quiet when nothing changed (do not generate repetitive
briefings when the state is unchanged, §30.9) and what the Opportunity
Alert Agent consumes — it creates an alert only when a material state
change occurs (§30.3.I).

Pure function of two market-side objects; pressure-blind by guard.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_firm.surveillance.schemas import DataQualityStatus, MarketStateObject

MATERIALITY_LOGIC_VERSION = "surveillance_materiality_v1"


@dataclass(frozen=True)
class MaterialityAssessment:
    material_changes: tuple[str, ...]
    logic_version: str = MATERIALITY_LOGIC_VERSION

    @property
    def is_material(self) -> bool:
        return bool(self.material_changes)


def assess_change(
    prior: MarketStateObject | None,
    current: MarketStateObject,
) -> MaterialityAssessment:
    """Compare two published states. The first state of a session is material
    by definition — there is no prior to be unchanged from."""
    if prior is None:
        return MaterialityAssessment(("first_state_of_session",))

    changes: list[str] = []
    if prior.market_regime.intraday != current.market_regime.intraday:
        changes.append(
            f"regime.intraday: {prior.market_regime.intraday} -> "
            f"{current.market_regime.intraday}"
        )
    if prior.market_regime.daily != current.market_regime.daily:
        changes.append(
            f"regime.daily: {prior.market_regime.daily} -> {current.market_regime.daily}"
        )
    if prior.data_quality.overall_status != current.data_quality.overall_status:
        changes.append(
            f"data_quality: {prior.data_quality.overall_status} -> "
            f"{current.data_quality.overall_status}"
        )
    if prior.macro_state.blackout_active != current.macro_state.blackout_active:
        changes.append(f"macro.blackout_active -> {current.macro_state.blackout_active}")
    if prior.liquidity_state.classification != current.liquidity_state.classification:
        changes.append(
            f"liquidity: {prior.liquidity_state.classification} -> "
            f"{current.liquidity_state.classification}"
        )
    if prior.liquidity_state.spread_state != current.liquidity_state.spread_state:
        changes.append(
            f"spread: {prior.liquidity_state.spread_state} -> "
            f"{current.liquidity_state.spread_state}"
        )
    if prior.news_state.unresolved_conflict != current.news_state.unresolved_conflict:
        changes.append(
            f"news.unresolved_conflict -> {current.news_state.unresolved_conflict}"
        )
    if prior.technical_state.structure_state != current.technical_state.structure_state:
        changes.append(
            f"structure: {prior.technical_state.structure_state} -> "
            f"{current.technical_state.structure_state}"
        )

    # A FAILED state is always material even if it was FAILED before — it is
    # re-announced by severity policy, not by this comparison; here we only
    # record the transition (severe-alert bypass lives in deduplication).
    if (
        prior.data_quality.overall_status == current.data_quality.overall_status
        and current.data_quality.overall_status is DataQualityStatus.FAILED
        and prior.data_quality.missing_components != current.data_quality.missing_components
    ):
        changes.append("data_quality.failed_components_changed")

    return MaterialityAssessment(tuple(changes))
