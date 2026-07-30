#!/usr/bin/env python3
"""Fetch OANDA practice M5 candles into a research fixture (read-only, §12.1).

This is the sanctioned way to pull OANDA market data for research: a
deterministic script against the PRACTICE host only. It submits nothing,
modifies nothing, and has no environment parameter — live routing is
unrepresentable here by construction (§13; same posture as the execution
transport). Order placement remains exclusively the deterministic broker
adapter's job (§0 iron rule 1).

Usage:
    OANDA_DEMO_API_TOKEN=<token> python3 scripts/fetch_oanda_candles.py \
        GBP_USD 2026-07-01 2026-07-29

Writes data/research/<INSTRUMENT>_M5_oanda_practice_<from>_<to>.json with
raw mid/ask/bid candles preserved (real spreads for research, replacing the
2-pip assumption when replay grows spread support) plus provenance metadata.
Fails closed: missing token, unreachable host, or any HTTP error aborts
with no partial file written.
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_firm.env_file import load_env_file  # noqa: E402
from trading_firm.market_data.candle_fixture import build_fixture, chunk_ranges  # noqa: E402

HOST = "api-fxpractice.oanda.com"  # practice ONLY — never fxtrade (§13, F-2)
GRANULARITY = "M5"
GRANULARITY_MINUTES = 5
DAYS_PER_REQUEST = 10  # 10d x 288 M5 candles = 2880 < the 5000/request cap


def get_json(token: str, path: str, params: dict) -> dict:
    url = f"https://{HOST}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    instrument = sys.argv[1]
    try:
        start = dt.date.fromisoformat(sys.argv[2])
        end = dt.date.fromisoformat(sys.argv[3])
    except ValueError as err:
        print(f"FAIL: bad date argument: {err}")
        return 2

    load_env_file()  # §17: an untracked .env is read; exported vars still win
    token = os.environ.get("OANDA_DEMO_API_TOKEN")
    if not token:
        print("FAIL (closed): set OANDA_DEMO_API_TOKEN — never hard-code it")
        print("(see .env.example; rotate any token that has passed through chat)")
        return 2

    candles: list[dict] = []
    try:
        for window_from, window_to in chunk_ranges(
            start, end, days_per_request=DAYS_PER_REQUEST
        ):
            payload = get_json(
                token,
                f"/v3/instruments/{instrument}/candles",
                {
                    "granularity": GRANULARITY,
                    "price": "MAB",
                    "from": window_from.isoformat(),
                    "to": window_to.isoformat(),
                    "includeFirst": "true",
                },
            )
            batch = payload.get("candles", [])
            candles.extend(batch)
            print(f"  {window_from.date()} → {window_to.date()}: {len(batch)} candles")
    except urllib.error.HTTPError as err:
        if err.code == 401:
            print("FAIL (closed): 401 on the PRACTICE host — invalid token, or a")
            print("live token (this script will not probe the live host).")
        else:
            print(f"FAIL (closed): HTTP {err.code} from {HOST}")
        return 1
    except (urllib.error.URLError, OSError) as err:
        print(f"FAIL (closed): cannot reach {HOST}: {err}")
        print("(In a Claude Code VM this usually means the egress network policy;")
        print("policy changes apply only to freshly created VMs. Run locally or")
        print("in a fresh session.)")
        return 1

    fixture, series = build_fixture(
        candles,
        instrument=instrument,
        granularity_minutes=GRANULARITY_MINUTES,
        host=HOST,
        fetched_at=dt.datetime.now(dt.UTC),
    )
    out = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "research"
        / f"{instrument}_M5_oanda_practice_{start}_{end}.json"
    )
    out.write_text(json.dumps(fixture, indent=1) + "\n")

    meta = fixture["meta"]
    print(
        f"\n{instrument}: {meta['candle_count']} candles → "
        f"{meta['normalized_bar_count']} bars, "
        f"{len(meta['quality_events'])} quality events"
    )
    for event in meta["quality_events"][:10]:
        print(f"  quality: {event}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
