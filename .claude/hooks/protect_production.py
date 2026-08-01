#!/usr/bin/env python3
"""Pre-edit protection and secret scanning hook (Master Handoff v1.1.3 §7.3).

Reads the Claude Code PreToolUse payload from stdin and blocks (exit 2):
  1. any write to an owner-managed credential file (§7.2) — `.env` and its
     variants are created and maintained by the owner directly on the local
     machine, outside Claude; no agent may create, modify, or delete one;
  2. edits to protected production paths (§7.2) — live config, approvals,
     the hooks themselves, and Claude settings (M-4: hooks guard the guard);
  3. file writes whose content matches credential patterns (§17) — broker
     tokens, API keys, and .env-style secret assignments.

Owner override for path protection (2): set OWNER_APPROVED_PROTECTED_EDIT=1
for the session, which represents explicit owner approval (§7.2 approval
gates). Checks (1) and (3) have NO override, and (1) is deliberately tested
before the override is read, so no approval can unlock a credential file
(§0.2).

`.env.example` is exempt from (1): it is the tracked, value-free template and
agents are expected to maintain it. Real values never belong in it.

To verify a local `.env` without exposing its contents, run
`python3 scripts/check_env.py` — existence, variable set, formats, git-ignore
status, and permissions, reported pass/fail only.

This is fast feedback, not the security boundary — OS permissions and startup
hash verification are the enforcement layers (§7.3, §17).
"""

import json
import os
import re
import sys

PROTECTED_PREFIXES = (
    "config/live/",
    "governance/approvals/",
    ".claude/hooks/",
)
PROTECTED_FILES = (".claude/settings.json",)

# The only .env-family file an agent may write: the tracked, value-free template.
ENV_TEMPLATE = ".env.example"

SECRET_PATTERNS = (
    # OANDA v20 personal access token: 32 hex, dash, 32 hex
    re.compile(r"\b[a-f0-9]{32}-[a-f0-9]{32}\b", re.IGNORECASE),
    # key/token/secret assignment to a >=20-char value (yaml/env/py/js styles)
    re.compile(
        r"(?i)\b(api[_-]?key|api[_-]?token|access[_-]?token|secret[_-]?key|auth[_-]?token|"
        r"password|passwd)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}"
    ),
    # bearer header with a literal token
    re.compile(r"(?i)authorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9_\-\.]{16,}"),
)


def _relative(path: str) -> str:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    absolute = os.path.abspath(path)
    try:
        return os.path.relpath(absolute, root)
    except ValueError:
        return path


def _is_owner_managed_env(rel: str) -> bool:
    """True for any `.env` / `.env.<suffix>` file except the tracked template.

    Matched on basename, so the rule holds at any depth — mirroring how
    .gitignore already treats these paths (`.env`, `.env.*`, `!.env.example`).
    """
    name = rel.rsplit("/", 1)[-1]
    if name == ENV_TEMPLATE:
        return False
    return name == ".env" or name.startswith(".env.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed payload: do not block unrelated tools

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path")
    if not file_path:
        return 0
    rel = _relative(file_path).replace(os.sep, "/")

    # Checked first, and before the override is read: an owner approval for a
    # protected path must never become an approval to write a credential file.
    if _is_owner_managed_env(rel):
        print(
            f"BLOCKED (§7.2 owner-managed credential file): '{rel}' is created and "
            "maintained by the owner directly on the local machine, outside Claude. "
            "No agent may create, modify, or delete it. This check has no override — "
            "OWNER_APPROVED_PROTECTED_EDIT does not apply here.\n"
            f"  - Agents MAY edit '{ENV_TEMPLATE}': the tracked, value-free template. "
            "Add the variable name with an empty value; never a real one.\n"
            "  - To confirm a local .env is correct without exposing values, run:\n"
            "        python3 scripts/check_env.py\n"
            "    It reports existence, variable set, formats, git-ignore status, and "
            "file permissions as pass/fail only, and never prints a value.",
            file=sys.stderr,
        )
        return 2

    if rel.startswith(PROTECTED_PREFIXES) or rel in PROTECTED_FILES:
        if os.environ.get("OWNER_APPROVED_PROTECTED_EDIT") == "1":
            return 0
        print(
            f"BLOCKED (§7.3 pre-edit protection): '{rel}' is a protected production path. "
            "Owner approval is required: re-run with OWNER_APPROVED_PROTECTED_EDIT=1 only "
            "after explicit owner sign-off, and record the change in governance/decision-log.md.",
            file=sys.stderr,
        )
        return 2

    content = tool_input.get("content") or tool_input.get("new_string") or ""
    for pattern in SECRET_PATTERNS:
        if pattern.search(content):
            print(
                f"BLOCKED (§17 secret scan): the content being written to '{rel}' matches a "
                "credential pattern. Credentials live only in the OS keychain or the owner's "
                "local .env — neither of which any agent may write. There is no override for "
                "this check (§0.2).\n"
                f"  - Put the variable name with an empty value in '{ENV_TEMPLATE}' instead.\n"
                "  - To validate the owner's local .env: python3 scripts/check_env.py",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
