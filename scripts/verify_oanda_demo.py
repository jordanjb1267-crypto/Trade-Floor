#!/usr/bin/env python3
"""Phase 0 broker-audit probe: OANDA fxTrade Practice (demo) connection check.

Read-only. Performs the Master Handoff v1.1.0 §16 connection checks against
the PRACTICE environment only — this script refuses to touch the live host by
design (§13 staging: demo before live). It submits no orders.

Usage:
    OANDA_DEMO_API_TOKEN=<token> python3 scripts/verify_oanda_demo.py

Optional:
    OANDA_DEMO_ACCOUNT_ID=<id>   # otherwise the first account on the token is used

Output redacts account IDs (§17). Never pass a live token here; live
credentials must stay separate (§17).
"""

import json
import os
import sys
import urllib.error
import urllib.request

HOST = "api-fxpractice.oanda.com"  # practice ONLY — do not change to fxtrade (§13)
INSTRUMENTS = ["GBP_USD", "EUR_USD"]


def redact(account_id: str) -> str:
    return account_id[:8] + "…" + account_id[-3:] if len(account_id) > 11 else "…"


def get(token: str, path: str):
    req = urllib.request.Request(
        f"https://{HOST}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> int:
    token = os.environ.get("OANDA_DEMO_API_TOKEN")
    if not token:
        print("FAIL: set OANDA_DEMO_API_TOKEN (never hard-code it; see .env.example)")
        return 2

    checks: list[tuple[str, bool, str]] = []

    try:
        accounts = get(token, "/v3/accounts")["accounts"]
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("FAIL: 401 Unauthorized on the PRACTICE host. Either the token is")
            print("      invalid, or it belongs to a LIVE account. This script will")
            print("      not probe the live host; generate a practice token at")
            print("      fxTrade Practice and retry.")
        else:
            print(f"FAIL: HTTP {e.code} from {HOST}: {e.read().decode()[:200]}")
        return 1

    checks.append(("API reachable, token accepted (practice)", True, HOST))
    account_id = os.environ.get("OANDA_DEMO_ACCOUNT_ID") or accounts[0]["id"]
    print(f"Accounts on token: {len(accounts)}; auditing {redact(account_id)}\n")

    summary = get(token, f"/v3/accounts/{account_id}/summary")["account"]
    currency = summary.get("currency")
    margin_rate = float(summary.get("marginRate", "0"))
    checks.append(("Account currency is USD", currency == "USD", f"currency={currency}"))
    checks.append(
        (
            "Margin rate consistent with US 50:1 majors cap",
            margin_rate >= 0.02,
            f"marginRate={margin_rate} (leverage {1 / margin_rate:.0f}:1)"
            if margin_rate
            else "marginRate missing",
        )
    )
    checks.append(
        (
            "Equity endpoint returns balance/NAV",
            "balance" in summary and "NAV" in summary,
            f"balance={summary.get('balance')} NAV={summary.get('NAV')}",
        )
    )
    checks.append(
        (
            "Hedging disabled (NFA FIFO expectation)",
            summary.get("hedgingEnabled") is False,
            f"hedgingEnabled={summary.get('hedgingEnabled')}",
        )
    )

    instruments = get(
        token,
        f"/v3/accounts/{account_id}/instruments?instruments={','.join(INSTRUMENTS)}",
    )["instruments"]
    by_name = {i["name"]: i for i in instruments}
    for name in INSTRUMENTS:
        inst = by_name.get(name)
        if not inst:
            checks.append((f"{name} tradeable on account", False, "not returned"))
            continue
        min_size = float(inst["minimumTradeSize"])
        precision = int(inst["tradeUnitsPrecision"])
        checks.append(
            (
                f"{name}: 1-unit granularity (deciding constraint, §16 annex)",
                min_size <= 1 and precision == 0,
                f"minimumTradeSize={min_size} tradeUnitsPrecision={precision} "
                f"pipLocation={inst.get('pipLocation')} marginRate={inst.get('marginRate')}",
            )
        )

    pricing = get(
        token,
        f"/v3/accounts/{account_id}/pricing?instruments={','.join(INSTRUMENTS)}",
    )["prices"]
    for p in pricing:
        name = p["instrument"]
        bid = float(p["bids"][0]["price"])
        ask = float(p["asks"][0]["price"])
        spread_pips = (ask - bid) / 0.0001
        checks.append(
            (
                f"{name}: live pricing, spread sane (< 3 pips at quiet hours)",
                0 < spread_pips < 3,
                f"bid={bid} ask={ask} spread={spread_pips:.1f} pips "
                f"tradeable={p.get('tradeable')}",
            )
        )

    print(f"{'RESULT':<6} CHECK")
    failures = 0
    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL':<6} {label}\n       {detail}")
        failures += 0 if ok else 1

    print(
        f"\n{len(checks) - failures}/{len(checks)} checks passed. "
        + ("Demo connection audit: OK." if failures == 0 else "Resolve failures before Phase 0 sign-off.")
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
