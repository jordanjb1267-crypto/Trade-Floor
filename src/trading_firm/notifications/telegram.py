"""Telegram notification and remote-control path (§19, §18, §17).

§18 asks for "local notifications plus optional Telegram/Discord notification
path" and §25's definition of done requires the owner to reach the kill switch
"from laptop and approved mobile path". This is that mobile path.

Two design decisions here are load-bearing and were not obvious.

**The inbound command surface is halt-only, by type.**

§19 lists seven owner controls, and they divide into two very different classes.
Restrictive controls — kill, halt, disable an instrument, disable a strategy,
freeze scaling, freeze promotion — can only ever *reduce* what the firm may do.
Permissive controls — "global live enable", "approve trade during probation" —
grant. A bot token is a bearer credential sitting on a phone and travelling
through a third party's servers; whoever holds it can send whatever the surface
accepts. If the surface accepts approvals, a compromised token approves trades.

So `OwnerCommand` contains no permissive member and a module-level check asserts
it never gains one. An attacker holding the token can halt this firm, which is
the same thing the owner can do and is a fail-closed direction (§0.10). They
cannot start it, size it, or approve anything.

Live-trade approval over Telegram is therefore **deliberately not built**. §13
requires human approval for every live trade during probation, but it does not
require that approval to arrive over a messaging app, and Phase 6 is shadow and
paper where there is nothing live to approve. Building the approval path is a
Phase 7 decision that needs its own threat model — reaching for it here because
the enum was already open would be exactly the wrong way to acquire it.

**The bot token lives in the URL path.**

Telegram's API is `https://api.telegram.org/bot<TOKEN>/sendMessage`. That is a
credential inside a URL, which is the single most log-prone place a secret can
sit: request loggers, retry wrappers, and — worst — exception messages, which
routinely carry the failing URL and then get written to an audit trail that §0
rule 11 makes immutable. `redact()` exists for that, every error raised here
passes through it, and a test asserts a token never survives into an exception.
"""

from __future__ import annotations

import enum
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

TOKEN_VAR = "TELEGRAM_BOT_TOKEN"
CHAT_VAR = "TELEGRAM_CHAT_ID"

API_ROOT = "https://api.telegram.org"
DEFAULT_TIMEOUT_SECONDS = 10

# Telegram tokens are `<digits>:<35-ish base64url chars>`. Matched loosely on
# purpose: redaction should over-match rather than let one through.
_TOKEN_PATTERN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_WRAPPED = re.compile(r"^[<\[].*[>\]]$")
_PLACEHOLDER_WORDS = frozenset(
    {"changeme", "change-me", "todo", "tbd", "xxx", "none", "null", "your-token-here"}
)


class TelegramConfigError(RuntimeError):
    """The notification path is not configured, or cannot possibly be valid."""


def redact(text: str) -> str:
    """Remove anything token-shaped from text bound for a log or an exception.

    Applied to every message this module raises or returns. A token in an
    exception string reaches the audit trail, and §0 rule 11 makes that record
    immutable — there is no cleaning it up afterwards.
    """
    text = _TOKEN_PATTERN.sub("<redacted-token>", text)
    # Belt and braces: the URL form, in case a token shape drifts.
    return re.sub(r"/bot[^/\s]+/", "/bot<redacted-token>/", text)


class NotificationKind(enum.StrEnum):
    """The §19 minimum set. Named so a report cannot be sent untyped."""

    SESSION_START_HEALTH = "session_start_health"
    CANDIDATE_APPROVAL_REQUEST = "candidate_approval_request"
    ORDER_SUBMITTED = "order_submitted"
    FILL_CONFIRMATION = "fill_confirmation"
    STOP_CONFIRMATION = "stop_confirmation"
    POSITION_CLOSED = "position_closed"
    RISK_HALT = "risk_halt"
    DATA_OR_BROKER_FAILURE = "data_or_broker_failure"
    TIER_CHANGE = "tier_change"
    DAILY_SESSION_REPORT = "daily_session_report"
    WEEKLY_PERFORMANCE_REPORT = "weekly_performance_report"

    @property
    def is_alert(self) -> bool:
        """Alerts must reach the owner even if routine reports are suppressed."""
        return self in (
            NotificationKind.RISK_HALT,
            NotificationKind.DATA_OR_BROKER_FAILURE,
            NotificationKind.TIER_CHANGE,
        )


class OwnerCommand(enum.StrEnum):
    """Remote controls the owner may send (§19).

    Every member is RESTRICTIVE: it can only reduce what the firm may do. There
    is deliberately no `ENABLE_LIVE`, no `APPROVE_TRADE`, and no `UNFREEZE` —
    see the module docstring. `_no_permissive_commands()` runs at import and
    fails the process if one is ever added.
    """

    KILL = "kill"  # §19 kill switch: stop everything, flatten per §14
    HALT = "halt"  # no new entries; manage existing positions only
    DISABLE_INSTRUMENT = "disable_instrument"
    DISABLE_STRATEGY = "disable_strategy"
    FREEZE_SCALING = "freeze_scaling"
    FREEZE_PROMOTION = "freeze_promotion"
    STATUS = "status"  # read-only

    @property
    def is_restrictive(self) -> bool:
        return self is not OwnerCommand.STATUS

    @property
    def requires_argument(self) -> bool:
        return self in (OwnerCommand.DISABLE_INSTRUMENT, OwnerCommand.DISABLE_STRATEGY)


# Words that would indicate a permissive command had been added. A denylist
# cannot catch a creatively-named one, so the registered-set check below is the
# real guard; this exists to give a precise error for the obvious case.
_PERMISSIVE_HINTS = frozenset(
    {"enable", "approve", "allow", "unfreeze", "resume", "start", "activate", "promote", "raise"}
)

# The exact command set this module is registered to expose. Any addition trips
# the import-time check until someone deliberately registers it and states that
# it cannot grant. Same reasoning as REGISTERED_QUERY_FIELDS in research/analogs.
REGISTERED_COMMANDS = frozenset(
    {
        "KILL",
        "HALT",
        "DISABLE_INSTRUMENT",
        "DISABLE_STRATEGY",
        "FREEZE_SCALING",
        "FREEZE_PROMOTION",
        "STATUS",
    }
)


def _no_permissive_commands() -> None:
    """Fail at import if the remote surface ever gains a granting command."""
    named = {member.name for member in OwnerCommand}

    hinted = sorted(
        name
        for name in named
        if any(hint in name.lower() for hint in _PERMISSIVE_HINTS)
    )
    if hinted:
        raise RuntimeError(
            f"OwnerCommand declares {hinted}: the remote control surface is halt-only. "
            f"A bot token is a bearer credential on a phone; a surface that can grant "
            f"is a surface an attacker can grant with (§19, §0.10)."
        )

    added = named - REGISTERED_COMMANDS
    removed = REGISTERED_COMMANDS - named
    if added or removed:
        raise RuntimeError(
            f"OwnerCommand changed (added={sorted(added)}, removed={sorted(removed)}). "
            f"Every remote command is registered explicitly so that adding one is a "
            f"deliberate act. If the new command genuinely cannot grant, enable, "
            f"approve, or raise anything, add it to REGISTERED_COMMANDS and say so in "
            f"the commit."
        )


_no_permissive_commands()


@dataclass(frozen=True)
class ParsedCommand:
    command: OwnerCommand
    argument: str | None = None


def parse_owner_command(text: str) -> ParsedCommand | None:
    """Parse an inbound message, or None if it is not a recognised command.

    Unrecognised input returns None rather than raising: an owner mistyping into
    a chat window should get "not a command", and an attacker probing the
    surface should learn nothing from the difference.
    """
    if not text or not text.strip():
        return None
    parts = text.strip().lstrip("/").split()
    if not parts:
        return None
    try:
        command = OwnerCommand(parts[0].lower())
    except ValueError:
        return None
    argument = parts[1] if len(parts) > 1 else None
    if command.requires_argument and not argument:
        return None
    return ParsedCommand(command=command, argument=argument)


# A chat id is an integer — negative for groups and supergroups — or an
# `@channelusername` for a public channel. Nothing else can receive a message.
_CHAT_ID = re.compile(r"^(-?\d+|@[A-Za-z][A-Za-z0-9_]{4,})$")
_TOKEN_SHAPE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


def _validate(name: str, raw: str | None) -> str:
    if raw is None or not raw.strip():
        raise TelegramConfigError(f"{name} not set (see .env.example; §17)")
    value = raw.strip()
    if _WRAPPED.match(value) or value.lower() in _PLACEHOLDER_WORDS:
        raise TelegramConfigError(
            f"{name} holds a placeholder, not a real value — substitute the real one "
            f"(§17). Nothing was sent."
        )
    if any(char.isspace() for char in value):
        raise TelegramConfigError(
            f"{name} contains whitespace, so it cannot be valid (§17). Nothing was sent."
        )
    return value


def _validate_token(name: str, raw: str | None) -> str:
    value = _validate(name, raw)
    if not _TOKEN_SHAPE.match(value):
        raise TelegramConfigError(
            f"{name} is not shaped like a Telegram bot token (`<digits>:<secret>` from "
            f"BotFather). Nothing was sent, and the value is not echoed here (§17)."
        )
    return value


def _validate_chat_id(name: str, raw: str | None) -> str:
    """Reject a well-formed value of the wrong KIND.

    The generic check — non-empty, no whitespace, not a placeholder — passes a
    bot's @username, which is exactly what was configured on the first real
    attempt at this path. It is a perfectly valid string and it can never
    receive a message; Telegram answers "chat not found" at send time, which
    surfaces as a silent non-delivery during a session rather than as a
    configuration error before one.

    A validator that accepts an unusable value is the failure this codebase
    keeps finding: it passes, so nobody looks again.
    """
    value = _validate(name, raw)
    if not _CHAT_ID.match(value):
        raise TelegramConfigError(
            f"{name} must be the NUMERIC chat id (negative for a group), or "
            f"@channelusername for a public channel. A bot's username is not a chat "
            f"id and cannot receive messages. Message the bot, then read "
            f"message.chat.id from /getUpdates (§19). Nothing was sent."
        )
    return value


class TelegramNotifier:
    """Outbound §19 notifications. Holds the token; never surfaces it.

    Construction resolves credentials from the environment (§17) — a token is
    never passed as a literal, so it cannot arrive from a config file, a prompt,
    or a commit.
    """

    def __init__(self, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._token = _validate_token(TOKEN_VAR, os.environ.get(TOKEN_VAR))
        self._chat_id = _validate_chat_id(CHAT_VAR, os.environ.get(CHAT_VAR))
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        # The default dataclass/object repr would print _token in any traceback
        # that renders locals.
        return f"TelegramNotifier(chat_id=<set>, token=<redacted>, timeout={self._timeout}s)"

    def _url(self, method: str) -> str:
        return f"{API_ROOT}/bot{self._token}/{method}"

    def send(self, kind: NotificationKind, body: str) -> bool:
        """Send one notification. Returns success; never raises on transport.

        A failed notification must not stop the session — §0.10 fails closed on
        *trading* inputs, and a chat outage is not one. The failure is returned
        so the caller can record it, and an alert that could not be delivered is
        the operator's problem to see in the local log, which is why §18 asks for
        local notifications *as well as* this path rather than instead of it.
        """
        payload = json.dumps(
            {
                "chat_id": self._chat_id,
                "text": f"[{kind.value}] {body}",
                "disable_notification": not kind.is_alert,
            }
        ).encode()
        request = urllib.request.Request(
            self._url("sendMessage"),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, OSError, TimeoutError):
            # Deliberately not re-raising and not including the exception text:
            # urllib puts the full URL — and therefore the token — into several
            # of its error messages.
            return False

    def diagnose(self) -> tuple[bool, str]:
        """Attempt one delivery and return (ok, a specific reason).

        `send()` deliberately swallows everything, which is right for a running
        session and useless for a preflight. This exists because the first real
        run of `verify_telegram.py` reported "verify the token is current and
        the chat id is..." when the actual cause was a network policy denying
        api.telegram.org — sending an operator to rotate a perfectly good
        credential.

        `credentials.py` was written for exactly this failure on the broker side:
        an error that is wrong in a way that sends someone to fix the wrong
        thing costs more than no error at all. So the three causes are named
        apart, because the remedies are completely different — reach the host,
        replace the token, or fix the destination.

        Telegram's error `description` is diagnostic and carries no secret, so
        it is surfaced; everything still passes through `redact()` because the
        URL that produced it does carry one.
        """
        payload = json.dumps({"chat_id": self._chat_id, "text": "preflight"}).encode()
        request = urllib.request.Request(
            self._url("sendMessage"),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                if 200 <= response.status < 300:
                    return True, "delivered"
                return False, redact(f"unexpected HTTP {response.status}")
        except urllib.error.HTTPError as error:
            body = ""
            try:
                body = json.loads(error.read(600).decode()).get("description", "")
            except Exception:
                pass
            if error.code == 401:
                return False, redact(
                    f"401 Unauthorized — the bot token is not valid. It was revoked, "
                    f"regenerated, or copied incompletely. {body}"
                )
            if error.code in (400, 403):
                return False, redact(
                    f"{error.code} — the token works but the destination does not: "
                    f"{body or 'chat not found'}. Send the bot a message first, then "
                    f"take message.chat.id from /getUpdates. A bot cannot open a "
                    f"conversation with you."
                )
            return False, redact(f"HTTP {error.code}: {body}")
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            return False, redact(
                f"api.telegram.org is not reachable from this machine "
                f"({type(error).__name__}). This is a NETWORK result, not a credential "
                f"one — the token and chat id may both be correct. Check egress policy, "
                f"proxy rules, or DNS before changing any credential."
            )

    def describe_failure(self, error: BaseException) -> str:
        """Render an exception for a log, with any token removed (§17, §0.2)."""
        return redact(f"{type(error).__name__}: {error}")
