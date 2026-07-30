"""Preflight credential validation and auth-failure surfacing (§17, §0.3).

Regression cover for the 2026-07-30 lifecycle attempt, where the environment
held the literal placeholder `<practice token>` and the run reported "no
practice accounts on this token" — a 401 that had been preserved as an
ordinary body and then read as a valid-but-empty account list.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from trading_firm.execution.adapter import BrokerAuthError, TransportFailureError
from trading_firm.execution.credentials import (
    ACCOUNT_VAR,
    TOKEN_VAR,
    CredentialError,
    configured_account_id,
    practice_token,
)
from trading_firm.execution.oanda_transport import OandaPracticeTransport


@pytest.fixture(autouse=True)
def _hermetic_credentials(monkeypatch):
    """Clear both variables before every test. The session environment may
    legitimately carry either one, and these tests must assert on what they
    set, not on the host's configuration."""
    monkeypatch.delenv(TOKEN_VAR, raising=False)
    monkeypatch.delenv(ACCOUNT_VAR, raising=False)


def _http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api-fxpractice.oanda.com/v3/accounts",
        code=code,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(body.encode()),
    )


# --------------------------------------------------------------- preflight


def test_missing_token_is_refused_by_name(monkeypatch):
    monkeypatch.delenv(TOKEN_VAR, raising=False)
    with pytest.raises(CredentialError, match=TOKEN_VAR):
        practice_token()


@pytest.mark.parametrize(
    "placeholder",
    [
        "<practice token>",  # the exact value that broke the 2026-07-30 run
        "<practice-token>",
        "<token>",
        "[token]",
        "CHANGEME",
        "your-token-here",
    ],
)
def test_placeholder_token_is_named_as_a_placeholder(monkeypatch, placeholder):
    monkeypatch.setenv(TOKEN_VAR, placeholder)
    with pytest.raises(CredentialError, match="placeholder"):
        practice_token()


def test_placeholder_account_id_is_refused(monkeypatch):
    """`<id>` must never reach the wire as /v3/accounts/<id>/summary."""
    monkeypatch.setenv(ACCOUNT_VAR, "<id>")
    with pytest.raises(CredentialError, match="placeholder"):
        configured_account_id()


def test_whitespace_token_is_refused(monkeypatch):
    monkeypatch.setenv(TOKEN_VAR, "abc def")
    with pytest.raises(CredentialError, match="whitespace"):
        practice_token()


def test_plausible_token_passes_preflight_untouched(monkeypatch):
    """Preflight rules out only what is locally impossible; judging validity
    is the broker's job, so a well-formed token must survive."""
    token = f"{'a' * 32}-{'b' * 32}"
    monkeypatch.setenv(TOKEN_VAR, f"  {token}\n")
    assert practice_token() == token


def test_unset_account_id_means_not_pinned(monkeypatch):
    monkeypatch.delenv(ACCOUNT_VAR, raising=False)
    assert configured_account_id() is None


def test_credential_error_never_echoes_the_value(monkeypatch):
    secret = "<super-secret-placeholder>"
    monkeypatch.setenv(TOKEN_VAR, secret)
    with pytest.raises(CredentialError) as caught:
        practice_token()
    assert secret not in str(caught.value)


def test_transport_refuses_placeholder_before_any_network_io(monkeypatch):
    monkeypatch.setenv(TOKEN_VAR, "<practice token>")

    def explode(*args, **kwargs):  # pragma: no cover — must never be reached
        raise AssertionError("network I/O attempted on a placeholder credential")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    with pytest.raises(CredentialError, match="placeholder"):
        OandaPracticeTransport()


# ------------------------------------------------------- auth vs. rejection


@pytest.mark.parametrize("code", [401, 403])
def test_auth_failure_raises_instead_of_reporting_no_accounts(monkeypatch, code):
    """The exact 2026-07-30 misdiagnosis: a rejected credential must not
    degrade into an empty account list."""
    monkeypatch.setenv(TOKEN_VAR, f"{'a' * 32}-{'b' * 32}")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(
            _http_error(code, json.dumps({"errorMessage": "Insufficient authorization"}))
        ),
    )

    with pytest.raises(BrokerAuthError) as caught:
        OandaPracticeTransport()

    message = str(caught.value)
    assert "no practice accounts" not in message
    assert str(code) in message and "Insufficient authorization" in message


def test_auth_error_routes_through_existing_fail_closed_handlers():
    """Subclassing keeps every `except TransportFailureError` handler in the
    §2 order path intact, so UNKNOWN resolution still applies."""
    assert issubclass(BrokerAuthError, TransportFailureError)


def test_order_rejection_body_is_still_preserved(monkeypatch):
    """Finding 5 must survive: a non-auth 4xx carrying a rejection reaches the
    adapter as a rejection, not as an exception."""
    monkeypatch.setenv(TOKEN_VAR, f"{'a' * 32}-{'b' * 32}")
    transport = OandaPracticeTransport(account_id="001-001-1234567-001")

    body = {"orderRejectTransaction": {"reason": "INSUFFICIENT_MARGIN"}}
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(_http_error(400, json.dumps(body))),
    )

    response = transport.create_market_order(
        instrument="EUR_USD", units=1, stop_loss_price="1.0", client_order_id="x"
    )
    assert response["orderRejectTransaction"]["reason"] == "INSUFFICIENT_MARGIN"


def test_unparseable_auth_body_still_raises_auth_error(monkeypatch):
    monkeypatch.setenv(TOKEN_VAR, f"{'a' * 32}-{'b' * 32}")
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(_http_error(401, "<html>gateway</html>")),
    )
    with pytest.raises(BrokerAuthError, match="unparseable body"):
        OandaPracticeTransport()


# ------------------------------------------------------------ account pin


def test_pinned_account_is_honored_over_first_account(monkeypatch):
    """A token holding several practice accounts must target the pinned one,
    not whichever OANDA lists first."""
    monkeypatch.setenv(TOKEN_VAR, f"{'a' * 32}-{'b' * 32}")
    monkeypatch.setenv(ACCOUNT_VAR, "001-001-7654321-002")

    def explode(*args, **kwargs):  # pragma: no cover — must never be reached
        raise AssertionError("looked up accounts despite an explicit pin")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    assert OandaPracticeTransport()._account_id == "001-001-7654321-002"


def test_explicit_argument_outranks_the_env_pin(monkeypatch):
    monkeypatch.setenv(TOKEN_VAR, f"{'a' * 32}-{'b' * 32}")
    monkeypatch.setenv(ACCOUNT_VAR, "001-001-7654321-002")
    transport = OandaPracticeTransport(account_id="001-001-1111111-003")
    assert transport._account_id == "001-001-1111111-003"
