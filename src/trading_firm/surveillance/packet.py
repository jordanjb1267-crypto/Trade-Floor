"""The surveillance packet for the senior traders (§30.5).

Extends what Alpha and Beta receive without touching the existing
`MarketStatePacket`: this is the surveillance HALF, referenced from the
candidate and delivered beside the §6A packet. Serialized, checksummed, and
provided identically to both senior traders before either first-pass
analysis begins — identity is the checksum, so "both received the same
packet" and "neither received an altered packet" are one property, exactly
as `MarketStateObject` works.

**What is deliberately absent (§30.5, A-3 tightening):** the open-position
contradiction packet. The uploaded amendment listed it as a first-pass
component; §5.1 [A-2] makes firm state in classification input a type
error, so contradiction material is post-entry only
(`surveillance/monitoring.py`, `surveillance/positions/`) and this module
has no field it could travel in. Do not include another agent's narrative
thesis in the first-pass packet.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, field_validator

from trading_firm.packet import _digest
from trading_firm.surveillance.schemas import (
    MarketStateObject,
    UpcomingEvent,
    _aware,
)

SURVEILLANCE_PACKET_VERSION = "surveillance_packet_v1"


class SurveillancePacket(BaseModel):
    """§30.5 components as references plus compact snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    packet_version: str
    created_at_utc: dt.datetime
    market_state: MarketStateObject
    prior_material_state_id: str | None
    feature_snapshot_id: str | None
    scheduled_events: tuple[UpcomingEvent, ...]
    verified_news_item_ids: tuple[str, ...]
    source_health: Mapping[str, str]
    data_limitations: tuple[str, ...]

    _aware_created = field_validator("created_at_utc")(_aware)

    @property
    def packet_id(self) -> str:
        payload = self.model_dump(mode="python")
        payload["source_health"] = dict(sorted(self.source_health.items()))
        return _digest(payload)

    def verify(self, expected_packet_id: str) -> None:
        """§30.5: Alpha and Beta receive identical checksums. A mismatch is
        an altered packet, and an altered packet is refused, not repaired."""
        actual = self.packet_id
        if actual != expected_packet_id:
            raise ValueError(
                f"surveillance packet checksum mismatch: expected "
                f"{expected_packet_id}, computed {actual} (§30.5)"
            )
        self.market_state.verify(self.market_state.market_state_id)


def build_packet(
    *,
    market_state: MarketStateObject,
    prior_material_state_id: str | None,
    scheduled_events: tuple[UpcomingEvent, ...] = (),
    verified_news_item_ids: tuple[str, ...] = (),
    source_health: Mapping[str, str] | None = None,
    created_at_utc: dt.datetime,
) -> SurveillancePacket:
    """Assemble the packet from what the sweep already holds. Data
    limitations are derived, never asserted: whatever the state's quality
    block says is missing or stale IS the limitations list."""
    limitations = tuple(
        f"{kind}:{component}"
        for kind, components in (
            ("missing", market_state.data_quality.missing_components),
            ("stale", market_state.data_quality.stale_components),
            ("conflicting", market_state.data_quality.conflicting_components),
        )
        for component in components
    )
    return SurveillancePacket(
        packet_version=SURVEILLANCE_PACKET_VERSION,
        created_at_utc=created_at_utc,
        market_state=market_state,
        prior_material_state_id=prior_material_state_id,
        feature_snapshot_id=market_state.feature_snapshot_id,
        scheduled_events=scheduled_events,
        verified_news_item_ids=verified_news_item_ids,
        source_health=dict(source_health or {}),
        data_limitations=limitations,
    )
