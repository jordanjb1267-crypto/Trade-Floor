#!/usr/bin/env python3
"""Preflight for the §19 notification and remote-control path.

Run this on the trading laptop once `.env` carries a real bot token and chat id.
It validates configuration locally first, then sends one test message, so a
misconfiguration is named before any network call rather than surfacing as a
silent non-delivery during a live session (§0.10, fail closed).

Nothing here prints, logs, or returns a credential. Telegram puts the bot token
in the URL path, so every message this script emits passes through `redact()`
(§17, §0.2).

Usage:
    python3 scripts/verify_telegram.py            # validate config, send a test message
    python3 scripts/verify_telegram.py --dry-run  # validate config only, send nothing

Reads from the environment or an untracked `.env`:
    TELEGRAM_BOT_TOKEN   from BotFather
    TELEGRAM_CHAT_ID     message the bot, then read message.chat.id from /getUpdates

Exit codes: 0 all checks pass, 1 a check failed, 2 not configured.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_firm.env_file import load_env_file  # noqa: E402
from trading_firm.notifications import (  # noqa: E402
    NotificationKind,
    OwnerCommand,
    TelegramConfigError,
    TelegramNotifier,
    parse_owner_command,
    redact,
)

PASS = "PASS"
FAIL = "FAIL"


def report(status: str, label: str, detail: str = "") -> bool:
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {redact(detail)}"
    print(line)
    return status == PASS


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    load_env_file()

    print("§19 notification path preflight\n")
    results: list[bool] = []

    # --- 1. configuration, before any network I/O ----------------------------
    try:
        notifier = TelegramNotifier()
    except TelegramConfigError as error:
        report(FAIL, "configuration", str(error))
        print(
            "\nNot configured. Add both values to the untracked .env on this machine:\n"
            "  TELEGRAM_BOT_TOKEN=...   (BotFather)\n"
            "  TELEGRAM_CHAT_ID=...     (message the bot, then /getUpdates)\n"
            "A bot token alone has no destination; the chat id is required too."
        )
        return 2
    results.append(report(PASS, "configuration", "token and chat id present and well-formed"))

    # --- 2. the control surface cannot grant ---------------------------------
    # Re-asserted here rather than trusted, because this is the check an operator
    # runs on the machine that will actually hold the token.
    permissive = [
        member.name
        for member in OwnerCommand
        if any(
            word in member.name.lower()
            for word in ("enable", "approve", "allow", "unfreeze", "resume", "activate")
        )
    ]
    results.append(
        report(
            PASS if not permissive else FAIL,
            "remote controls are halt-only",
            "no command can enable, approve, or raise anything"
            if not permissive
            else f"permissive commands present: {permissive}",
        )
    )

    results.append(
        report(
            PASS if parse_owner_command("/approve_trade yes") is None else FAIL,
            "an approval command is not accepted",
            "live-trade approval over chat is deliberately not built (Phase 7 decision)",
        )
    )
    results.append(
        report(
            PASS if parse_owner_command("/kill") is not None else FAIL,
            "the kill switch parses",
            "§25 mobile path for the kill switch",
        )
    )

    # --- 3. delivery ----------------------------------------------------------
    if dry_run:
        print("\n  [SKIP] delivery — --dry-run")
    else:
        delivered = notifier.send(
            NotificationKind.SESSION_START_HEALTH,
            "Preflight from verify_telegram.py. If you can read this, the §19 "
            "notification path works. Reply /status to check the command surface.",
        )
        results.append(
            report(
                PASS if delivered else FAIL,
                "test message delivered",
                "check the chat"
                if delivered
                else "send failed — verify the token is current and the chat id is "
                "the numeric id of a chat the bot can post to",
            )
        )

    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        return 1
    print(
        "\nNote: this proves the path works. It does not enable anything — the "
        "firm is not live and live_allowed is empty (§12.5, §24)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
