"""Surveillance event envelope and vocabulary (§30.6).

The event mechanism is deliberately small: typed envelopes over the existing
architecture, durably recorded in the SQLite outbox (`surveillance_events`,
migration 0002). No Kafka, no Redis, no cloud queues (§30.6, §23).

Event types are a closed StrEnum — the §30.6 families exactly. An
unregistered event type is unrepresentable, which is what makes the event
stream auditable: every record's type resolves to a spec-defined family.
"""

from __future__ import annotations

import datetime as dt
import enum
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from trading_firm.packet import _canonical, _digest
from trading_firm.surveillance.schemas import DataQualityStatus, _aware

EVENT_SCHEMA_VERSION = "surveillance_event_v1"


class EventType(enum.StrEnum):
    """§30.6 required event families — all twenty-two, nothing else."""

    MARKET_DATA_RECEIVED = "market_data.received"
    MARKET_DATA_STALE = "market_data.stale"
    BAR_CLOSED = "bar.closed"
    FEATURE_SNAPSHOT_CREATED = "feature.snapshot.created"
    MARKET_STATE_PUBLISHED = "market_state.published"
    MARKET_STATE_DEGRADED = "market_state.degraded"
    REGIME_CHANGED = "regime.changed"
    STRUCTURE_LEVEL_REACHED = "structure.level_reached"
    STRUCTURE_BREAK_DETECTED = "structure.break_detected"
    STRUCTURE_FAILED_BREAK_DETECTED = "structure.failed_break_detected"
    VOLATILITY_THRESHOLD_CROSSED = "volatility.threshold_crossed"
    SPREAD_THRESHOLD_CROSSED = "spread.threshold_crossed"
    ECONOMIC_EVENT_UPCOMING = "economic_event.upcoming"
    ECONOMIC_EVENT_RELEASED = "economic_event.released"
    NEWS_ITEM_INGESTED = "news.item_ingested"
    NEWS_ITEM_VERIFIED = "news.item_verified"
    NEWS_CONFLICT_DETECTED = "news.conflict_detected"
    CROSS_MARKET_DIVERGENCE_DETECTED = "cross_market.divergence_detected"
    OPPORTUNITY_MATERIAL_CHANGE_DETECTED = "opportunity.material_change_detected"
    POSITION_CONTRADICTION_DETECTED = "position.contradiction_detected"
    SOURCE_HEALTH_CHANGED = "source.health_changed"
    SURVEILLANCE_BRIEFING_DUE = "surveillance.briefing_due"


class SurveillanceEvent(BaseModel):
    """§30.6 envelope. Every field the section requires, nothing extra."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    event_type: EventType
    schema_version: Literal["surveillance_event_v1"]
    event_time_utc: dt.datetime
    ingestion_time_utc: dt.datetime
    producer: str
    instrument_scope: list[str]
    correlation_id: str
    configuration_version: str
    data_quality: DataQualityStatus
    payload: dict[str, object]

    _aware_event = field_validator("event_time_utc")(_aware)
    _aware_ingest = field_validator("ingestion_time_utc")(_aware)

    @field_validator("payload")
    @classmethod
    def _payload_is_canonical(cls, value: dict[str, object]) -> dict[str, object]:
        # Fails now rather than at persistence time: an event that cannot be
        # reproduced from stored inputs violates §30.1 rule 10.
        try:
            _canonical(value)
        except (TypeError, ValueError) as err:
            raise ValueError(f"event payload is not canonically serializable: {err}") from err
        return value

    @property
    def payload_checksum(self) -> str:
        return _digest(self.payload)

    def to_row(self) -> Mapping[str, object]:
        """Column mapping for the surveillance_events outbox (migration 0002)."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "schema_version": self.schema_version,
            "event_time_utc": self.event_time_utc.astimezone(dt.UTC).isoformat(),
            "ingestion_time_utc": self.ingestion_time_utc.astimezone(dt.UTC).isoformat(),
            "producer": self.producer,
            "instrument_scope": json.dumps(sorted(self.instrument_scope)),
            "correlation_id": self.correlation_id,
            "configuration_version": self.configuration_version,
            "data_quality": self.data_quality.value,
            "payload_json": json.dumps(_canonical(self.payload), sort_keys=True),
            "payload_checksum": self.payload_checksum,
        }


_INSERT = (
    "INSERT INTO surveillance_events (event_id, event_type, schema_version, "
    "event_time_utc, ingestion_time_utc, producer, instrument_scope, "
    "correlation_id, configuration_version, data_quality, payload_json, "
    "payload_checksum) VALUES (:event_id, :event_type, :schema_version, "
    ":event_time_utc, :ingestion_time_utc, :producer, :instrument_scope, "
    ":correlation_id, :configuration_version, :data_quality, :payload_json, "
    ":payload_checksum)"
)


def record_event(conn, event: SurveillanceEvent) -> None:
    """Append to the durable outbox (§30.6). The primary key makes replayed
    ids a hard error rather than a silent duplicate — an event happened once."""
    conn.execute(_INSERT, dict(event.to_row()))
    conn.commit()
