"""Deterministic Telegram notification path (§18).

§18's minimum operational requirements include "Local notifications plus
optional Telegram/Discord notification path"; this module is that optional
path, kept deliberately dumb: one bounded HTTPS POST to api.telegram.org,
stdlib only, deterministic end to end.

Three properties are load-bearing:

- **Not an order path (§0 iron rule 1).** This module carries text OUT to
  the owner; nothing comes back in. It imports no broker code — only the
  shared §17 credential preflight — and exposes nothing an agent could bend
  toward the broker.

- **Advisory, so it never raises (§18).** `send()` and `get_me()` return a
  `NotifyResult` in every case, including misconfiguration and transport
  bugs. A notification channel that can crash the process it reports on
  inverts the reliability it exists to serve; runtime callers record a
  failed result and continue (§0 iron rule 6). The verification script, by
  contrast, treats any failed result as a hard FAIL — advisory at runtime
  does not mean unverified at acceptance.

- **Sanitized errors (§0 iron rule 5).** Telegram's API design puts the bot
  token in the request URL, so a naive traceback leaks it. Every transport
  error is caught and reduced to a bounded, human-readable detail; the URL
  never enters a result, and both token and chat id are scrubbed from all
  detail text as defense in depth. Chat ids are redacted in output the way
  §17 requires of account ids.

Retries are deterministic: one fixed-delay re-attempt on transport errors,
HTTP 5xx, and 429 rate limits; none on any other 4xx (a rejected request
stays rejected). No randomness, no jitter.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace

from trading_firm.execution.credentials import CredentialError, validate_credential

BOT_TOKEN_VAR = "TELEGRAM_BOT_TOKEN"
CHAT_ID_VAR = "TELEGRAM_CHAT_ID"

API_HOST = "api.telegram.org"  # notification host only — no broker host may appear here
TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS = 2  # one send, one fixed-delay retry — bounded by design
RETRY_DELAY_SECONDS = 2.0
MAX_TEXT_CHARS = 4096  # Telegram's hard limit; longer text is truncated, never rejected
DETAIL_LIMIT = 200

_ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
_REDACTED = "[redacted]"

# transport(url, request_body, timeout) -> (http_status, response_body).
# The default is urllib; tests inject fakes so no unit test opens a socket.
Transport = Callable[[str, bytes, float], tuple[int, bytes]]
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class NotifyResult:
    """Outcome of one notification call.

    `detail` is bounded, human-readable, and never contains a secret; it is
    safe to log verbatim (§17). `stage` is "preflight" when nothing left the
    machine, "api" once a request was attempted.
    """

    ok: bool
    stage: str
    detail: str
    status: int | None = None
    message_id: int | None = None
    attempts: int = 0


def preflight() -> tuple[str, str]:
    """Resolve (bot token, chat id) or raise CredentialError before any I/O.

    On top of the shared §17 checks, a token without the ':' every Telegram
    bot token carries cannot possibly be real, so it is refused locally
    (fail closed, §0 iron rule 3) instead of being sent to Telegram to come
    back as a 401.
    """
    token = validate_credential(BOT_TOKEN_VAR, os.environ.get(BOT_TOKEN_VAR))
    chat_id = validate_credential(CHAT_ID_VAR, os.environ.get(CHAT_ID_VAR))
    if ":" not in token:
        raise CredentialError(
            f"{BOT_TOKEN_VAR} lacks the ':' separator every bot token has, so it "
            f"cannot be a Telegram bot token (§17). Nothing was sent."
        )
    return token, chat_id


def redact_chat_id(chat_id: str) -> str:
    """First two and last two characters only — §17 account-id redaction, applied
    to the identifier of the owner's chat."""
    return chat_id[:2] + _ELLIPSIS + chat_id[-2:] if len(chat_id) > 6 else _ELLIPSIS


def send(
    text: str, *, transport: Transport | None = None, sleep: Sleep | None = None
) -> NotifyResult:
    """Send one plain-text message to the configured owner chat. Never raises.

    Text goes verbatim with no parse mode, so no markup can change what the
    owner reads. Text over the 4096-char limit is truncated with a visible
    mark rather than rejected — a cut-off alert still alerts (§18). Empty
    text is refused locally: there is nothing to deliver.
    """
    if not text or not text.strip():
        return NotifyResult(
            ok=False, stage="preflight", detail="empty message text; nothing to send"
        )
    try:
        token, chat_id = preflight()
    except CredentialError as err:
        return NotifyResult(ok=False, stage="preflight", detail=str(err))
    if len(text) > MAX_TEXT_CHARS:
        text = text[: MAX_TEXT_CHARS - 1] + _ELLIPSIS
    return _call(
        "sendMessage",
        {"chat_id": chat_id, "text": text},
        token=token,
        chat_id=chat_id,
        transport=transport if transport is not None else _default_transport,
        sleep=sleep if sleep is not None else time.sleep,
    )


def get_me(*, transport: Transport | None = None, sleep: Sleep | None = None) -> NotifyResult:
    """Prove the token resolves to a live bot without sending anything. Never raises."""
    try:
        token, chat_id = preflight()
    except CredentialError as err:
        return NotifyResult(ok=False, stage="preflight", detail=str(err))
    return _call(
        "getMe",
        {},
        token=token,
        chat_id=chat_id,
        transport=transport if transport is not None else _default_transport,
        sleep=sleep if sleep is not None else time.sleep,
    )


def _call(
    method: str,
    payload: dict[str, object],
    *,
    token: str,
    chat_id: str,
    transport: Transport,
    sleep: Sleep,
) -> NotifyResult:
    secrets = (token, chat_id)
    # A real bot token is [0-9]+:[A-Za-z0-9_-]+, which passes through quote()
    # byte-identical (":" is kept explicitly); anything else — say a value
    # containing "/" — is percent-encoded so it cannot rewrite the path.
    url = f"https://{API_HOST}/bot{urllib.parse.quote(token, safe=':')}/{method}"
    body = json.dumps(payload).encode()
    last = NotifyResult(ok=False, stage="api", detail="no attempt made")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        outcome, retryable = _one_attempt(url, body, transport, secrets)
        last = replace(outcome, attempts=attempt)
        if last.ok or not retryable:
            return last
        if attempt < MAX_ATTEMPTS:
            sleep(RETRY_DELAY_SECONDS)
    return last


def _one_attempt(
    url: str, body: bytes, transport: Transport, secrets: tuple[str, ...]
) -> tuple[NotifyResult, bool]:
    """One request. Returns (result, retryable). Catches everything (§18)."""
    try:
        status, raw = transport(url, body, TIMEOUT_SECONDS)
    except OSError as err:
        # URLError (timeouts included) and every socket/TLS failure. str() of
        # these never includes the URL, but the scrub does not rely on that.
        return (
            NotifyResult(ok=False, stage="api", detail=_bounded(_reason_text(err), secrets)),
            True,
        )
    except Exception as err:  # a broken injected transport must not crash the caller
        detail = _bounded(f"unexpected {type(err).__name__}: {err}", secrets)
        return NotifyResult(ok=False, stage="api", detail=detail), False

    parsed = _parse_body(raw)
    if status == 200 and parsed.get("ok") is True:
        result = parsed.get("result")
        fields = result if isinstance(result, dict) else {}
        message_id = fields.get("message_id")
        username = fields.get("username")
        detail = f"bot @{username} reachable" if isinstance(username, str) else "delivered"
        return (
            NotifyResult(
                ok=True,
                stage="api",
                detail=_bounded(detail, secrets),
                status=status,
                message_id=message_id if isinstance(message_id, int) else None,
            ),
            False,
        )
    detail = _bounded(_failure_detail(status, parsed, raw), secrets)
    retryable = status >= 500 or status == 429
    return NotifyResult(ok=False, stage="api", detail=detail, status=status), retryable


def _default_transport(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        # An HTTP status is an answer, not a transport failure. Read it here
        # so no URL-bearing exception ever propagates (the URL carries the
        # token; §0 iron rule 5).
        try:
            raw = err.read() or b""
        except OSError:
            raw = b""
        finally:
            err.close()
        return err.code, raw


def _parse_body(raw: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _failure_detail(status: int, parsed: dict[str, object], raw: bytes) -> str:
    description = parsed.get("description")
    if isinstance(description, str) and description:
        return f"HTTP {status}: {description}"
    excerpt = raw.decode("utf-8", errors="replace").strip()
    return f"HTTP {status}: {excerpt}" if excerpt else f"HTTP {status}"


def _reason_text(err: OSError) -> str:
    reason = getattr(err, "reason", None)  # URLError wraps its cause here
    text = str(reason) if reason is not None else str(err)
    return f"transport failure: {text}" if text else "transport failure"


def _bounded(text: str, secrets: tuple[str, ...], limit: int = DETAIL_LIMIT) -> str:
    """Scrub BEFORE truncating: truncating first could split a secret so the
    scrub no longer matches the remainder."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, _REDACTED)
    return text[:limit]
