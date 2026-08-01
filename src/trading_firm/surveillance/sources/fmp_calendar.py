"""FMP economic-calendar normalization (§30.8; source `fmp`, decision D-7).

Normalization only — no polling lives here; the rows arrive from whatever
fetched them, and this module's whole job is the two disciplines FMP data
needs: an EXPLICIT source timezone (FMP timestamps arrive as naive local
times — the calendar-audit precedent that produced the same rule in
`market_data.bars.from_fmp_rows`), and revision versioning, so a corrected
release time becomes a new version and the record a decision was made on
survives (§30.1 rule 10).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from zoneinfo import ZoneInfo

from trading_firm.surveillance.schemas import UpcomingEvent

_IMPORTANCE = {"low": "low", "medium": "medium", "high": "high"}


def _event_id(row: Mapping[str, object], currency: str) -> str:
    # Identity is (event name, currency, original scheduled date): a revised
    # TIME is a new version of the same event, not a new event.
    scheduled = str(row.get("date", ""))[:10]
    blob = json.dumps([str(row.get("event", "")), currency, scheduled])
    return "fmp." + hashlib.sha256(blob.encode()).hexdigest()[:16]


def normalize_calendar(
    rows: list[Mapping[str, object]],
    source_tz: str,
) -> list[UpcomingEvent]:
    """FMP calendar rows -> typed events with aware UTC timestamps.

    `source_tz` is required and has no default on purpose: an unmarked
    timestamp interpreted in the wrong zone moves a release by hours, which
    is exactly the corrupted-input shape §30.1 rule 8 fails closed on.
    """
    zone = ZoneInfo(source_tz)
    out: list[UpcomingEvent] = []
    for row in rows:
        raw_date = row.get("date")
        currency = str(row.get("currency", "")).upper()
        if not raw_date or not currency:
            raise ValueError(f"calendar row lacks date or currency: {dict(row)!r} (§30.8)")
        naive = dt.datetime.fromisoformat(str(raw_date))
        if naive.tzinfo is not None:
            scheduled = naive.astimezone(dt.UTC)
        else:
            scheduled = naive.replace(tzinfo=zone).astimezone(dt.UTC)
        importance = _IMPORTANCE.get(str(row.get("impact", "")).lower(), "low")
        out.append(
            UpcomingEvent(
                event_id=_event_id(row, currency),
                scheduled_utc=scheduled,
                importance=importance,
                currency=currency,
            )
        )
    return sorted(out, key=lambda e: (e.scheduled_utc, e.event_id))


def revision_rows(
    normalized: list[UpcomingEvent],
    existing_versions: Mapping[str, int],
    source_id: str,
    ingested_at: dt.datetime,
    names: Mapping[str, str],
) -> list[dict[str, object]]:
    """economic_events rows, versioned per event id (migration 0002).

    A previously seen event gets version max+1 — the prior row is never
    touched. `existing_versions` maps event_id -> highest stored version.
    """
    rows: list[dict[str, object]] = []
    for event in normalized:
        version = existing_versions.get(event.event_id, 0) + 1
        rows.append(
            {
                "event_id": event.event_id,
                "version": version,
                "source_id": source_id,
                "currency": event.currency,
                "name": names.get(event.event_id, ""),
                "scheduled_utc": event.scheduled_utc.isoformat(),
                "importance": event.importance,
                "ingested_at": ingested_at.astimezone(dt.UTC).isoformat(),
            }
        )
    return rows
