"""Deterministic position sizing (§3.3, §8.1).

The stop comes first; size is derived. Spread is included in loss-per-unit
(conservative), units round DOWN to broker granularity, and the trade is
rejected outright if the broker minimum would exceed the approved risk
(§8.1 'Reject if minimum size exceeds allowed risk').
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from trading_firm.models import Candidate, InstrumentSpec, SizingResult, cents

_ZERO = Decimal("0")


def size_position(
    candidate: Candidate,
    spec: InstrumentSpec,
    allowed_risk_usd: Decimal,
    *,
    closed_equity: Decimal,
    margin_utilization_cap_fraction: Decimal,
    spread_pips_assumption: Decimal = Decimal("2.0"),
) -> SizingResult:
    """Convert approved dollar risk into broker units, or reject.

    spread_pips_assumption defaults to 2.0 pips — the upper edge of audited
    practice spreads (F-3/F-5) — so effective risk stays conservative until a
    live-calibrated cost model exists (§12.4).
    """
    reasons: list[str] = []
    if allowed_risk_usd <= _ZERO:
        return SizingResult(False, 0, _ZERO, _ZERO, ("no approved risk to size (§3.3)",))

    loss_per_unit = candidate.stop_distance() + spread_pips_assumption * spec.pip_size
    raw_units = allowed_risk_usd / loss_per_unit

    granularity = Decimal(10) ** -spec.trade_units_precision
    units_dec = (raw_units / granularity).to_integral_value(rounding=ROUND_DOWN) * granularity
    units = int(units_dec)

    if units < spec.minimum_trade_size:
        reasons.append(
            "broker minimum size exceeds approved risk at this stop distance: reject "
            "(§3.3/§8.1 reject_minimum_size_overrisk)"
        )
        return SizingResult(False, 0, _ZERO, _ZERO, tuple(reasons))

    margin_required = units_dec * candidate.entry_price * spec.margin_rate
    margin_budget = margin_utilization_cap_fraction * closed_equity
    if margin_required > margin_budget:
        reasons.append(
            f"margin {cents(margin_required)} exceeds budget {cents(margin_budget)} "
            "(§3.2 overlay, per-instrument rate — F-1)"
        )
        return SizingResult(False, 0, _ZERO, cents(margin_required), tuple(reasons))

    effective_risk = cents(units_dec * loss_per_unit)
    if effective_risk > allowed_risk_usd:
        reasons.append("effective risk exceeds approval after rounding — internal error")
        return SizingResult(False, 0, effective_risk, cents(margin_required), tuple(reasons))

    return SizingResult(
        approved=True,
        units=units,
        effective_risk_usd=effective_risk,
        margin_required_usd=cents(margin_required),
        reasons=(f"loss/unit {loss_per_unit} incl. {spread_pips_assumption} pips spread",),
    )
