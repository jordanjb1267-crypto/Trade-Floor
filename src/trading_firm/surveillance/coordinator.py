"""The surveillance sweep (§30.9): one pass, observe-only, injected everywhere.

Refresh → build → materiality → alerts → dedup → record → (maybe) deliver.
Every side effect is an injected callable — state building, event recording,
owner notification — so a full sweep runs as a deterministic test with no
sockets and no disk, exactly like the supervisor it rides in.

The coordinator holds the only cross-sweep memory the discipline needs: the
prior published state (for change comparison) and the emitted-content ledger
(for throttling). Both reset with the process; a restart re-announces at
most one state, which the duplicate-collapse window absorbs.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass

from trading_firm.notify.surface import NotificationKind
from trading_firm.runner.schedule import ScheduledEvent
from trading_firm.surveillance.alerts import build_alerts, deliverable
from trading_firm.surveillance.config import SurveillanceConfig
from trading_firm.surveillance.deduplication import decide
from trading_firm.surveillance.events import EventType, SurveillanceEvent
from trading_firm.surveillance.materiality import MaterialityAssessment
from trading_firm.surveillance.schemas import DataQualityStatus, MarketStateObject

BuildState = Callable[[ScheduledEvent, "MarketStateObject | None"], "MarketStateObject | None"]
RecordEvent = Callable[[SurveillanceEvent], None]
Notify = Callable[[NotificationKind, str], bool]
Now = Callable[[], dt.datetime]


@dataclass(frozen=True)
class SweepResult:
    market_state_id: str | None
    material_changes: int
    alerts_built: int
    alerts_emitted: int
    delivered_to_owner: int

    def summary(self) -> str:
        if self.market_state_id is None:
            return "no state built (inputs unavailable — fail closed, §30.1)"
        return (
            f"state {self.market_state_id[:12]} changes={self.material_changes} "
            f"alerts={self.alerts_built} emitted={self.alerts_emitted} "
            f"delivered={self.delivered_to_owner}"
        )


class Coordinator:
    """Callable matching the supervisor's injected `Sweep` signature."""

    def __init__(
        self,
        *,
        config: SurveillanceConfig,
        build_state: BuildState,
        record_event: RecordEvent,
        notify: Notify,
        now: Now,
        configuration_version: str,
    ) -> None:
        self._config = config
        self._build_state = build_state
        self._record_event = record_event
        self._notify = notify
        self._now = now
        self._configuration_version = configuration_version
        self._prior: MarketStateObject | None = None
        self._emitted_at_by_hash: dict[str, dt.datetime] = {}

    def __call__(self, scheduled: ScheduledEvent) -> str:
        return self.run(scheduled).summary()

    def run(self, scheduled: ScheduledEvent) -> SweepResult:
        if not self._config.enabled:
            # Composition should never have wired a disabled coordinator, but
            # the master switch dominates here too (§30.12).
            return SweepResult(None, 0, 0, 0, 0)

        state = self._build_state(scheduled, self._prior)
        if state is None:
            return SweepResult(None, 0, 0, 0, 0)

        at = self._now()
        self._record(
            EventType.MARKET_STATE_PUBLISHED
            if state.data_quality.overall_status is not DataQualityStatus.FAILED
            else EventType.MARKET_STATE_DEGRADED,
            state,
            at,
            scheduled,
        )

        assessment = MaterialityAssessment(tuple(state.change_summary.material_changes))
        alerts = build_alerts(state, assessment, at)
        emitted = delivered = 0
        for alert in alerts:
            decision = decide(
                alert,
                self._emitted_at_by_hash,
                self._config.alerts.minimum_severity,
                state_change_only=self._config.alerts.state_change_only,
            )
            if not decision.should_emit:
                continue
            emitted += 1
            self._emitted_at_by_hash[alert.content_hash] = alert.ts
            self._record(
                EventType.OPPORTUNITY_MATERIAL_CHANGE_DETECTED, state, at, scheduled
            )
            if deliverable(alert, self._config):
                ok = self._notify(
                    NotificationKind.SURVEILLANCE_ALERT,
                    f"{alert.severity} {alert.what_changed} "
                    f"[{state.instrument_id}, state {state.market_state_id[:12]}]",
                )
                delivered += 1 if ok else 0

        self._prior = state
        return SweepResult(
            state.market_state_id,
            len(assessment.material_changes),
            len(alerts),
            emitted,
            delivered,
        )

    def _record(
        self,
        event_type: EventType,
        state: MarketStateObject,
        at: dt.datetime,
        scheduled: ScheduledEvent,
    ) -> None:
        try:
            self._record_event(
                SurveillanceEvent(
                    event_id=f"{event_type.value}.{state.market_state_id[:16]}.{at:%H%M%S}",
                    event_type=event_type,
                    schema_version="surveillance_event_v1",
                    event_time_utc=state.as_of_utc,
                    ingestion_time_utc=at.astimezone(dt.UTC),
                    producer="surveillance.coordinator",
                    instrument_scope=[state.instrument_id],
                    correlation_id=f"{scheduled.session_date}.{scheduled.event.value}",
                    configuration_version=self._configuration_version,
                    data_quality=state.data_quality.overall_status,
                    payload={"market_state_id": state.market_state_id},
                )
            )
        except Exception:  # noqa: BLE001, S110
            # A locked database must not take the sweep down (§30.17 failure
            # row); the missing event is visible as a gap in the outbox.
            pass
