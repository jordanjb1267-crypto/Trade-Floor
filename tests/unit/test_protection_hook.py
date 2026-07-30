"""Tests for the §7.3 pre-edit protection and secret-scan hook.

Secret-like strings are constructed at runtime (concatenation/repetition) so
this file's own text never matches the scanner's patterns — the hook scans
file writes, including writes of this file.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "protect_production.py"
ROOT = HOOK.parents[2]


def run_hook(tool_input: dict, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    env.pop("OWNER_APPROVED_PROTECTED_EDIT", None)
    env.update(env_extra or {})
    payload = json.dumps({"tool_name": "Write", "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


class TestProtectedPaths:
    def test_live_config_blocked(self) -> None:
        result = run_hook({"file_path": str(ROOT / "config/live/firm.yaml"), "content": "x: 1"})
        assert result.returncode == 2
        assert "protected production path" in result.stderr

    def test_approvals_blocked(self) -> None:
        result = run_hook({"file_path": str(ROOT / "governance/approvals/rec.md"), "content": "x"})
        assert result.returncode == 2

    def test_hooks_protect_themselves(self) -> None:
        # M-4: the hook files are themselves protected paths.
        result = run_hook({"file_path": str(HOOK), "content": "pass"})
        assert result.returncode == 2

    def test_owner_override_allows_path(self) -> None:
        result = run_hook(
            {"file_path": str(ROOT / "config/live/firm.yaml"), "content": "x: 1"},
            env_extra={"OWNER_APPROVED_PROTECTED_EDIT": "1"},
        )
        assert result.returncode == 0

    def test_ordinary_path_allowed(self) -> None:
        result = run_hook(
            {"file_path": str(ROOT / "src/trading_firm/risk/engine.py"), "content": "x = 1"}
        )
        assert result.returncode == 0


class TestSecretScan:
    def test_broker_token_shape_blocked(self) -> None:
        token = "a" * 32 + "-" + "b" * 32  # hex32-hex32, built at runtime
        result = run_hook({"file_path": str(ROOT / "notes.md"), "content": f"token {token}"})
        assert result.returncode == 2
        assert "secret scan" in result.stderr

    def test_key_assignment_blocked(self) -> None:
        content = "api" + "_key" + ' = "' + "A1zZ" * 6 + '"'  # assembled, never literal
        result = run_hook({"file_path": str(ROOT / "src/x.py"), "content": content})
        assert result.returncode == 2

    def test_bearer_header_blocked(self) -> None:
        content = "Autho" + "rization: Bea" + "rer " + "t0" * 10
        result = run_hook({"file_path": str(ROOT / "notes.md"), "content": content})
        assert result.returncode == 2

    def test_no_override_for_secrets(self) -> None:
        token = "c" * 32 + "-" + "d" * 32
        result = run_hook(
            {"file_path": str(ROOT / "notes.md"), "content": token},
            env_extra={"OWNER_APPROVED_PROTECTED_EDIT": "1"},
        )
        assert result.returncode == 2

    def test_sha256_in_docs_not_flagged(self) -> None:
        # 64 contiguous hex chars (a document hash) must not trip the token pattern.
        result = run_hook({"file_path": str(ROOT / "docs/x.md"), "content": "sha256 " + "e" * 64})
        assert result.returncode == 0

    def test_env_example_placeholders_allowed(self) -> None:
        placeholders = "FMP_API" + "_KEY=\nOANDA_DEMO_API" + "_TOKEN=\n"
        result = run_hook({"file_path": str(ROOT / "docs/setup.md"), "content": placeholders})
        assert result.returncode == 0
