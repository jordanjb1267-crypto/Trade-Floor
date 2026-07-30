"""OANDA v20 PRACTICE transport (§16, D-1). The live host does not exist here.

Token comes from the environment at construction (§17); it is never logged.
This module is wire plumbing only — every order request reaching it has
already passed the deterministic gates in BrokerAdapter (§2).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

PRACTICE_HOST = "https://api-fxpractice.oanda.com"  # practice ONLY (§13)


class OandaPracticeTransport:
    is_practice = True

    def __init__(self, account_id: str | None = None):
        token = os.environ.get("OANDA_DEMO_API_TOKEN")
        if not token:
            raise RuntimeError("OANDA_DEMO_API_TOKEN not set (see .env.example; §17)")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._account_id = account_id or self._first_account_id()

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            PRACTICE_HOST + path,
            method=method,
            headers=self._headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return {}
            return json.loads(err.read().decode())

    def _first_account_id(self) -> str:
        accounts = self._request("GET", "/v3/accounts").get("accounts", [])
        if not accounts:
            raise RuntimeError("no practice accounts on this token")
        return accounts[0]["id"]

    # ------------------------------------------------------------ transport
    def create_market_order(
        self, *, instrument: str, units: int, stop_loss_price: str, client_order_id: str
    ) -> dict:
        body = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": stop_loss_price},
                "clientExtensions": {"id": client_order_id},
            }
        }
        return self._request("POST", f"/v3/accounts/{self._account_id}/orders", body)

    def find_order_by_client_id(self, client_order_id: str) -> dict | None:
        found = self._request(
            "GET", f"/v3/accounts/{self._account_id}/orders/@{client_order_id}"
        )
        return found or None

    def get_trade(self, trade_id: str) -> dict | None:
        return self._request(
            "GET", f"/v3/accounts/{self._account_id}/trades/{trade_id}"
        ).get("trade")

    def close_trade(self, trade_id: str) -> dict:
        return self._request(
            "PUT", f"/v3/accounts/{self._account_id}/trades/{trade_id}/close"
        )

    # -------------------------------------------------- reconciliation views
    def open_trade_ids(self) -> set[str]:
        trades = self._request(
            "GET", f"/v3/accounts/{self._account_id}/openTrades"
        ).get("trades", [])
        return {trade["id"] for trade in trades}

    def account_summary(self) -> dict:
        return self._request("GET", f"/v3/accounts/{self._account_id}/summary")
