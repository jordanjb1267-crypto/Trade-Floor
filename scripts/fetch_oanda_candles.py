#!/usr/bin/env python3
"""Fetch OANDA v20 candles and write them as JSON fixtures.

Usage:
    OANDA_API_KEY=... python3 scripts/fetch_oanda_candles.py \
        --instruments GBP_USD,EUR_USD \
        --from 2026-07-01 --to 2026-07-29 \
        --granularity H1 \
        --out fixtures/oanda

Environment:
    OANDA_API_KEY   required, a v20 API personal access token
    OANDA_ENV       "practice" (default) or "live"

One fixture file is written per instrument, named
<INSTRUMENT>_<GRANULARITY>_<FROM>_<TO>.json, containing the instrument,
granularity, and the list of complete candles exactly as OANDA returns
them (time, volume, mid o/h/l/c).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

# OANDA rejects requests that would return more than 5000 candles, so we
# page with from+count and stop once we pass the end of the range.
MAX_COUNT = 5000


def parse_day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def fetch_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        sys.exit(f"OANDA request failed ({error.code}) for {url}: {detail}")


def fetch_candles(host: str, token: str, instrument: str, granularity: str,
                  start: datetime, end: datetime) -> list[dict]:
    candles: list[dict] = []
    cursor = start
    while cursor < end:
        query = urllib.parse.urlencode({
            "granularity": granularity,
            "price": "M",
            "from": cursor.isoformat().replace("+00:00", "Z"),
            "count": MAX_COUNT,
        })
        url = f"{host}/v3/instruments/{instrument}/candles?{query}"
        batch = fetch_json(url, token).get("candles", [])
        if not batch:
            break
        for candle in batch:
            time = datetime.fromisoformat(candle["time"].replace("Z", "+00:00"))
            if time >= end:
                return candles
            if candle.get("complete"):
                candles.append(candle)
        last = datetime.fromisoformat(batch[-1]["time"].replace("Z", "+00:00"))
        if last <= cursor:
            break
        cursor = last + timedelta(seconds=1)
        if len(batch) < MAX_COUNT:
            break
    return candles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instruments", required=True,
                        help="comma-separated, e.g. GBP_USD,EUR_USD")
    parser.add_argument("--from", dest="start", required=True, type=parse_day,
                        help="first day, inclusive (YYYY-MM-DD, UTC)")
    parser.add_argument("--to", dest="end", required=True, type=parse_day,
                        help="last day, inclusive (YYYY-MM-DD, UTC)")
    parser.add_argument("--granularity", default="H1",
                        help="OANDA granularity code (default H1)")
    parser.add_argument("--out", default="fixtures/oanda", type=Path,
                        help="output directory (default fixtures/oanda)")
    args = parser.parse_args()

    token = os.environ.get("OANDA_API_KEY")
    if not token:
        sys.exit("OANDA_API_KEY is not set; a v20 API token is required.")
    env = os.environ.get("OANDA_ENV", "practice")
    if env not in HOSTS:
        sys.exit(f"OANDA_ENV must be one of {sorted(HOSTS)}, got {env!r}.")

    end_exclusive = args.end + timedelta(days=1)
    args.out.mkdir(parents=True, exist_ok=True)

    for instrument in args.instruments.split(","):
        instrument = instrument.strip()
        candles = fetch_candles(HOSTS[env], token, instrument,
                                args.granularity, args.start, end_exclusive)
        fixture = {
            "instrument": instrument,
            "granularity": args.granularity,
            "from": args.start.date().isoformat(),
            "to": args.end.date().isoformat(),
            "candles": candles,
        }
        path = args.out / (f"{instrument}_{args.granularity}_"
                           f"{fixture['from']}_{fixture['to']}.json")
        path.write_text(json.dumps(fixture, indent=2) + "\n")
        print(f"{path}: {len(candles)} candles")


if __name__ == "__main__":
    main()
