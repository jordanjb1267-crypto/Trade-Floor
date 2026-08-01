"""Deterministic alert construction and severity policy (§30.6, §30.13).

Alerts are built from materiality assessments, never from raw readings — a
level of anything, in isolation, is not an alert. Severity assignment is a
versioned table, not judgment: an agent may LOWER how interesting a change
reads in its commentary, but the deterministic severity is what throttling
and delivery run on, so no narrative can promote or bury an alert.

Phone delivery is a separate question from creation: `deliverable(alert,
config)` implements the owner's severe-only decision — only MATERIAL and
CRITICAL alerts may reach the §19 Telegram surface, and the config loader
refuses a lower threshold.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

from trading_firm.surveillance.config import AlertSeverity, SurveillanceConfig
from trading_firm.surveillance.materiality import MaterialityAssessment
from trading_firm.surveillance.schemas import DataQualityStatus, MarketStateObject

ALERT_POLICY_VERSION = "surveillance_alert_policy_v1"
ALERT_VALIDITY = dt.timedelta(minutes=30)

# Change-reason prefixes -> severity. Versioned with the policy: changing a
# row is a new version, reviewed, never a quiet edit.
_SEVERITY_BY_PREFIX: tuple[tuple[str, AlertSeverity], ...] = (
    ("data_quality: DataQualityStatus.FAILED", AlertSeverity.CRITICAL),
    ("data_quality.failed_components_changed", AlertSeverity.CRITICAL),
    ("data_quality", AlertSeverity.WATCH),
    ("news.unresolved_conflict", AlertSeverity.MATERIAL),
    ("macro.blackout_active", AlertSeverity.MATERIAL),
    ("regime.", AlertSeverity.MATERIAL),
    ("structure:", AlertSeverity.MATERIAL),
    ("liquidity:", AlertSeverity.WATCH),
    ("spread:", AlertSeverity.WATCH),
    ("first_state_of_session", AlertSeverity.INFO),
)


@dataclass(frozen=True)
class SurveillanceAlertRecord:
    alert_id: str
    ts: dt.datetime
    market_state_id: str
    severity: AlertSeverity
    change_type: str
    what_changed: str
    content_hash: str
    expires_at_utc: dt.datetime
    policy_version: str = ALERT_POLICY_VERSION

    @property
    def is_severe(self) -> bool:
        """§30.6: severe alerts are never suppressed by normal throttling.
        CRITICAL always; MATERIAL data-integrity and blackout transitions
        qualify because they are the source-failure/position-protection
        class the section names."""
        if self.severity is AlertSeverity.CRITICAL:
            return True
        return self.severity is AlertSeverity.MATERIAL and self.change_type.startswith(
            ("data_quality", "news.unresolved_conflict", "macro.blackout_active")
        )


def severity_for(change: str, current_status: DataQualityStatus) -> AlertSeverity:
    if current_status is DataQualityStatus.FAILED and change.startswith("data_quality"):
        return AlertSeverity.CRITICAL
    for prefix, severity in _SEVERITY_BY_PREFIX:
        if change.startswith(prefix):
            return severity
    return AlertSeverity.INFO


def build_alerts(
    state: MarketStateObject,
    assessment: MaterialityAssessment,
    at: dt.datetime,
) -> list[SurveillanceAlertRecord]:
    """One alert per material change, content-hashed for dedup (§30.6)."""
    if at.tzinfo is None:
        raise ValueError("alert timestamps must be timezone-aware (§30.4, C-2)")
    alerts: list[SurveillanceAlertRecord] = []
    for change in assessment.material_changes:
        digest = hashlib.sha256(
            f"{state.instrument_id}|{change}".encode()
        ).hexdigest()
        alerts.append(
            SurveillanceAlertRecord(
                alert_id=f"alert.{digest[:16]}.{at.astimezone(dt.UTC):%Y%m%dT%H%M%S}",
                ts=at.astimezone(dt.UTC),
                market_state_id=state.market_state_id,
                severity=severity_for(change, state.data_quality.overall_status),
                change_type=change.split(" ")[0].rstrip(":"),
                what_changed=change,
                content_hash=digest,
                expires_at_utc=(at + ALERT_VALIDITY).astimezone(dt.UTC),
            )
        )
    return alerts


def deliverable(alert: SurveillanceAlertRecord, config: SurveillanceConfig) -> bool:
    """May this alert reach the owner's phone? Severe-only by owner decision
    (2026-07-31): severity at or above `alerts.telegram_minimum_severity`,
    with the whole surface behind `alerts_active`."""
    return alert.severity.at_least(config.alerts.telegram_minimum_severity) and (
        config.alerts_active
    )
