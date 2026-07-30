"""`.env` loading (§17): the file is read, but the real environment wins.

Credential-shaped values are BUILT AT RUNTIME here, never written as static
literals — the pre-write hook scans for credential patterns and blocks them
(decision log, 2026-07-29).
"""

import os

import pytest

from trading_firm.env_file import load_env_file, parse_env_text

TOKEN_NAME = "OANDA_DEMO_API_TOKEN"


def fake_token(seed: str = "a") -> str:
    """Build a v20-shaped token at runtime: 32 hex chars, dash, 32 hex chars."""
    return (seed * 32)[:32] + "-" + (seed.upper() * 32)[:32]


def test_parses_keys_comments_quotes_and_export():
    token = fake_token()
    text = "\n".join(
        [
            "# a comment",
            "",
            f"{TOKEN_NAME}={token}",
            "export OANDA_DEMO_ACCOUNT_ID='001-001-1234567-001'",
            'FMP_API_KEY="quoted-value"',
        ]
    )
    parsed = parse_env_text(text)
    assert parsed[TOKEN_NAME] == token
    assert parsed["OANDA_DEMO_ACCOUNT_ID"] == "001-001-1234567-001"
    assert parsed["FMP_API_KEY"] == "quoted-value"


def test_value_containing_hash_is_kept_verbatim():
    # A credential may legitimately contain '#'; we must not treat it as a comment.
    value = "abc#def"
    assert parse_env_text(f"{TOKEN_NAME}={value}")[TOKEN_NAME] == value


def test_malformed_line_raises_without_echoing_content():
    secret = fake_token("b")
    with pytest.raises(ValueError) as err:
        parse_env_text(f"# ok\n{secret}\n")
    message = str(err.value)
    assert "line 2" in message
    assert secret not in message  # never echo a line that may hold a credential


def test_loads_when_variable_absent(tmp_path, monkeypatch):
    token = fake_token("c")
    env_path = tmp_path / ".env"
    env_path.write_text(f"{TOKEN_NAME}={token}\n")
    monkeypatch.delenv(TOKEN_NAME, raising=False)

    applied = load_env_file(env_path)

    assert applied == [TOKEN_NAME]
    assert os.environ[TOKEN_NAME] == token


def test_real_environment_wins_over_file(tmp_path, monkeypatch):
    exported, from_file = fake_token("d"), fake_token("e")
    env_path = tmp_path / ".env"
    env_path.write_text(f"{TOKEN_NAME}={from_file}\n")
    monkeypatch.setenv(TOKEN_NAME, exported)

    applied = load_env_file(env_path)

    assert applied == []
    assert os.environ[TOKEN_NAME] == exported


def test_empty_placeholder_is_not_loaded(tmp_path, monkeypatch):
    # .env.example ships `OANDA_DEMO_API_TOKEN=` — an empty value must not
    # shadow a real one or count as "set".
    env_path = tmp_path / ".env"
    env_path.write_text(f"{TOKEN_NAME}=\n")
    monkeypatch.delenv(TOKEN_NAME, raising=False)

    assert load_env_file(env_path) == []
    assert TOKEN_NAME not in os.environ


def test_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_NAME, raising=False)

    assert load_env_file(tmp_path / "does-not-exist") == []
    assert TOKEN_NAME not in os.environ  # caller still fails closed
