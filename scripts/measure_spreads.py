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
        data/research/GBP_USD_M5_oanda_practice_2026-07-01_2026-07-29.json

Practice-feed caveat (F-5): spreads here are usable for modeling; fills and
slippage are not represented. NOT validation (§12.4).
"""

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
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    fixture = json.loads(Path(sys.argv[1]).read_text())
    meta = fixture["meta"]
    print(f"{meta['instrument']} {meta['granularity_minutes']}m from {meta['host']}")

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
