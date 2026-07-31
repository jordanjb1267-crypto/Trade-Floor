"""Deterministic risk engine (§3, §5.3, §8.1).

Only this code authorizes risk. It consumes a schema-valid candidate, the
reconciled account state, and broker-reported instrument facts, and produces
an immutable decision. LLM output appears nowhere in this module (§0.3).

allowed_trade_risk = min(               # §3.3
    tier dollar cap,
    tier fraction x current closed equity,
    remaining session loss capacity,
    remaining weekly loss capacity,
    margin-safe capacity at the technical stop (per-instrument rate, F-1),
)
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from trading_firm.config import FirmConfig
from trading_firm.models import (
    AccountState,
    Candidate,
    DrawdownState,
    EdgeTier,
    InstrumentSpec,
    RiskDecision,
    cents,
    tier_from_score,
)
from trading_firm.risk.capital import (
    drawdown_state,
    max_tier_for_drawdown,
    max_trades_for_drawdown,
)
from trading_firm.sessions.clock import SessionClock

_ZERO = Decimal("0")


class RiskEngine:
    def __init__(self, config: FirmConfig, clock: SessionClock):
        self._config = config
        self._clock = clock

    def evaluate(
        self,
        candidate: Candidate,
        account: AccountState,
        spec: InstrumentSpec,
        now: dt.datetime,
    ) -> RiskDecision:
        cfg = self._config
        risk = cfg.risk
        reasons: list[str] = []

        candidate_key = candidate.content_key()

        def reject(tier: EdgeTier = EdgeTier.NONE, bound_by: str | None = None) -> RiskDecision:
            return RiskDecision(
                approved=False,
                tier=tier,
                allowed_risk_usd=_ZERO,
                reasons=tuple(reasons),
                candidate_key=candidate_key,
                thesis_ceiling=candidate.thesis_ceiling,
                tier_bound_by=bound_by,
            )

        # --- fail-closed gates (§0.10): any doubt -> no new entry ---------------
        if now >= candidate.expires_at:
            reasons.append("candidate expired (§13)")
        if not candidate.data_fresh:
            reasons.append("market data not fresh (§0.10)")
        if not candidate.news_state_known:
            reasons.append("economic-calendar state unknown (§0.10)")
        if not candidate.stop_broker_compatible:
            reasons.append("stop not broker-compatible (§5.3)")
        if not account.reconciled:
            reasons.append("account not reconciled (§8.1)")
        if not account.broker_healthy:
            reasons.append("broker connection unhealthy (§0.10)")
        if candidate.instrument != spec.name:
            reasons.append("instrument spec mismatch")
        if reasons:
            return reject()

        # --- session window and rollover (§14, F-5) ------------------------------
        if not self._clock.entries_allowed(now):
            reasons.append("outside entry window [activation, cutoff) (§14)")
        if self._clock.in_rollover_blackout(now):
            reasons.append("inside 21:00 UTC rollover blackout (F-5)")
        if reasons:
            return reject()

        # --- structural limits (§3.4) -------------------------------------------
        state = drawdown_state(
            account.closed_equity,
            account.tier_anchor,
            Decimal(str(risk.initial_live_floor_usd)),
            Decimal(str(risk.drawdown_states.caution_from_anchor)),
            Decimal(str(risk.drawdown_states.restricted_from_anchor)),
        )
        if state is DrawdownState.SHADOW:
            reasons.append("at/below live floor: SHADOW state, live entries disabled (§3.4)")
        if account.open_positions >= risk.max_open_positions:
            reasons.append("max open positions reached (§3.4)")
        if account.trades_this_session >= max_trades_for_drawdown(state, risk):
            reasons.append("session trade count exhausted (§3.4/§4.5)")

        session_limit = Decimal(str(risk.initial_session_loss_limit_usd))
        weekly_limit = Decimal(str(risk.initial_weekly_loss_limit_usd))
        session_capacity = session_limit - account.session_realized_loss
        weekly_capacity = weekly_limit - account.weekly_realized_loss
        if session_capacity <= _ZERO:
            reasons.append("session loss limit reached: session is over (§3.4)")
        if weekly_capacity <= _ZERO:
            reasons.append("weekly loss limit reached (§3.4)")
        if reasons:
            return reject()

        # --- tier: score sets the ceiling; deterministic gates only lower it -----
        # Every assignment below moves the tier DOWN. That is the property A-2
        # depends on and §5.1 states: firm state (drawdown, session loss, trade
        # counts) reaches this block only as a reducer. `tier_bound_by` records
        # which reducer last moved it, so the audit trail distinguishes a
        # gate-bound decision from a thesis-bound one (§25).
        tier = tier_from_score(candidate.edge_score)
        if tier is EdgeTier.NONE:
            reasons.append("edge score below 70: no qualified edge (§5.2)")
            return reject(bound_by="edge score (§5.2)")
        tier_bound_by = "edge score (§5.2)"

        # A-2: the thesis's own novelty x evidence ceiling. Lowers only — a
        # thesis cannot raise the tier its evidence score already set (§5.2).
        ceiling = candidate.thesis_ceiling
        if ceiling is not None and ceiling < tier:
            tier = ceiling
            tier_bound_by = "thesis classification: novelty x evidence (§5.2, §6.8)"
            if tier is EdgeTier.NONE:
                reasons.append(
                    "thesis classification permits no live tier: an unvalidated novelty "
                    "or evidence class cannot place a live order (§5.2, §6.8)"
                )
                return reject(bound_by=tier_bound_by)

        cap = max_tier_for_drawdown(state)
        if tier > cap:
            tier = cap
            tier_bound_by = "drawdown cap (§4.5)"
        if tier is EdgeTier.EXCEPTIONAL:
            ladder = cfg.risk_ladder.exceptional
            if account.session_realized_loss > _ZERO and ladder.prohibited_after_session_loss:
                tier = EdgeTier.HIGH  # §3.4: session loss disables Exceptional
                tier_bound_by = "session loss disables Exceptional (§3.4)"
            elif account.exceptional_trades_this_session >= risk.max_exceptional_trades_per_session:
                tier = EdgeTier.HIGH  # §3.4: one exceptional trade per session
                tier_bound_by = "one Exceptional trade per session (§3.4)"
            elif ladder.human_approval_during_probation and not candidate.human_approval:
                tier = EdgeTier.HIGH  # §5.3: explicit human approval required
                tier_bound_by = "Exceptional requires explicit human approval (§5.3)"

        # --- §3.3 minimum over all capacities ------------------------------------
        tier_cfg = {
            EdgeTier.STANDARD: cfg.risk_ladder.standard,
            EdgeTier.STRONG: cfg.risk_ladder.strong,
            EdgeTier.HIGH: cfg.risk_ladder.high,
            EdgeTier.EXCEPTIONAL: cfg.risk_ladder.exceptional,
        }[tier]
        tier_dollar_cap = Decimal(str(tier_cfg.initial_usd))
        fraction_cap = Decimal(str(tier_cfg.initial_equity_fraction)) * account.closed_equity

        loss_per_unit = candidate.stop_distance()  # USD-quote pairs: USD per unit
        margin_budget = (
            Decimal(str(risk.margin_utilization_cap_fraction)) * account.closed_equity
        )
        margin_units_cap = margin_budget / (candidate.entry_price * spec.margin_rate)
        margin_risk_cap = margin_units_cap * loss_per_unit  # F-1: per-instrument rate

        capacities = {
            "tier dollar cap (§3.2)": tier_dollar_cap,
            "tier fraction of equity (§3.2)": fraction_cap,
            "remaining session capacity (§3.4)": session_capacity,
            "remaining weekly capacity (§3.4)": weekly_capacity,
            "margin-safe capacity (§3.2, F-1)": margin_risk_cap,
        }
        binding = min(capacities, key=lambda k: capacities[k])
        allowed = cents(capacities[binding])
        if allowed <= _ZERO:
            reasons.append(f"no positive risk capacity; binding: {binding}")
            return reject(tier, bound_by=tier_bound_by)

        return RiskDecision(
            approved=True,
            tier=tier,
            allowed_risk_usd=allowed,
            reasons=tuple(f"{name} = {cents(value)}" for name, value in capacities.items()),
            candidate_key=candidate_key,
            binding_constraint=binding,
            thesis_ceiling=candidate.thesis_ceiling,
            tier_bound_by=tier_bound_by,
        )
