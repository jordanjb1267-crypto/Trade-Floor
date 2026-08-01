#!/usr/bin/env python3
"""Preflight and end-to-end verification of the §19 notification path.

Run on the trading laptop once `.env` carries a real bot token and chat id.
Four stages, strictly ordered so nothing leaves the machine until local
checks pass (§0.10):

1. configuration — shared §17 credential preflight plus Telegram shape checks
   (a bot's @username configured as the chat id is the observed failure mode:
   well-formed, passes generic checks, can never receive a message);
2. the remote-control surface — re-asserted on the machine that will actually
   hold the token: halt-only, no approval command, kill switch parses;
3. getMe — the token resolves to a live bot, nothing sent;
4. one real sendMessage to the owner chat.

Failures are mapped to remedies by `surface.remedy_for`: an unreachable host is
named as a NETWORK result so nobody rotates a good credential over an egress
denial, a 401 names the token, a 400/403 names the destination.

Usage:
    python3 scripts/verify_telegram.py            # all four stages
    python3 scripts/verify_telegram.py --dry-run  # stages 1-2 only, nothing sent

Exit codes: 0 all checks pass, 1 a check failed, 2 not configured.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_firm.env_file import load_env_file  # noqa: E402
from trading_firm.execution.credentials import CredentialError  # noqa: E402
from trading_firm.notify import telegram  # noqa: E402
from trading_firm.notify.surface import (  # noqa: E402
    NotificationKind,
    OwnerCommand,
    notify_owner,
    parse_owner_command,
    redact,
    remedy_for,
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
        telegram.preflight()
    except CredentialError as error:
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

    # --- 3-4. the wire ---------------------------------------------------------
    if dry_run:
        print("\n  [SKIP] getMe / delivery — --dry-run")
    else:
        me = telegram.get_me()
        results.append(
            report(PASS if me.ok else FAIL, "getMe: token resolves to a live bot",
                   me.detail if me.ok else remedy_for(me))
        )
        if me.ok:
            sent = notify_owner(
                NotificationKind.SESSION_START_HEALTH,
                "Preflight from verify_telegram.py. If you can read this, the §19 "
                "notification path works end to end on this machine.",
            )
            results.append(
                report(
                    PASS if sent.ok else FAIL,
                    "test message delivered",
                    f"message_id={sent.message_id} status={sent.status} "
                    f"attempts={sent.attempts}"
                    if sent.ok
                    else remedy_for(sent),
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
