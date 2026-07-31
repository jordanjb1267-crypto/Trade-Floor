"""Telegram notify path (§18): fail closed locally, leak nothing, never raise.

Credential-shaped values are BUILT AT RUNTIME here, never written as static
literals — the pre-write hook scans for credential patterns (decision log,
2026-07-29). No test opens a socket: every transport is injected, and the
fail-closed tests use a transport that fails the test if it is ever called.
"""

import json
import urllib.error

import pytest

from trading_firm.execution.credentials import CredentialError
from trading_firm.notify import telegram


def fake_token(seed: str = "1") -> str:
    """Bot-token shape built at runtime: digits, ':', 35 URL-safe chars."""
    return (seed * 10)[:10] + ":" + ("Ab8_" * 9)[:35]


def fake_chat_id() -> str:
    return "-100" + "9" * 9


def ok_body(**result: object) -> bytes:
    return json.dumps({"ok": True, "result": result}).encode()


def error_body(description: str) -> bytes:
    return json.dumps({"ok": False, "description": description}).encode()


class RecordingTransport:
    """Replays scripted (status, body) responses or raises scripted exceptions."""

    def __init__(self, *responses: object):
        self.responses = list(responses)
        self.calls: list[tuple[str, bytes, float]] = []

    def __call__(self, url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
        self.calls.append((url, body, timeout))
        action = self.responses.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action  # type: ignore[return-value]


def refuse_network(url: str, body: bytes, timeout: float) -> tuple[int, bytes]:
    raise AssertionError("preflight must refuse before any network I/O")


@pytest.fixture()
def creds(monkeypatch) -> tuple[str, str]:
    token, chat = fake_token(), fake_chat_id()
    monkeypatch.setenv(telegram.BOT_TOKEN_VAR, token)
    monkeypatch.setenv(telegram.CHAT_ID_VAR, chat)
    return token, chat


@pytest.fixture()
def sleeps() -> list[float]:
    return []


# --- preflight: fail closed before any I/O (§0 iron rule 3) -----------------


def test_missing_token_fails_closed_without_network(monkeypatch):
    monkeypatch.delenv(telegram.BOT_TOKEN_VAR, raising=False)
    monkeypatch.setenv(telegram.CHAT_ID_VAR, fake_chat_id())
    result = telegram.send("hello", transport=refuse_network)
    assert not result.ok
    assert result.stage == "preflight"
    assert telegram.BOT_TOKEN_VAR in result.detail
    assert result.attempts == 0


def test_placeholder_chat_id_refused(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN_VAR, fake_token())
    monkeypatch.setenv(telegram.CHAT_ID_VAR, "<chat id>")
    result = telegram.send("hello", transport=refuse_network)
    assert not result.ok
    assert result.stage == "preflight"
    assert "placeholder" in result.detail


def test_token_without_colon_refused_and_not_echoed(monkeypatch):
    bad = "0" * 46  # token-length but structurally impossible: no ':'
    monkeypatch.setenv(telegram.BOT_TOKEN_VAR, bad)
    monkeypatch.setenv(telegram.CHAT_ID_VAR, fake_chat_id())
    result = telegram.send("hello", transport=refuse_network)
    assert not result.ok
    assert result.stage == "preflight"
    assert "bot token" in result.detail
    assert bad not in result.detail


def test_empty_text_refused_before_credentials_are_read(monkeypatch):
    monkeypatch.delenv(telegram.BOT_TOKEN_VAR, raising=False)
    monkeypatch.delenv(telegram.CHAT_ID_VAR, raising=False)
    result = telegram.send("   ", transport=refuse_network)
    assert not result.ok
    assert result.stage == "preflight"
    assert "empty message" in result.detail


def test_preflight_returns_both_values(creds):
    assert telegram.preflight() == creds


def test_preflight_raises_credential_error_naming_the_variable(monkeypatch):
    monkeypatch.setenv(telegram.BOT_TOKEN_VAR, fake_token())
    monkeypatch.delenv(telegram.CHAT_ID_VAR, raising=False)
    with pytest.raises(CredentialError, match=telegram.CHAT_ID_VAR):
        telegram.preflight()


# --- the happy path ---------------------------------------------------------


def test_send_success_builds_expected_request(creds):
    token, chat = creds
    transport = RecordingTransport((200, ok_body(message_id=7)))
    result = telegram.send("hello owner", transport=transport)

    assert result.ok and result.stage == "api"
    assert result.status == 200 and result.message_id == 7 and result.attempts == 1

    url, body, timeout = transport.calls[0]
    assert url == f"https://{telegram.API_HOST}/bot{token}/sendMessage"
    assert json.loads(body) == {"chat_id": chat, "text": "hello owner"}
    assert timeout == telegram.TIMEOUT_SECONDS


def test_get_me_reports_bot_identity(creds):
    transport = RecordingTransport((200, ok_body(id=1, username="tf_bot")))
    result = telegram.get_me(transport=transport)
    assert result.ok
    assert "@tf_bot" in result.detail
    assert transport.calls[0][0].endswith("/getMe")


def test_long_text_truncated_to_telegram_limit(creds):
    transport = RecordingTransport((200, ok_body(message_id=1)))
    telegram.send("x" * 5000, transport=transport)
    sent = json.loads(transport.calls[0][1])["text"]
    assert len(sent) == telegram.MAX_TEXT_CHARS
    assert sent.endswith("\N{HORIZONTAL ELLIPSIS}")


# --- retry policy: deterministic and bounded --------------------------------


def test_server_error_retried_once_with_fixed_delay(creds, sleeps):
    transport = RecordingTransport((500, b"{}"), (200, ok_body(message_id=2)))
    result = telegram.send("hello", transport=transport, sleep=sleeps.append)
    assert result.ok and result.attempts == 2
    assert sleeps == [telegram.RETRY_DELAY_SECONDS]


def test_rate_limit_429_retried_then_reported(creds, sleeps):
    transport = RecordingTransport(
        (429, error_body("Too Many Requests: retry later")),
        (429, error_body("Too Many Requests: retry later")),
    )
    result = telegram.send("hello", transport=transport, sleep=sleeps.append)
    assert not result.ok
    assert result.status == 429 and result.attempts == 2
    assert len(sleeps) == 1


def test_client_error_not_retried(creds, sleeps):
    transport = RecordingTransport((400, error_body("Bad Request: chat not found")))
    result = telegram.send("hello", transport=transport, sleep=sleeps.append)
    assert not result.ok
    assert result.status == 400 and result.attempts == 1
    assert "chat not found" in result.detail
    assert sleeps == []


def test_ok_false_on_http_200_is_failure_without_retry(creds, sleeps):
    transport = RecordingTransport((200, error_body("something declined")))
    result = telegram.send("hello", transport=transport, sleep=sleeps.append)
    assert not result.ok and result.attempts == 1
    assert "something declined" in result.detail
    assert sleeps == []


def test_network_error_then_success(creds, sleeps):
    transport = RecordingTransport(
        urllib.error.URLError(TimeoutError("timed out")),
        (200, ok_body(message_id=3)),
    )
    result = telegram.send("hello", transport=transport, sleep=sleeps.append)
    assert result.ok and result.attempts == 2


# --- secrecy: nothing that leaves this module may carry a secret (§17) ------


def test_url_bearing_exception_never_leaks_token(creds, sleeps):
    """HTTPError carries the full request URL — token included — in .filename.
    The detail that comes back must not contain either secret."""
    token, chat = creds
    poisoned_url = f"https://{telegram.API_HOST}/bot{token}/sendMessage"
    transport = RecordingTransport(
        urllib.error.HTTPError(poisoned_url, 404, "Not Found", None, None),
        urllib.error.HTTPError(poisoned_url, 404, "Not Found", None, None),
    )
    result = telegram.send("hello", transport=transport, sleep=sleeps.append)
    assert not result.ok
    assert token not in result.detail
    assert chat not in result.detail


def test_api_description_echoing_chat_id_is_scrubbed(creds):
    token, chat = creds
    transport = RecordingTransport((400, error_body(f"Bad Request: chat {chat} rejected")))
    result = telegram.send("hello", transport=transport)
    assert chat not in result.detail
    assert "[redacted]" in result.detail
    assert token not in result.detail


def test_unexpected_transport_exception_contained_and_scrubbed(creds):
    token, _ = creds
    transport = RecordingTransport(ValueError(f"boom {token} boom"))
    result = telegram.send("hello", transport=transport)  # must not raise
    assert not result.ok
    assert "unexpected ValueError" in result.detail
    assert token not in result.detail
    assert result.attempts == 1


def test_redact_chat_id_shapes():
    assert telegram.redact_chat_id("-1009999999999") == "-1\N{HORIZONTAL ELLIPSIS}99"
    assert telegram.redact_chat_id("1234567") == "12\N{HORIZONTAL ELLIPSIS}67"
    assert telegram.redact_chat_id("123456") == "\N{HORIZONTAL ELLIPSIS}"
    assert telegram.redact_chat_id("") == "\N{HORIZONTAL ELLIPSIS}"
