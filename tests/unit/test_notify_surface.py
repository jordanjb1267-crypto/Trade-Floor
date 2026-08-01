"""The §19 policy surface over the verified transport (§19, §17, §0.2).

Transport behaviour lives in `test_notify.py` against `notify/telegram.py`.
This file covers the policy layer: the halt-only command surface, the typed
notification set, redaction for script output, and the remedy mapping.

Ported from the pre-consolidation `test_notifications.py`; the tests that
exercised the deleted duplicate transport were dropped rather than translated,
because the surviving transport has its own suite and a translated test
asserting the same thing twice is how two suites drift apart while both stay
green.
"""

import os
from unittest import mock

import pytest

from trading_firm.execution.credentials import CredentialError
from trading_firm.notify import surface, telegram
from trading_firm.notify.surface import (
    NotificationKind,
    OwnerCommand,
    notify_owner,
    parse_owner_command,
    redact,
    remedy_for,
)

# Shaped like a real Telegram token so the redactor is exercised honestly, but
# not one — the digits are sequential and the secret half is a fixed filler.
FAKE_TOKEN = "1234567890:" + ("A" * 35)
FAKE_CHAT = "-1001234567890"


@pytest.fixture
def configured():
    with mock.patch.dict(
        os.environ,
        {telegram.BOT_TOKEN_VAR: FAKE_TOKEN, telegram.CHAT_ID_VAR: FAKE_CHAT},
        clear=False,
    ):
        yield


class TestTheCommandSurfaceCannotGrant:
    """§19: a bot token is a bearer credential on a phone. Whoever holds it can
    send whatever the surface accepts, so the surface accepts only restriction."""

    def test_no_command_can_enable_approve_or_raise(self) -> None:
        forbidden = ("enable", "approve", "allow", "unfreeze", "resume", "activate", "raise")
        for member in OwnerCommand:
            lowered = member.name.lower()
            assert not any(word in lowered for word in forbidden), (
                f"{member.name} is a permissive remote command: an attacker holding "
                f"the bot token could use it to start or size the firm (§19, §0.10)"
            )

    def test_every_command_is_restrictive_or_read_only(self) -> None:
        for member in OwnerCommand:
            assert member.is_restrictive or member is OwnerCommand.STATUS

    def test_the_import_guard_fires_on_a_permissive_command(self) -> None:
        """The guard is only worth having if it actually trips."""
        import enum

        real = surface.OwnerCommand
        try:
            surface.OwnerCommand = enum.StrEnum(
                "OwnerCommand", {"KILL": "kill", "ENABLE_LIVE": "enable_live"}
            )
            with pytest.raises(RuntimeError, match="halt-only"):
                surface._no_permissive_commands()
        finally:
            surface.OwnerCommand = real

    def test_the_import_guard_fires_on_an_unregistered_command(self) -> None:
        """A creatively-named permissive command defeats the word denylist, so
        the registered set is the real control."""
        import enum

        real = surface.OwnerCommand
        try:
            members = {m.name: m.value for m in real}
            members["YOLO"] = "yolo"  # no forbidden word in the name
            surface.OwnerCommand = enum.StrEnum("OwnerCommand", members)
            with pytest.raises(RuntimeError, match="registered explicitly"):
                surface._no_permissive_commands()
        finally:
            surface.OwnerCommand = real

    def test_the_real_enum_passes(self) -> None:
        surface._no_permissive_commands()  # does not raise


class TestCommandParsing:
    @pytest.mark.parametrize("text", ["/kill", "kill", "  KILL  ", "/KILL"])
    def test_kill_parses(self, text: str) -> None:
        parsed = parse_owner_command(text)
        assert parsed is not None and parsed.command is OwnerCommand.KILL

    def test_an_argument_command_without_one_is_not_a_command(self) -> None:
        assert parse_owner_command("/disable_instrument") is None
        parsed = parse_owner_command("/disable_instrument GBP_USD")
        assert parsed is not None and parsed.argument == "GBP_USD"

    @pytest.mark.parametrize(
        "text", ["", "   ", "hello", "/enable_live", "/approve", "/approve_trade yes"]
    )
    def test_unrecognised_input_is_not_a_command(self, text: str) -> None:
        # Returning None rather than raising: an owner mistyping gets "not a
        # command", and a prober learns nothing from the difference.
        assert parse_owner_command(text) is None


class TestShapeValidation:
    """A well-formed value of the wrong KIND must fail before any I/O.

    The observed failure, not a hypothetical: a real environment carried the
    bot's @username as TELEGRAM_CHAT_ID. It passes every generic credential
    check and can never receive a message, so a §19 risk-halt alert would have
    died as a silent 400 mid-session.
    """

    @pytest.mark.parametrize(
        "bad_chat_id",
        ["my_trading_bot", "TradeFloorBot", "bot", "not-a-number", "123abc", "@x"],
    )
    def test_a_non_chat_id_is_rejected_at_preflight(self, bad_chat_id: str) -> None:
        with mock.patch.dict(
            os.environ,
            {telegram.BOT_TOKEN_VAR: FAKE_TOKEN, telegram.CHAT_ID_VAR: bad_chat_id},
            clear=False,
        ):
            with pytest.raises(CredentialError, match="NUMERIC chat id"):
                telegram.preflight()

    @pytest.mark.parametrize(
        "good_chat_id",
        ["5044229533", "-1001234567890", "-987654321", "@a_public_channel"],
    )
    def test_a_real_chat_id_is_accepted(self, good_chat_id: str) -> None:
        with mock.patch.dict(
            os.environ,
            {telegram.BOT_TOKEN_VAR: FAKE_TOKEN, telegram.CHAT_ID_VAR: good_chat_id},
            clear=False,
        ):
            telegram.preflight()  # does not raise

    @pytest.mark.parametrize("bad_token", ["not-a-token", "12345", "abcdef:ghijkl", "5044229533"])
    def test_a_token_of_the_wrong_shape_is_rejected(self, bad_token: str) -> None:
        # Pasting the chat id into the token field is the mirror mistake.
        with mock.patch.dict(
            os.environ,
            {telegram.BOT_TOKEN_VAR: bad_token, telegram.CHAT_ID_VAR: FAKE_CHAT},
            clear=False,
        ):
            with pytest.raises(CredentialError, match="bot token"):
                telegram.preflight()

    def test_the_rejection_does_not_echo_the_value(self) -> None:
        with mock.patch.dict(
            os.environ,
            {telegram.BOT_TOKEN_VAR: FAKE_TOKEN, telegram.CHAT_ID_VAR: "secret_bot_name"},
            clear=False,
        ):
            with pytest.raises(CredentialError) as excinfo:
                telegram.preflight()
        assert "secret_bot_name" not in str(excinfo.value)


class TestRedaction:
    def test_redact_removes_a_token_shaped_string(self) -> None:
        assert FAKE_TOKEN not in redact(f"failed calling /bot{FAKE_TOKEN}/sendMessage")
        assert "<redacted-token>" in redact(f"boom {FAKE_TOKEN}")

    def test_redact_handles_the_url_form(self) -> None:
        url = f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
        assert FAKE_TOKEN not in redact(f"HTTPError 401 for {url}")


class TestNotificationKinds:
    def test_the_nineteen_minimum_set_is_covered(self) -> None:
        # §19's "at minimum provide" list, one member each.
        assert len(surface.SPEC_MINIMUM_KINDS) == 11
        assert surface.SPEC_MINIMUM_KINDS <= {member.value for member in NotificationKind}

    def test_every_kind_is_registered_as_spec_or_operational(self) -> None:
        """Replaces a bare `len() == 11`, which could be satisfied by deleting
        one kind and adding another. The registry says which is which, so an
        operational message can never be passed off as a §19 requirement."""
        declared = {member.value for member in NotificationKind}
        assert declared == surface.SPEC_MINIMUM_KINDS | surface.OPERATIONAL_KINDS
        assert not (surface.SPEC_MINIMUM_KINDS & surface.OPERATIONAL_KINDS)

    def test_the_supervisor_startup_kind_is_operational_not_spec(self) -> None:
        value = NotificationKind.SUPERVISOR_STARTUP_HEALTH.value
        assert value in surface.OPERATIONAL_KINDS
        assert value not in surface.SPEC_MINIMUM_KINDS

    def test_the_startup_kind_is_not_an_alert(self) -> None:
        """A process starting is routine. Marking it an alert would train the
        owner to ignore the channel that carries RISK_HALT."""
        assert not NotificationKind.SUPERVISOR_STARTUP_HEALTH.is_alert

    def test_alerts_are_marked(self) -> None:
        assert NotificationKind.RISK_HALT.is_alert
        assert NotificationKind.DATA_OR_BROKER_FAILURE.is_alert
        assert NotificationKind.TIER_CHANGE.is_alert
        assert not NotificationKind.DAILY_SESSION_REPORT.is_alert

    def test_notify_owner_prefixes_the_kind(self, configured) -> None:
        captured = {}

        def fake_transport(url, body, timeout):
            captured["body"] = body.decode()
            return 200, b'{"ok": true, "result": {"message_id": 1}}'

        with mock.patch.object(telegram, "_default_transport", fake_transport):
            result = notify_owner(NotificationKind.RISK_HALT, "session halted")
        assert result.ok is True
        assert "[risk_halt] session halted" in captured["body"]

    def test_an_untyped_send_has_no_entry_point_here(self) -> None:
        # notify_owner requires a NotificationKind; the transport's send() is
        # for scripts and the runner, not a way around the typing.
        with pytest.raises(AttributeError):
            surface.send  # noqa: B018


class TestRemedyMapping:
    """The three causes have completely different remedies: reach the host,
    replace the token, or fix the destination. The first real preflight run
    misdiagnosed a network denial as a credential problem."""

    @staticmethod
    def _result(**kw):
        base = dict(ok=False, stage="api", detail="x", status=None, message_id=None, attempts=1)
        base.update(kw)
        return telegram.NotifyResult(**base)

    def test_no_status_is_named_a_network_result(self) -> None:
        remedy = remedy_for(self._result(detail="tunnel connection failed"))
        assert "NETWORK result, not a credential one" in remedy
        assert "rotate" not in remedy.lower()

    def test_401_names_the_token(self) -> None:
        assert "token is not valid" in remedy_for(self._result(status=401))

    def test_400_names_the_destination_not_the_token(self) -> None:
        remedy = remedy_for(self._result(status=400, detail="chat not found"))
        assert "the token works" in remedy
        assert "A bot cannot open a conversation" in remedy

    def test_preflight_failures_pass_through(self) -> None:
        remedy = remedy_for(self._result(stage="preflight", detail="TELEGRAM_CHAT_ID must be..."))
        assert remedy.startswith("TELEGRAM_CHAT_ID")

    def test_success_is_delivered(self) -> None:
        assert remedy_for(self._result(ok=True)) == "delivered"
