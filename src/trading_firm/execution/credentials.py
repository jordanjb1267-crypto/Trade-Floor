"""Practice-credential resolution and preflight validation (§17).

The 2026-07-30 lifecycle attempt is why this module exists. The environment
carried the literal placeholder `<practice token>` — copied verbatim from a
usage docstring — and the run failed with "no practice accounts on this
token". That message was wrong in a way that sends an operator to the OANDA
site to create an account they already have: the real cause was a 401 whose
body had been preserved as an ordinary response and then read as "valid, but
empty".

A credential that cannot possibly be real is therefore named as such here,
before any network I/O (§0 iron rule 3, fail closed). Anything this module
cannot rule out locally is left to the broker, which answers definitively.

Values are never logged, echoed, or embedded in an error; failures report the
variable name and the reason only (§0 iron rule 5).
"""

from __future__ import annotations

import os
import re

TOKEN_VAR = "OANDA_DEMO_API_TOKEN"
ACCOUNT_VAR = "OANDA_DEMO_ACCOUNT_ID"

# `<practice token>`, `<id>`, `[token]` — placeholder notation lifted straight
# from .env.example or a usage line. No real credential is bracket-wrapped.
_WRAPPED = re.compile(r"^[<\[].*[>\]]$")
_PLACEHOLDER_WORDS = frozenset(
    {"changeme", "change-me", "todo", "tbd", "xxx", "none", "null", "your-token-here"}
)


class CredentialError(RuntimeError):
    """A credential is absent or cannot possibly be valid.

    Raised before any request is sent, so a local misconfiguration is never
    mistaken for an answer from the broker.
    """


def validate_credential(name: str, raw: str | None) -> str:
    """Reject an absent, placeholder, or whitespace-bearing credential (§17).

    Shared preflight: the OANDA getters below and the Telegram notify path
    (`trading_firm.notify.telegram`) validate on identical terms, so the
    placeholder vocabulary cannot drift between them. Errors name the
    variable and the reason; the value itself is never echoed.
    """
    if raw is None or not raw.strip():
        raise CredentialError(f"{name} not set (see .env.example; §17)")

    value = raw.strip()

    if _WRAPPED.match(value) or value.lower() in _PLACEHOLDER_WORDS:
        raise CredentialError(
            f"{name} holds the literal placeholder from .env.example, not a real "
            f"credential — substitute the practice value (§17). Nothing was sent."
        )
    if any(char.isspace() for char in value):
        raise CredentialError(
            f"{name} contains whitespace, so it cannot be a valid credential (§17). "
            f"Nothing was sent."
        )
    return value


def practice_token() -> str:
    """The fxTrade Practice token, or raise CredentialError. Never logged."""
    return validate_credential(TOKEN_VAR, os.environ.get(TOKEN_VAR))


def configured_account_id() -> str | None:
    """The operator-pinned practice account, or None to use the first account
    on the token — the contract both scripts already document.

    Validated on the same terms as the token: an unset variable is a normal
    "not pinned", but a placeholder is a misconfiguration and must not reach a
    request path as `/v3/accounts/<id>/summary`.
    """
    raw = os.environ.get(ACCOUNT_VAR)
    if raw is None or not raw.strip():
        return None
    return validate_credential(ACCOUNT_VAR, raw)
