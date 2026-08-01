"""The §19 notification surface and remote-control policy.

This package divides in two, deliberately:

- ``telegram.py`` is TRANSPORT — one bounded HTTPS POST, verified end-to-end
  against the real API on 2026-07-31 (message_id=8, HTTP 200;
  `docs/audits/2026-07-31-telegram-notify-e2e.md`). It stays as close to the
  verified code as possible so that evidence keeps describing the code that
  runs.
- this module is POLICY — what may be sent (§19's typed notification set) and,
  more importantly, what may be RECEIVED. Policy changes freely; transport
  does not.

The two were originally parallel implementations from two sessions that could
not see each other's work. The transport that had actually delivered a message
won the transport role; the policy layer that had the security surface won the
policy role; the duplicate transport was deleted rather than kept as an
alternative, because two code paths to the same API drift apart silently and
the §17 guarantees only hold on the one that is maintained.

**The inbound command surface is halt-only, by type.**

§19 lists seven owner controls, and they divide into two very different
classes. Restrictive controls — kill, halt, disable an instrument, disable a
strategy, freeze scaling, freeze promotion — can only ever *reduce* what the
firm may do. Permissive controls — "global live enable", "approve trade during
probation" — grant. A bot token is a bearer credential sitting on a phone and
travelling through a third party's servers; whoever holds it can send whatever
the surface accepts. If the surface accepts approvals, a compromised token
approves trades.

So `OwnerCommand` contains no permissive member and a module-level check
asserts it never gains one. An attacker holding the token can halt this firm —
the same thing the owner can do, and a fail-closed direction (§0.10). They
cannot start it, size it, or approve anything.

Live-trade approval over Telegram is therefore **deliberately not built**. §13
requires human approval for every live trade during probation, but it does not
require that approval to arrive over a messaging app, and Phase 6 is shadow
and paper where there is nothing live to approve. Building the approval path
is a Phase 7 decision that needs its own threat model.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from trading_firm.notify import telegram as transport

# Matched loosely on purpose: redaction should over-match rather than let one
# through. The transport scrubs its own results; this exists for anything a
# SCRIPT prints, where the exact secrets tuple is not in hand.
_TOKEN_PATTERN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")


def redact(text: str) -> str:
    """Remove anything token-shaped from text bound for a log or an exception.

    A token in an exception string reaches the audit trail, and §0 rule 11
    makes that record immutable — there is no cleaning it up afterwards.
    """
    text = _TOKEN_PATTERN.sub("<redacted-token>", text)
    return re.sub(r"/bot[^/\s]+/", "/bot<redacted-token>/", text)


class NotificationKind(enum.StrEnum):
    """The §19 minimum set, plus operational additions. Named so a report
    cannot be sent untyped.

    §19 specifies a MINIMUM set, so adding a kind is permitted; adding one
    quietly is not. `SUPERVISOR_STARTUP_HEALTH` is the one addition, and it is
    operational rather than a trading notification: it reports that the §18
    supervisor PROCESS reached a healthy initialisation, which is a different
    event from `SESSION_START_HEALTH` (the London session beginning). Conflating
    them would have made a crash-looping supervisor indistinguishable from a
    normal trading day in the owner's chat.

    Outbound kinds carry no authority — unlike `OwnerCommand`, nothing here can
    enable, approve, or size anything, so this set needs no permissive-member
    guard.
    """

    SESSION_START_HEALTH = "session_start_health"
    SUPERVISOR_STARTUP_HEALTH = "supervisor_startup_health"
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
    SURVEILLANCE_ALERT = "surveillance_alert"
    SURVEILLANCE_BRIEFING = "surveillance_briefing"

    @property
    def is_alert(self) -> bool:
        """Alerts must reach the owner even if routine reports are one day
        made quiet. Not yet wired to delivery options — metadata for the
        session runner to act on."""
        return self in (
            NotificationKind.RISK_HALT,
            NotificationKind.DATA_OR_BROKER_FAILURE,
            NotificationKind.TIER_CHANGE,
            NotificationKind.SURVEILLANCE_ALERT,
        )


# §19's "at minimum provide" list, one member each, written out so that adding
# an outbound kind is a deliberate act rather than an edit nobody reviews. Same
# discipline as REGISTERED_COMMANDS below — the inbound surface is the dangerous
# one, but a notification set that drifts silently is how an operational message
# ends up indistinguishable from a trading one in the owner's chat.
SPEC_MINIMUM_KINDS = frozenset(
    {
        "session_start_health",
        "candidate_approval_request",
        "order_submitted",
        "fill_confirmation",
        "stop_confirmation",
        "position_closed",
        "risk_halt",
        "data_or_broker_failure",
        "tier_change",
        "daily_session_report",
        "weekly_performance_report",
    }
)

# Additions beyond the §19 minimum. Every member here reports on the MACHINERY
# — that a process started, that a host is reachable — never on a position, a
# candidate, or a size. A kind that says something about trading belongs in the
# spec set, with the spec discussion that implies.
OPERATIONAL_KINDS = frozenset({"supervisor_startup_health"})

# The §30 surveillance class (A-3). Not operational — these say things about
# the MARKET, so they cannot ride in OPERATIONAL_KINDS without falsifying its
# contract — and not in the §19 minimum, which is pinned as ratified. A third
# registered set with its own contract: SURVEILLANCE_ALERT reaches Telegram
# only at MATERIAL/CRITICAL severity (owner decision 2026-07-31, §30.6; the
# config loader refuses a lower delivery threshold), and SURVEILLANCE_BRIEFING
# stays unused until the claude_agents flags enable scheduled briefings.
# Neither can carry a direction: the OpportunityAlert schema types
# trade_direction as None (§30.13).
SURVEILLANCE_KINDS = frozenset({"surveillance_alert", "surveillance_briefing"})


def _registered_notification_kinds() -> None:
    """Fail at import if the outbound set drifts from its registry."""
    declared = {member.value for member in NotificationKind}
    registered = SPEC_MINIMUM_KINDS | OPERATIONAL_KINDS | SURVEILLANCE_KINDS
    added = declared - registered
    removed = registered - declared
    overlaps = (
        (SPEC_MINIMUM_KINDS & OPERATIONAL_KINDS)
        | (SPEC_MINIMUM_KINDS & SURVEILLANCE_KINDS)
        | (OPERATIONAL_KINDS & SURVEILLANCE_KINDS)
    )
    if added or removed or overlaps:
        raise RuntimeError(
            f"NotificationKind changed (added={sorted(added)}, removed={sorted(removed)}, "
            f"overlaps={sorted(overlaps)}). §19 specifies a MINIMUM set, so additions are "
            f"allowed — but each one is registered explicitly and in exactly one set. Put a "
            f"spec-mandated kind in SPEC_MINIMUM_KINDS, an operational one in "
            f"OPERATIONAL_KINDS, a §30 surveillance one in SURVEILLANCE_KINDS, and say "
            f"which it is in the commit."
        )


_registered_notification_kinds()


def notify_owner(kind: NotificationKind, body: str) -> transport.NotifyResult:
    """Send one typed §19 notification. Never raises (§18).

    The kind travels in the message text, so the owner's chat is greppable by
    notification type and an untyped send has no entry point here.
    """
    return transport.send(f"[{kind.value}] {body}")


class OwnerCommand(enum.StrEnum):
    """Remote controls the owner may send (§19).

    Every member is RESTRICTIVE: it can only reduce what the firm may do.
    There is deliberately no `ENABLE_LIVE`, no `APPROVE_TRADE`, and no
    `UNFREEZE` — see the module docstring. `_no_permissive_commands()` runs at
    import and fails the process if one is ever added.
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
# cannot catch a creatively-named one, so the registered-set check below is
# the real guard; this exists to give a precise error for the obvious case.
_PERMISSIVE_HINTS = frozenset(
    {"enable", "approve", "allow", "unfreeze", "resume", "start", "activate", "promote", "raise"}
)

# The exact command set this module is registered to expose. Any addition
# trips the import-time check until someone deliberately registers it and
# states that it cannot grant. Same reasoning as REGISTERED_QUERY_FIELDS in
# research/analogs.py.
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
        name for name in named if any(hint in name.lower() for hint in _PERMISSIVE_HINTS)
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

    Unrecognised input returns None rather than raising: an owner mistyping
    into a chat window should get "not a command", and an attacker probing the
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


def remedy_for(result: transport.NotifyResult) -> str:
    """Turn a failed NotifyResult into the operator's next action.

    The three causes have completely different remedies — reach the host,
    replace the token, or fix the destination — and the first real preflight
    run misdiagnosed a network denial as a credential problem, sending the
    operator to rotate a perfectly good token. The transport reports facts;
    this maps them to actions, so the mapping can improve without touching
    verified code.
    """
    if result.ok:
        return "delivered"
    if result.stage == "preflight":
        return result.detail  # already names the variable and the fix
    if result.status is None:
        return (
            f"api.telegram.org was not reachable ({result.detail}). This is a NETWORK "
            f"result, not a credential one — the token and chat id may both be "
            f"correct. Check egress policy, proxy rules, or DNS before changing any "
            f"credential."
        )
    if result.status == 401:
        return (
            "401 Unauthorized — the bot token is not valid. It was revoked, "
            "regenerated, or copied incompletely. Issue a new one in BotFather."
        )
    if result.status in (400, 403):
        return (
            f"{result.status} — the token works but the destination does not "
            f"({result.detail}). Send the bot a message first, then take "
            f"message.chat.id from /getUpdates. A bot cannot open a conversation "
            f"with you."
        )
    return result.detail
