#!/usr/bin/env python3
"""Pre-edit protection and secret scanning hook (Master Handoff v1.1.3 §7.3).

Reads the Claude Code PreToolUse payload from stdin and blocks (exit 2):
  1. edits to protected production paths (§7.2) — live config, approvals,
     the hooks themselves, and Claude settings (M-4: hooks guard the guard);
  2. file writes whose content matches credential patterns (§17) — broker
     tokens, API keys, and .env-style secret assignments.

Owner override for path protection: set OWNER_APPROVED_PROTECTED_EDIT=1 for
the session, which represents explicit owner approval (§7.2 approval gates).
The secret scan has NO override: credentials never belong in the repo (§0.2).

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
                "credential pattern. Secrets belong in the OS keychain or an untracked .env — "
                "never in repository files. There is no override for this check (§0.2).",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
