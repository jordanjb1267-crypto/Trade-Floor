"""Alert deduplication and throttling (§30.6) — prevent alert floods.

Modeled on `runner/liveness.py`'s plan/ledger split: a pure decision
function over an explicit history, so the throttle is testable without a
clock or disk. The invariant carried from the section text: severe risk,
source-failure, broker, or position-protection alerts must never be
suppressed by normal throttling — `is_severe` bypasses every rule below
except exact-duplicate collapse within the correlation window, which is not
suppression but recognition that one event is one event.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from trading_firm.surveillance.alerts import SurveillanceAlertRecord
from trading_firm.surveillance.config import AlertSeverity

# Cooldown per severity: how long the same content hash stays quiet after an
# emission. Severe alerts bypass; INFO waits the longest.
COOLDOWN_SECONDS: dict[AlertSeverity, int] = {
    AlertSeverity.INFO: 3600,
    AlertSeverity.WATCH: 1800,
    AlertSeverity.MATERIAL: 900,
    AlertSeverity.CRITICAL: 0,
}
# Exact duplicates inside this window collapse even for severe alerts: the
# same event re-detected seconds apart is one event, not two emergencies.
DUPLICATE_COLLAPSE_SECONDS = 60


@dataclass(frozen=True)
class AlertDecision:
    should_emit: bool
    reason: str


def decide(
    alert: SurveillanceAlertRecord,
    last_emitted_at_by_hash: dict[str, dt.datetime],
    minimum_severity: AlertSeverity,
    state_change_only: bool = True,
) -> AlertDecision:
    prior = last_emitted_at_by_hash.get(alert.content_hash)

    if prior is not None:
        age = (alert.ts - prior).total_seconds()
        if age <= DUPLICATE_COLLAPSE_SECONDS:
            return AlertDecision(False, "duplicate within correlation window")
        if alert.is_severe:
            return AlertDecision(True, "severe alert bypasses throttling (§30.6)")
        if state_change_only:
            return AlertDecision(False, "state-change-only: content already emitted")
        if age <= COOLDOWN_SECONDS[alert.severity]:
            return AlertDecision(False, f"severity cooldown ({alert.severity})")
        return AlertDecision(True, "cooldown elapsed")

    if alert.is_severe:
        return AlertDecision(True, "severe alert bypasses throttling (§30.6)")
    if not alert.severity.at_least(minimum_severity):
        return AlertDecision(False, f"below minimum severity {minimum_severity}")
    return AlertDecision(True, "new alert content")
