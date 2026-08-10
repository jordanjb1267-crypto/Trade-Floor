"""OANDA v20 PRACTICE transport (§16, D-1). The live host does not exist here.

Hardened per the 2026-07-30 adversarial review:
- Connection failures, timeouts, and unparseable bodies raise
  TransportFailureError instead of escaping as raw urllib/json exceptions
  (findings 2, 15).
- HTTP error bodies are preserved when they parse — a 4xx carrying an
  orderRejectTransaction reaches the adapter as a rejection, never as an
  empty dict (finding 5).
- Client-order lookups use GET /orders?state=ALL and return a typed
  ClientOrderStatus, so FILLED market orders are found (the @clientID
  pending-order specifier 404s for them — finding 0/3). Window: the most
  recent 500 orders; the transactions-log walk is the Phase 6 upgrade path.

Per the 2026-07-30 lifecycle attempt:
- Credentials are validated before any network I/O, so a placeholder copied
  from .env.example is named as one rather than provoking a broker round trip.
- 401/403 raise BrokerAuthError instead of being preserved as a body; the
  preservation rule above is for order rejections, and applying it to auth
  failures reported a bad token as "no practice accounts on this token".

Token comes from the environment at construction (§17); never logged.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from trading_firm.execution.adapter import (
    BrokerAuthError,
    ClientOrderStatus,
    TransportFailureError,
)
from trading_firm.execution.credentials import (
    TOKEN_VAR,
    configured_account_id,
    practice_token,
)

PRACTICE_HOST = "https://api-fxpractice.oanda.com"  # practice ONLY (§13)

def _error_message(raw: str) -> str:
    """OANDA's own errorMessage, for diagnosis. Never includes the credential:
    the token travels in the request header, not in any response body."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return "unparseable body"
    message = parsed.get("errorMessage") if isinstance(parsed, dict) else None
    return str(message) if message else "no errorMessage in body"


_ORDER_STATE_MAP = {
    "PENDING": "PENDING",
    "TRIGGERED": "PENDING",
    "FILLED": "FILLED",
    "CANCELLED": "CANCELLED",
}


class OandaPracticeTransport:
    is_practice = True

    def __init__(
        self, account_id: str | None = None, timeout_seconds: float = 30.0
    ):
        # timeout_seconds bounds EACH request. The default preserves every
        # existing caller; the supervisor's verification probe passes a
        # tighter value so a retry schedule can be budgeted against the
        # §31.2 verification window instead of accidental urllib timing.
        self._timeout = timeout_seconds
        token = practice_token()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # Explicit argument wins, then the OANDA_DEMO_ACCOUNT_ID pin both
        # scripts document, then the first account on the token. Honoring the
        # pin matters on a token holding several practice accounts, where
        # "first" is whichever one OANDA happens to list first.
        self._account_id = account_id or configured_account_id() or self._first_account_id()

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            PRACTICE_HOST + path,
            method=method,
            headers=self._headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as err:
            raw = err.read().decode(errors="replace")
            if err.code in (401, 403):
                # A rejected credential carries no trading payload, so the
                # finding-5 preservation below must not apply to it: returning
                # {"errorMessage": ...} as an ordinary body made
                # _first_account_id report "no practice accounts on this
                # token" for what was really a bad token.
                raise BrokerAuthError(
                    f"HTTP {err.code} from the practice host on {method} {path}: "
                    f"credential rejected ({_error_message(raw)}). Check that "
                    f"{TOKEN_VAR} holds a current fxTrade Practice token — a live "
                    f"token is also rejected here by design (§13)."
                ) from err
            try:
                # Preserve error bodies: they carry orderRejectTransaction /
                # errorMessage, which are definitive answers (finding 5).
                return json.loads(raw)
            except json.JSONDecodeError:
                raise TransportFailureError(
                    f"HTTP {err.code} with unparseable body on {method} {path}"
                ) from err
        except TimeoutError as err:
            raise TransportFailureError(f"timeout on {method} {path}") from err
        except urllib.error.URLError as err:
            raise TransportFailureError(
                f"connection failure on {method} {path}: {err.reason}"
            ) from err
        except OSError as err:
            raise TransportFailureError(f"transport error on {method} {path}: {err}") from err
        except json.JSONDecodeError as err:
            raise TransportFailureError(f"unparseable response on {method} {path}") from err

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

    def lookup_client_order(self, client_order_id: str) -> ClientOrderStatus | None:
        """Resolve a client order id against recent orders in ANY state, so
        instantly-filled market orders are found (finding 0/3)."""
        listing = self._request(
            "GET", f"/v3/accounts/{self._account_id}/orders?state=ALL&count=500"
        )
        for order in listing.get("orders", []):
            if order.get("clientExtensions", {}).get("id") != client_order_id:
                continue
            state = _ORDER_STATE_MAP.get(str(order.get("state", "")))
            if state is None:
                raise TransportFailureError(
                    f"unknown order state '{order.get('state')}' for {client_order_id}"
                )
            trade_id = order.get("tradeOpenedID")
            return ClientOrderStatus(state=state, trade_id=str(trade_id) if trade_id else None)
        return None

    def get_trade(self, trade_id: str) -> dict | None:
        response = self._request("GET", f"/v3/accounts/{self._account_id}/trades/{trade_id}")
        return response.get("trade")

    def close_trade(self, trade_id: str) -> dict:
        return self._request(
            "PUT", f"/v3/accounts/{self._account_id}/trades/{trade_id}/close"
        )

    # -------------------------------------------------- reconciliation views
    def open_trade_ids(self) -> set[str]:
        return {trade["id"] for trade in self.open_trades()}

    def open_trades(self) -> list[dict]:
        return self._request(
            "GET", f"/v3/accounts/{self._account_id}/openTrades"
        ).get("trades", [])

    def account_summary(self) -> dict:
        return self._request("GET", f"/v3/accounts/{self._account_id}/summary")
