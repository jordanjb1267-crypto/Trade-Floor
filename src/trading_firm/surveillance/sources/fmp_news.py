"""FMP news normalization (§30.8; source `fmp.news`, research-only).

Normalization only — the news domain ships disabled and nothing polls. FMP
news rows carry timestamps whose zone must be stated explicitly by the
caller, the same discipline as the calendar adapter; a single-provider item
can never exceed SINGLE_SOURCE verification (§30.3.H), which the
verification module enforces by counting independent registered sources.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from zoneinfo import ZoneInfo

from trading_firm.surveillance.news.normalization import (
    NormalizedNewsItem,
    normalize_item,
)

SOURCE_ID = "fmp.news"


def normalize_news(
    rows: list[Mapping[str, object]],
    source_tz: str,
    ingested_at_utc: dt.datetime,
) -> list[NormalizedNewsItem]:
    zone = ZoneInfo(source_tz)
    out: list[NormalizedNewsItem] = []
    for row in rows:
        headline = str(row.get("title", "")).strip()
        published = row.get("publishedDate")
        if not headline or not published:
            raise ValueError(f"news row lacks title or publishedDate: {dict(row)!r} (§30.8)")
        naive = dt.datetime.fromisoformat(str(published))
        publication = (
            naive.astimezone(dt.UTC)
            if naive.tzinfo is not None
            else naive.replace(tzinfo=zone).astimezone(dt.UTC)
        )
        out.append(
            normalize_item(
                headline=headline,
                source_id=SOURCE_ID,
                publication_time_utc=publication,
                ingested_at_utc=ingested_at_utc,
            )
        )
    return out
