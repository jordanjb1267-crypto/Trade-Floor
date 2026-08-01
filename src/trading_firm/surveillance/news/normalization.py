"""News normalization and deduplication (§30.8, §30.6).

The content hash is the dedup key: a duplicate storm — the same story
recirculated across feeds and timestamps — collapses to one item instead of
one alert per copy. Publication time and event time are separate fields on
purpose (§30.17 unit row: publication-time versus event-time handling); a
story ABOUT yesterday published today must never backfill into yesterday's
decisions.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedNewsItem:
    news_item_id: str
    content_hash: str
    headline: str
    source_id: str
    publication_time_utc: dt.datetime
    event_time_utc: dt.datetime | None
    ingested_at_utc: dt.datetime


def content_hash(headline: str) -> str:
    """Hash of the normalized headline: casefolded, accent-stripped,
    whitespace-collapsed, punctuation-free — so 'GBP Rallies!' and
    'gbp  rallies' are the same story."""
    text = unicodedata.normalize("NFKD", headline)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", "", text.casefold())
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(text.encode()).hexdigest()


def normalize_item(
    *,
    headline: str,
    source_id: str,
    publication_time_utc: dt.datetime,
    ingested_at_utc: dt.datetime,
    event_time_utc: dt.datetime | None = None,
) -> NormalizedNewsItem:
    for name, value in (
        ("publication_time_utc", publication_time_utc),
        ("ingested_at_utc", ingested_at_utc),
    ):
        if value.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware (§30.8, C-2)")
    if event_time_utc is not None and event_time_utc.tzinfo is None:
        raise ValueError("event_time_utc must be timezone-aware (§30.8, C-2)")
    digest = content_hash(headline)
    return NormalizedNewsItem(
        news_item_id=f"news.{digest[:16]}",
        content_hash=digest,
        headline=headline.strip(),
        source_id=source_id,
        publication_time_utc=publication_time_utc.astimezone(dt.UTC),
        event_time_utc=(
            event_time_utc.astimezone(dt.UTC) if event_time_utc is not None else None
        ),
        ingested_at_utc=ingested_at_utc.astimezone(dt.UTC),
    )


def is_recirculation(
    item: NormalizedNewsItem,
    seen_hashes: dict[str, dt.datetime],
    window_seconds: int,
) -> bool:
    """Same content hash inside the duplicate window (config
    `news.duplicate_window_seconds`) is the same story again, not news."""
    first_seen = seen_hashes.get(item.content_hash)
    if first_seen is None:
        return False
    return (item.publication_time_utc - first_seen).total_seconds() <= window_seconds
