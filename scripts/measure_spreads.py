#!/usr/bin/env python3
"""Measure real bid/ask spreads from an OANDA practice fixture (§12.1).

Reads a fixture written by scripts/fetch_oanda_candles.py and reports
close-of-candle spreads in pips, bucketed by Europe/London hour, plus the
windows the firm actually cares about: the Asian range (00:00-07:00), the
London entry/manage window (07:00-11:00), and the 21:00 UTC rollover
blackout (F-5). Output informs the sizing engine's spread assumption —
currently a flat 2.0 pips (config/base/firm.yaml).

Usage:
    python3 scripts/measure_spreads.py \
        data/research/GBP_USD_M5_oanda_practice_2026-03-30_2026-07-29.json

Practice-feed caveat (F-5): spreads here are usable for modeling; fills and
slippage are not represented. NOT validation (§12.4).
"""

import argparse
import datetime as dt
import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
PIP = Decimal("0.0001")


def spread_pips(candle: dict) -> Decimal:
    return (Decimal(candle["ask"]["c"]) - Decimal(candle["bid"]["c"])) / PIP


def describe(label: str, values: list[Decimal]) -> None:
    if not values:
        print(f"  {label:<28} (no candles)")
        return
    floats = sorted(float(v) for v in values)
    p95 = floats[min(len(floats) - 1, int(0.95 * len(floats)))]
    print(
        f"  {label:<28} n={len(floats):>5} median={statistics.median(floats):.2f} "
        f"mean={statistics.fmean(floats):.2f} p95={p95:.2f} max={floats[-1]:.2f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture")
    parser.add_argument("--from", dest="date_from", help="inclusive ISO date (UTC)")
    parser.add_argument("--to", dest="date_to", help="inclusive ISO date (UTC)")
    args = parser.parse_args()

    fixture = json.loads(Path(args.fixture).read_text())
    meta = fixture["meta"]
    lo = dt.date.fromisoformat(args.date_from) if args.date_from else None
    hi = dt.date.fromisoformat(args.date_to) if args.date_to else None
    if lo or hi:
        kept = []
        for candle in fixture["candles"]:
            day = dt.datetime.fromisoformat(
                str(candle["time"]).replace("Z", "+00:00")
            ).astimezone(dt.UTC).date()
            if (lo is None or day >= lo) and (hi is None or day <= hi):
                kept.append(candle)
        fixture["candles"] = kept
    window = f" [{lo or 'start'}..{hi or 'end'}]" if (lo or hi) else ""
    print(
        f"{meta['instrument']} {meta['granularity_minutes']}m from {meta['host']}"
        f"{window}: {len(fixture['candles'])} candles"
    )

    by_london_hour: dict[int, list[Decimal]] = {}
    asian: list[Decimal] = []
    session: list[Decimal] = []
    rollover: list[Decimal] = []
    for candle in fixture["candles"]:
        ts = dt.datetime.fromisoformat(str(candle["time"]).replace("Z", "+00:00"))
        pips = spread_pips(candle)
        london = ts.astimezone(LONDON)
        by_london_hour.setdefault(london.hour, []).append(pips)
        if 0 <= london.hour < 7:
            asian.append(pips)
        elif 7 <= london.hour < 11:
            session.append(pips)
        utc = ts.astimezone(dt.UTC)
        if (utc.hour == 20 and utc.minute >= 30) or utc.hour == 21 or (
            utc.hour == 22 and utc.minute == 0
        ):
            rollover.append(pips)

    print("\nFirm windows (Europe/London):")
    describe("Asian range 00:00-07:00", asian)
    describe("London session 07:00-11:00", session)
    describe("rollover 20:30-22:00 UTC", rollover)

    print("\nBy London hour:")
    for hour in sorted(by_london_hour):
        describe(f"{hour:02d}:00", by_london_hour[hour])

    print(
        "\nSizing assumption in config: 2.0 pips. Practice-feed spreads only "
        "(F-5) — NOT validation (§12.4)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
