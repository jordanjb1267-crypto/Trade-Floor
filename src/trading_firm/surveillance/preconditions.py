"""Optional deterministic risk-gate preconditions (§30.14) — built, unwired.

Do not rewrite risk calculations. These checks can only refuse; they cannot
raise anything, and in this build they are not consulted by
`risk/engine.py` at all: §30.14 requires them to remain disabled in live
configuration until paper validation and owner approval, and the honest
form of "disabled" is an integration that does not exist yet. When the
rollout reaches the step that wires them, the call site is the top of
`RiskEngine.evaluate`, refusals appended to the decision's reasons — the
same shape as every existing gate check.

Pure functions of (packet, health, config, now); no firm state, no I/O.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from trading_firm.surveillance.config import SurveillanceConfig
from trading_firm.surveillance.packet import SurveillancePacket
from trading_firm.surveillance.schemas import NewsPollState


def evaluate_preconditions(
    packet: SurveillancePacket | None,
    source_health: Mapping[str, str],
    config: SurveillanceConfig,
    now: dt.datetime,
) -> tuple[str, ...]:
    """Refusal reasons, empty when every precondition holds. Refusals only —
    there is no approval to hand out here (§30.14)."""
    if now.tzinfo is None:
        raise ValueError("precondition evaluation requires aware datetimes (C-2)")
    if not config.enabled:
        # The division is off: its preconditions assert nothing, and the
        # existing gate checks stand alone exactly as before the amendment.
        return ()

    refusals: list[str] = []
    if packet is None:
        refusals.append("no surveillance packet exists for this candidate (§30.14)")
        return tuple(refusals)

    if packet.market_state.valid_until_utc <= now:
        refusals.append(
            f"surveillance packet expired at "
            f"{packet.market_state.valid_until_utc.isoformat()} (§30.14)"
        )
    failed = sorted(
        source_id for source_id, state in packet.source_health.items() if state == "FAILED"
    )
    if failed:
        refusals.append(f"required source-health components failed: {failed} (§30.14)")
    if packet.market_state.macro_state.blackout_active:
        refusals.append("configured event blackout is active (§30.14)")
    if packet.market_state.news_state.unresolved_conflict:
        refusals.append("unresolved critical news conflict (§30.14, §30.8)")
    if packet.market_state.news_state.poll_state is NewsPollState.UNKNOWN and (
        config.news_active
    ):
        refusals.append(
            "news domain is enabled but poll state is UNKNOWN — unknown never "
            "confirms (§30.8)"
        )
    return tuple(refusals)
