#!/usr/bin/env python3
"""Phase 4 demo order-lifecycle test against the OANDA PRACTICE account (§22).

Places ONE 1-unit EUR_USD market order with a broker-held stop, verifies the
stop is active, closes the trade, and verifies the account is flat. This is a
TRANSPORT lifecycle validation (order mechanics, §22 Phase 4 'Demo lifecycle
tests'), not a strategy trade — strategy entries go through the full §2 path
inside the session window only.

Guards: practice host only; requires OANDA_DEMO_API_TOKEN and the explicit
--confirm-demo-order flag; refuses to run if the account already has open
trades (never disturbs live state).

Usage:
    OANDA_DEMO_API_TOKEN=<practice token> \
        python3 scripts/broker_sandbox_lifecycle.py --confirm-demo-order
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_firm.env_file import load_env_file  # noqa: E402
from trading_firm.execution.oanda_transport import OandaPracticeTransport  # noqa: E402


def main() -> int:
    if "--confirm-demo-order" not in sys.argv:
        print("Refusing to run: pass --confirm-demo-order to place a 1-unit demo order.")
        return 2

    load_env_file()  # §17: an untracked .env is read; exported vars still win

    checks: list[tuple[str, bool, str]] = []
    transport = OandaPracticeTransport()

    summary = transport.account_summary().get("account", {})
    checks.append(("account reachable", bool(summary), f"balance={summary.get('balance')}"))
    if int(summary.get("openTradeCount", 0)) > 0:
        print("Refusing to run: account already has open trades.")
        return 2

    pricing = transport._request(  # noqa: SLF001 — lifecycle script, read-only call
        "GET",
        f"/v3/accounts/{transport._account_id}/pricing?instruments=EUR_USD",  # noqa: SLF001
    )
    price = Decimal(pricing["prices"][0]["closeoutBid"])
    stop_price = (price - Decimal("0.0050")).quantize(Decimal("0.00001"))
    checks.append(("pricing fetched", True, f"bid={price}"))

    response = transport.create_market_order(
        instrument="EUR_USD",
        units=1,
        stop_loss_price=str(stop_price),
        client_order_id="clltf-lifecycle-test",
    )
    fill = response.get("orderFillTransaction")
    checks.append(("1-unit market order filled", fill is not None, str(response)[:160]))
    if fill is None:
        _report(checks)
        return 1

    trade_id = fill["tradeOpened"]["tradeID"]
    trade = transport.get_trade(trade_id) or {}
    stop = trade.get("stopLossOrder")
    checks.append(
        (
            "broker-held stop confirmed active (§0.9)",
            stop is not None and stop.get("state") in ("PENDING", "TRIGGERED"),
            f"stop={stop}",
        )
    )

    close = transport.close_trade(trade_id)
    closed = "orderFillTransaction" in close
    checks.append(("trade closed", closed, str(close)[:120]))

    flat = transport.open_trade_ids() == set()
    checks.append(("account flat after lifecycle", flat, ""))

    _report(checks)
    return 0 if all(passed for _, passed, _ in checks) else 1


def _report(checks: list[tuple[str, bool, str]]) -> None:
    print(f"\n{'RESULT':<6} CHECK")
    for label, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL':<6} {label}\n       {detail}")
    total = len(checks)
    good = sum(1 for _, passed, _ in checks if passed)
    print(f"\n{good}/{total} lifecycle checks passed.")


if __name__ == "__main__":
    sys.exit(main())
