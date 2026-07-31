"""Telegram notification and remote-control path (§19, §18, §17, §0.2).

Two properties carry the weight here: a token must never reach a log or an
exception, and the remote command surface must never be able to grant anything.
"""

import os
from unittest import mock

import pytest

from trading_firm.notifications import telegram as tg
from trading_firm.notifications.telegram import (
    NotificationKind,
    OwnerCommand,
    TelegramConfigError,
    TelegramNotifier,
    parse_owner_command,
    redact,
)

# Shaped like a real Telegram token so the redactor is exercised honestly, but
# not one — the digits are sequential and the secret half is a fixed filler.
FAKE_TOKEN = "1234567890:" + ("A" * 35)
FAKE_CHAT = "-1001234567890"


@pytest.fixture
def configured():
    with mock.patch.dict(
        os.environ, {tg.TOKEN_VAR: FAKE_TOKEN, tg.CHAT_VAR: FAKE_CHAT}, clear=False
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
        real = tg.OwnerCommand
        try:
            import enum

            tg.OwnerCommand = enum.StrEnum(
                "OwnerCommand", {"KILL": "kill", "ENABLE_LIVE": "enable_live"}
            )
            with pytest.raises(RuntimeError, match="halt-only"):
                tg._no_permissive_commands()
        finally:
            tg.OwnerCommand = real

    def test_the_import_guard_fires_on_an_unregistered_command(self) -> None:
        """A creatively-named permissive command defeats the word denylist, so
        the registered set is the real control — same reasoning as
        REGISTERED_QUERY_FIELDS in research/analogs.py."""
        real = tg.OwnerCommand
        try:
            import enum

            members = {m.name: m.value for m in real}
            members["YOLO"] = "yolo"  # no forbidden word in the name
            tg.OwnerCommand = enum.StrEnum("OwnerCommand", members)
            with pytest.raises(RuntimeError, match="registered explicitly"):
                tg._no_permissive_commands()
        finally:
            tg.OwnerCommand = real

    def test_the_real_enum_passes(self) -> None:
        tg._no_permissive_commands()  # does not raise


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


class TestTokenNeverEscapes:
    """§17 / §0.2. Telegram puts the token in the URL PATH, which is the most
    log-prone place a secret can sit — request loggers, retry wrappers, and
    exception messages all routinely carry a URL."""

    def test_redact_removes_a_token_shaped_string(self) -> None:
        assert FAKE_TOKEN not in redact(f"failed calling /bot{FAKE_TOKEN}/sendMessage")
        assert "<redacted-token>" in redact(f"boom {FAKE_TOKEN}")

    def test_redact_handles_the_url_form(self) -> None:
        url = f"https://api.telegram.org/bot{FAKE_TOKEN}/sendMessage"
        assert FAKE_TOKEN not in redact(f"HTTPError 401 for {url}")

    def test_repr_does_not_leak(self, configured) -> None:
        notifier = TelegramNotifier()
        rendered = repr(notifier)
        assert FAKE_TOKEN not in rendered
        assert "redacted" in rendered

    def test_describe_failure_strips_a_token_from_an_exception(self, configured) -> None:
        notifier = TelegramNotifier()
        error = OSError(f"connection refused for https://api.telegram.org/bot{FAKE_TOKEN}/x")
        described = notifier.describe_failure(error)
        assert FAKE_TOKEN not in described

    def test_a_transport_failure_returns_false_without_raising(self, configured) -> None:
        # urllib embeds the full URL in several of its error messages, so the
        # exception is swallowed rather than re-raised or logged.
        notifier = TelegramNotifier()
        with mock.patch.object(
            tg.urllib.request, "urlopen", side_effect=OSError(f"boom {FAKE_TOKEN}")
        ):
            assert notifier.send(NotificationKind.RISK_HALT, "halted") is False

    def test_a_config_error_names_the_variable_not_the_value(self) -> None:
        with mock.patch.dict(
            os.environ, {tg.TOKEN_VAR: "  ", tg.CHAT_VAR: FAKE_CHAT}, clear=False
        ):
            with pytest.raises(TelegramConfigError) as excinfo:
                TelegramNotifier()
        message = str(excinfo.value)
        assert tg.TOKEN_VAR in message
        assert FAKE_TOKEN not in message


class TestConfiguration:
    def test_missing_token_fails_closed(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(TelegramConfigError, match=tg.TOKEN_VAR):
                TelegramNotifier()

    def test_missing_chat_id_fails_closed(self) -> None:
        # A bot token alone cannot send anything; the destination is required.
        with mock.patch.dict(os.environ, {tg.TOKEN_VAR: FAKE_TOKEN}, clear=True):
            with pytest.raises(TelegramConfigError, match=tg.CHAT_VAR):
                TelegramNotifier()

    def test_a_placeholder_is_rejected_before_any_request(self) -> None:
        with mock.patch.dict(
            os.environ,
            {tg.TOKEN_VAR: "<your-bot-token>", tg.CHAT_VAR: FAKE_CHAT},
            clear=False,
        ):
            with pytest.raises(TelegramConfigError, match="placeholder"):
                TelegramNotifier()

    def test_no_token_literal_appears_in_the_module(self) -> None:
        """§0.2: the token must come from the environment, never a literal."""
        import pathlib

        source = pathlib.Path(tg.__file__).read_text()
        assert not tg._TOKEN_PATTERN.search(source), (
            "a token-shaped literal is present in the notifications module"
        )


class TestNotificationKinds:
    def test_the_nineteen_minimum_set_is_covered(self) -> None:
        # §19's "at minimum provide" list, one member each.
        assert len(NotificationKind) == 11

    def test_alerts_are_marked_and_bypass_silent_delivery(self, configured) -> None:
        assert NotificationKind.RISK_HALT.is_alert
        assert NotificationKind.DATA_OR_BROKER_FAILURE.is_alert
        assert NotificationKind.TIER_CHANGE.is_alert
        assert not NotificationKind.DAILY_SESSION_REPORT.is_alert

    def test_an_alert_is_sent_with_notification_enabled(self, configured) -> None:
        notifier = TelegramNotifier()
        captured = {}

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake(request, timeout=None):
            captured["body"] = request.data.decode()
            return _Response()

        with mock.patch.object(tg.urllib.request, "urlopen", _fake):
            assert notifier.send(NotificationKind.RISK_HALT, "session halted") is True
        assert '"disable_notification": false' in captured["body"]
        assert "risk_halt" in captured["body"]


class TestAWellFormedValueOfTheWrongKindIsRejected:
    """Found by running the preflight against a real configuration.

    The generic check — non-empty, no whitespace, not a placeholder — passed a
    bot's @username configured as TELEGRAM_CHAT_ID. It is a perfectly valid
    string that can never receive a message: Telegram answers "chat not found"
    at send time, so the failure surfaces as silent non-delivery during a
    session rather than as a config error before one. A validator that accepts
    an unusable value is the failure this codebase keeps finding — it passes, so
    nobody looks again.
    """

    @pytest.mark.parametrize(
        "bad_chat_id",
        [
            "my_trading_bot",  # a bot username, the real misconfiguration
            "TradeFloorBot",
            "bot",
            "not-a-number",
            "123abc",
            "@x",  # too short for a channel handle
        ],
    )
    def test_a_non_chat_id_is_rejected(self, bad_chat_id: str) -> None:
        with mock.patch.dict(
            os.environ, {tg.TOKEN_VAR: FAKE_TOKEN, tg.CHAT_VAR: bad_chat_id}, clear=False
        ):
            with pytest.raises(TelegramConfigError, match="NUMERIC chat id"):
                TelegramNotifier()

    @pytest.mark.parametrize(
        "good_chat_id",
        [
            "5044229533",  # a personal chat
            "-1001234567890",  # a supergroup
            "-987654321",  # a group
            "@a_public_channel",
        ],
    )
    def test_a_real_chat_id_is_accepted(self, good_chat_id: str) -> None:
        with mock.patch.dict(
            os.environ, {tg.TOKEN_VAR: FAKE_TOKEN, tg.CHAT_VAR: good_chat_id}, clear=False
        ):
            TelegramNotifier()  # does not raise

    @pytest.mark.parametrize(
        "bad_token", ["not-a-token", "12345", "abcdef:ghijkl", "5044229533"]
    )
    def test_a_token_of_the_wrong_shape_is_rejected(self, bad_token: str) -> None:
        # Pasting the chat id into the token field is the mirror mistake.
        with mock.patch.dict(
            os.environ, {tg.TOKEN_VAR: bad_token, tg.CHAT_VAR: FAKE_CHAT}, clear=False
        ):
            with pytest.raises(TelegramConfigError, match="bot token"):
                TelegramNotifier()

    def test_the_rejection_does_not_echo_the_value(self) -> None:
        with mock.patch.dict(
            os.environ, {tg.TOKEN_VAR: FAKE_TOKEN, tg.CHAT_VAR: "secret_bot_name"}, clear=False
        ):
            with pytest.raises(TelegramConfigError) as excinfo:
                TelegramNotifier()
        assert "secret_bot_name" not in str(excinfo.value)
