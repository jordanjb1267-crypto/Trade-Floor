#!/usr/bin/env python3
"""End-to-end verification of the §18 Telegram notification path.

Sends ONE real, clearly labelled message through api.telegram.org using the
same module the firm's runtime will use (`trading_firm.notify.telegram`) —
the point is to prove the deployed code path, not a mock. It contacts no
broker and carries no order capability (§0 iron rule 1).

Usage:
    TELEGRAM_BOT_TOKEN=<token> TELEGRAM_CHAT_ID=<id> \
        python3 scripts/verify_telegram_notify.py

Output redacts the chat id and never prints the token (§17). Exit codes:
0 = all checks passed; 1 = a check failed; 2 = preflight refused (nothing
was sent — fail closed, §0 iron rule 3).
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_firm.env_file import load_env_file  # noqa: E402
from trading_firm.execution.credentials import CredentialError  # noqa: E402
from trading_firm.notify import telegram  # noqa: E402


def main() -> int:
    # Load an untracked .env first (§17; exported vars still win), THEN
    # preflight — same order as verify_oanda_demo.py, and for the same
    # reason: a placeholder should be reported as a placeholder, not as a
    # 401 that reads like a bad token.
    load_env_file()
    try:
        _, chat_id = telegram.preflight()
    except CredentialError as err:
        print(f"FAIL: {err}")
        return 2

    print(f"Credentials present: {telegram.BOT_TOKEN_VAR}, {telegram.CHAT_ID_VAR} ")
    print(f"(values never printed; §17). Target chat: {telegram.redact_chat_id(chat_id)}\n")

    checks: list[tuple[str, bool, str]] = []

    identity = telegram.get_me()
    checks.append(
        (
            "getMe: token resolves to a live bot",
            identity.ok,
            f"{identity.detail} (status={identity.status} attempts={identity.attempts})",
        )
    )

    if identity.ok:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        message = (
            f"Trade-Floor notification-path verification — {stamp}.\n"
            "Deterministic notify module, end-to-end check from the Claude Code "
            "remote environment. Research phase; no live trading; this is not "
            "a trade signal."
        )
        delivery = telegram.send(message)
        checks.append(
            (
                "sendMessage: real message delivered to owner chat",
                delivery.ok and delivery.message_id is not None,
                f"message_id={delivery.message_id} status={delivery.status} "
                f"attempts={delivery.attempts} chat={telegram.redact_chat_id(chat_id)}",
            )
        )
    else:
        checks.append(
            (
                "sendMessage: real message delivered to owner chat",
                False,
                "NOT RUN — identity check failed first",
            )
        )

    print(f"{'RESULT':<6} CHECK")
    failures = 0
    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL':<6} {label}\n       {detail}")
        failures += 0 if ok else 1

    verdict = (
        "Notification path verified end-to-end."
        if failures == 0
        else "Resolve failures before relying on this path (§18)."
    )
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed. {verdict}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
