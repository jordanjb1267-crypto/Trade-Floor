"""`scripts/check_env.py` — the canonical structure-only `.env` validator.

**No test here reads the repository's real `.env`.** Every case builds a
throwaway git repository under `tmp_path` with fixture credentials that are
shaped correctly but fabricated. That is not merely hygiene: a test suite that
reads the owner's real credential file would put its contents one bad assertion
message away from CI output.
"""

from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("check_env", REPO / "scripts" / "check_env.py")
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: @dataclass resolves annotations via
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_env = _load()

# Shaped like the real thing, and entirely fabricated.
FAKE_OANDA = "0123456789abcdef" * 4  # 64 hex chars -> split into two 32-char halves
FAKE_OANDA = FAKE_OANDA[:32] + "-" + FAKE_OANDA[32:]
FAKE_BOT = "1234567890:" + "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRr"
FAKE_CHAT = "5044229533"

GOOD = (
    f"OANDA_DEMO_API_TOKEN={FAKE_OANDA}\n"
    f"TELEGRAM_BOT_TOKEN={FAKE_BOT}\n"
    f"TELEGRAM_CHAT_ID={FAKE_CHAT}\n"
)


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo that ignores .env, like the real one."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".env\n.env.*\n!.env.example\n")
    return tmp_path


def write_env(repo: Path, text: str, mode: int = 0o600) -> Path:
    path = repo / ".env"
    path.write_text(text)
    path.chmod(mode)
    return path


def results(repo: Path, **kwargs) -> dict[str, check_env.Check]:
    path = repo / ".env"
    checks = check_env.run_checks(path, repo_root=repo, **kwargs)
    return {check.name: check for check in checks}


class TestSuccess:
    def test_a_correct_env_passes_every_check(self, repo) -> None:
        write_env(repo, GOOD)
        checks = check_env.run_checks(repo / ".env", repo_root=repo)
        failed = [c.name for c in checks if not c.ok]
        assert failed == []

    def test_exit_code_is_zero(self, repo, capsys) -> None:
        write_env(repo, GOOD)
        code = check_env.main(["--path", str(repo / ".env"), "--repo-root", str(repo)])
        assert code == 0
        assert "ALL PASS" in capsys.readouterr().out

    def test_comments_blanks_quotes_and_export_are_accepted(self, repo) -> None:
        write_env(
            repo,
            "# owner-managed, never committed\n\n"
            f"export OANDA_DEMO_API_TOKEN='{FAKE_OANDA}'\n"
            f'TELEGRAM_BOT_TOKEN="{FAKE_BOT}"\n'
            f"TELEGRAM_CHAT_ID={FAKE_CHAT}\n",
        )
        checks = check_env.run_checks(repo / ".env", repo_root=repo)
        assert [c.name for c in checks if not c.ok] == []

    def test_a_negative_group_chat_id_is_valid(self, repo) -> None:
        write_env(repo, GOOD.replace(FAKE_CHAT, "-1001234567890"))
        assert results(repo)["format: TELEGRAM_CHAT_ID"].ok


class TestFailureClasses:
    def test_absent_file(self, repo) -> None:
        checks = check_env.run_checks(repo / ".env", repo_root=repo)
        assert not checks[0].ok
        assert all(not c.ok for c in checks), "an absent file fails every check"

    def test_absent_file_exits_nonzero(self, repo) -> None:
        assert check_env.main(["--path", str(repo / ".env"), "--repo-root", str(repo)]) == 1

    def test_a_symlink_is_refused(self, repo) -> None:
        real = repo / "elsewhere"
        real.write_text(GOOD)
        (repo / ".env").symlink_to(real)
        found = results(repo)
        assert not found["regular file"].ok
        assert "symlink" in found["regular file"].detail

    def test_malformed_line(self, repo) -> None:
        write_env(repo, GOOD + "this line has no equals sign\n")
        found = results(repo)
        assert not found["lines well-formed"].ok
        assert "line 4" in found["lines well-formed"].detail

    def test_empty_key(self, repo) -> None:
        write_env(repo, GOOD + "=orphaned\n")
        assert not results(repo)["lines well-formed"].ok

    def test_duplicate_assignment(self, repo) -> None:
        write_env(repo, GOOD + f"TELEGRAM_CHAT_ID={FAKE_CHAT}\n")
        found = results(repo)
        assert not found["no duplicate assignments"].ok
        assert "lines 3 and 4" in found["no duplicate assignments"].detail

    def test_a_duplicate_is_not_silently_resolved(self, repo) -> None:
        """`env_file.parse_env_text` builds a dict, so a repeat overwrites
        silently. Which value is live is ambiguous, so it must be reported."""
        _, _, duplicates = check_env.parse_assignments("A=1\nA=2\n")
        assert duplicates

    def test_extra_variable(self, repo) -> None:
        write_env(repo, GOOD + "EXTRA_TOKEN=whatever\n")
        found = results(repo)
        assert not found["exactly the required variables"].ok
        assert "unexpected EXTRA_TOKEN" in found["exactly the required variables"].detail

    def test_missing_variable(self, repo) -> None:
        write_env(repo, f"OANDA_DEMO_API_TOKEN={FAKE_OANDA}\n")
        found = results(repo)
        assert not found["exactly the required variables"].ok
        assert "missing TELEGRAM_BOT_TOKEN" in found["exactly the required variables"].detail
        assert not found["format: TELEGRAM_BOT_TOKEN"].ok

    def test_placeholder_is_rejected(self, repo) -> None:
        """The 2026-07-30 lifecycle failure: a literal `<practice token>`."""
        write_env(repo, GOOD.replace(FAKE_OANDA, "<practice token>"))
        found = results(repo)
        assert not found["format: OANDA_DEMO_API_TOKEN"].ok
        assert "placeholder" in found["format: OANDA_DEMO_API_TOKEN"].detail

    def test_changeme_is_rejected(self, repo) -> None:
        write_env(repo, GOOD.replace(FAKE_CHAT, "changeme"))
        assert not results(repo)["format: TELEGRAM_CHAT_ID"].ok

    def test_empty_value_is_rejected(self, repo) -> None:
        write_env(repo, GOOD.replace(FAKE_CHAT, ""))
        assert not results(repo)["format: TELEGRAM_CHAT_ID"].ok

    def test_malformed_oanda_token(self, repo) -> None:
        write_env(repo, GOOD.replace(FAKE_OANDA, "not-a-token"))
        found = results(repo)
        assert not found["format: OANDA_DEMO_API_TOKEN"].ok
        assert "shape" in found["format: OANDA_DEMO_API_TOKEN"].detail

    def test_a_bot_username_is_not_a_chat_id(self, repo) -> None:
        """The misconfiguration actually seen in this environment: a bot's
        @username passes every generic check and can never receive a message."""
        write_env(repo, GOOD.replace(FAKE_CHAT, "@Tradingfloorlondonbot"))
        # @channelusername IS valid for a public channel, so this must pass the
        # SHAPE check — the distinction is not one a file validator can make.
        assert results(repo)["format: TELEGRAM_CHAT_ID"].ok

    def test_not_gitignored(self, repo) -> None:
        (repo / ".gitignore").write_text("# nothing ignored\n")
        write_env(repo, GOOD)
        found = results(repo)
        assert not found["git ignores .env"].ok
        assert "committed by accident" in found["git ignores .env"].detail

    def test_tracked_by_git(self, repo) -> None:
        write_env(repo, GOOD)
        subprocess.run(["git", "-C", str(repo), "add", "-f", ".env"], check=True)
        found = results(repo)
        assert not found["not tracked by git"].ok
        assert "rotate every value" in found["not tracked by git"].detail

    def test_any_failure_exits_nonzero(self, repo) -> None:
        write_env(repo, GOOD + "EXTRA=1\n")
        assert check_env.main(["--path", str(repo / ".env"), "--repo-root", str(repo)]) == 1


class TestPermissionRemediation:
    def test_a_loose_mode_is_corrected_in_place(self, repo) -> None:
        write_env(repo, GOOD, mode=0o644)
        found = results(repo)
        assert found["permissions are 0600"].ok
        assert "REMEDIATED" in found["permissions are 0600"].detail
        assert stat.S_IMODE((repo / ".env").lstat().st_mode) == 0o600

    def test_an_already_correct_mode_is_left_alone(self, repo) -> None:
        write_env(repo, GOOD, mode=0o600)
        assert "REMEDIATED" not in results(repo)["permissions are 0600"].detail

    def test_no_fix_reports_without_touching_the_mode(self, repo) -> None:
        write_env(repo, GOOD, mode=0o644)
        found = results(repo, fix_permissions=False)
        assert not found["permissions are 0600"].ok
        assert "found 0644" in found["permissions are 0600"].detail
        assert stat.S_IMODE((repo / ".env").lstat().st_mode) == 0o644


class TestNoValueEverEscapes:
    """The property the whole script exists to guarantee."""

    def test_no_value_appears_in_a_fully_passing_report(self, repo) -> None:
        write_env(repo, GOOD)
        report = check_env.render(check_env.run_checks(repo / ".env", repo_root=repo))
        for secret in (FAKE_OANDA, FAKE_BOT, FAKE_CHAT):
            assert secret not in report

    def test_no_value_appears_when_every_check_fails(self, repo) -> None:
        write_env(repo, GOOD + "EXTRA=1\nbroken line\n", mode=0o644)
        report = check_env.render(check_env.run_checks(repo / ".env", repo_root=repo))
        for secret in (FAKE_OANDA, FAKE_BOT, FAKE_CHAT):
            assert secret not in report

    def test_a_malformed_line_is_reported_by_number_not_content(self, repo) -> None:
        write_env(repo, GOOD + "OANDA_DEMO_API_TOKEN_LEAKED_SOMEHOW\n")
        report = check_env.render(check_env.run_checks(repo / ".env", repo_root=repo))
        assert "line 4" in report
        assert "LEAKED_SOMEHOW" not in report

    def test_the_guard_refuses_a_report_containing_a_value(self) -> None:
        with pytest.raises(check_env.SecretLeakError) as caught:
            check_env.assert_no_values(
                f"FAIL  format: X  bad value {FAKE_BOT}", {"TELEGRAM_BOT_TOKEN": FAKE_BOT}
            )
        assert "TELEGRAM_BOT_TOKEN" in str(caught.value)
        assert FAKE_BOT not in str(caught.value)

    def test_stdout_never_carries_a_value(self, repo, capsys) -> None:
        write_env(repo, GOOD)
        check_env.main(["--path", str(repo / ".env"), "--repo-root", str(repo)])
        captured = capsys.readouterr()
        for secret in (FAKE_OANDA, FAKE_BOT, FAKE_CHAT):
            assert secret not in captured.out
            assert secret not in captured.err


class TestSharedVocabularyDoesNotDrift:
    def test_the_telegram_shapes_match_the_notify_transport(self) -> None:
        """Duplicated shapes are only safe if they cannot drift."""
        from trading_firm.notify import telegram

        assert check_env.FORMATS["TELEGRAM_BOT_TOKEN"].pattern == telegram._TOKEN_SHAPE.pattern
        assert check_env.FORMATS["TELEGRAM_CHAT_ID"].pattern == telegram._CHAT_ID_SHAPE.pattern

    def test_the_required_set_matches_what_the_runtime_reads(self) -> None:
        from trading_firm.execution import credentials
        from trading_firm.notify import telegram

        assert credentials.TOKEN_VAR in check_env.REQUIRED_VARS
        assert telegram.BOT_TOKEN_VAR in check_env.REQUIRED_VARS
        assert telegram.CHAT_ID_VAR in check_env.REQUIRED_VARS

    def test_the_grammar_agrees_with_the_canonical_parser(self) -> None:
        from trading_firm.env_file import parse_env_text

        text = "# c\n\nexport A='1'\nB=\"2\"\nC=3\n"
        mine, malformed, duplicates = check_env.parse_assignments(text)
        assert not malformed and not duplicates
        assert mine == parse_env_text(text)


class TestDoesNotTouchTheRealEnv:
    def test_the_default_path_is_the_repository_root(self) -> None:
        assert check_env.REPO == REPO

    def test_no_test_in_this_file_reads_the_real_env(self) -> None:
        """Guard against a future test dropping the --path argument.

        The needles are assembled at runtime so this assertion does not match
        its own source — the first version did, and failed on itself.
        """
        source = Path(__file__).read_text()
        no_args = "main(" + "[])"
        real_root = "run_checks(" + "REPO"
        assert no_args not in source, "a test invokes the validator against the real .env"
        assert real_root not in source, "a test points run_checks at the real repo root"
