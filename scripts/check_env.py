#!/usr/bin/env python3
"""Structure-only validation of the repository-root `.env` (§17).

The pre-write hook refuses every agent Write/Edit to `.env` with no override:
the file is created and maintained by the owner, locally, outside Claude. That
prohibition is only workable if there is a way to answer "is my `.env` correct?"
without opening it, and this is that way.

**It never reveals a value.** Not in output, not in an error, not in a summary.
Errors name the VARIABLE and the reason; parse failures name the LINE NUMBER and
never the line. Before anything is printed, the rendered report is scanned for
every value the file contains and printing is refused outright if one appears —
so a future edit that interpolates a value into a message fails loudly instead
of leaking (§0 iron rule 5, and §0 rule 11 makes an audit record immutable).

Reuses `trading_firm.execution.credentials.validate_credential`, the shared §17
preflight, so the placeholder vocabulary cannot drift from the OANDA and
Telegram paths — the 2026-07-30 lifecycle attempt failed on a literal
`<practice token>` and that lesson lives in one place.

Permissions are REMEDIATED, not merely reported: a `.env` found at anything
other than 0600 is corrected in place. A credential file readable by other
local accounts is a finding you want fixed at the moment it is noticed, not
filed. Pass `--no-fix-permissions` to report without touching the mode.

    python3 scripts/check_env.py             # validate ./.env
    python3 scripts/check_env.py --path X    # validate elsewhere (tests)
"""

from __future__ import annotations

import argparse
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_firm.execution.credentials import (  # noqa: E402
    CredentialError,
    validate_credential,
)

REQUIRED_VARS = ("OANDA_DEMO_API_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
# Optional, validated-when-present (account-pinning review, 2026-08-11). An
# operator who writes this variable gets full validation: empty, placeholder,
# whitespace-corrupted, and malformed values all FAIL — an attempted pin is
# never silently equivalent to no pin. The known-variable contract stays
# strict: anything outside REQUIRED + OPTIONAL is still rejected.
OPTIONAL_VARS = ("OANDA_DEMO_ACCOUNT_ID",)
REQUIRED_MODE = 0o600

# Shapes. The two Telegram patterns mirror `trading_firm.notify.telegram`;
# tests/unit/test_check_env.py asserts they never drift from it. The OANDA
# practice token is two 32-character hex halves joined by a hyphen.
FORMATS = {
    "OANDA_DEMO_API_TOKEN": re.compile(r"^[0-9a-f]{32}-[0-9a-f]{32}$"),
    "TELEGRAM_BOT_TOKEN": re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$"),
    "TELEGRAM_CHAT_ID": re.compile(r"^(-?\d+|@[A-Za-z][A-Za-z0-9_]{4,})$"),
    # Structural plausibility only, mirroring execution/credentials.py. This is
    # NOT a practice-vs-live rule: no authoritative documentation lets an id
    # prefix prove environment locally, so the practice boundary remains the
    # hard-coded host + practice token + broker authorization (§13).
    "OANDA_DEMO_ACCOUNT_ID": re.compile(r"^\d{3}-\d{3}-\d+-\d{3}$"),
}


class SecretLeakError(RuntimeError):
    """Raised instead of printing a report that contains a credential value."""


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def parse_assignments(text: str) -> tuple[dict[str, str], list[str], list[str]]:
    """Return (values, malformed, duplicates).

    Same grammar as `trading_firm.env_file.parse_env_text` — `KEY=VALUE`, an
    optional `export `, blanks, `#` comments, surrounding quotes stripped — with
    one deliberate difference: that parser builds a dict, so a repeated key
    silently overwrites. A duplicate assignment is ambiguous about which value
    is live, so it is reported here rather than resolved.

    Problems carry line NUMBERS only. The line itself may be a credential.
    """
    values: dict[str, str] = {}
    first_seen: dict[str, int] = {}
    malformed: list[str] = []
    duplicates: list[str] = []

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            malformed.append(f"line {number} is not KEY=VALUE")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            malformed.append(f"line {number} has an empty key")
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key in values:
            duplicates.append(f"{key} assigned twice (lines {first_seen[key]} and {number})")
            continue
        first_seen[key] = number
        values[key] = value
    return values, malformed, duplicates


def check_value(name: str, value: str) -> Check:
    """Placeholder/whitespace via the shared §17 validator, then shape."""
    try:
        cleaned = validate_credential(name, value)
    except CredentialError as error:
        # CredentialError never embeds the value — it names the variable only.
        return Check(f"format: {name}", False, str(error))
    if not FORMATS[name].match(cleaned):
        return Check(
            f"format: {name}",
            False,
            "present, but does not match the expected shape for this credential",
        )
    return Check(f"format: {name}", True)


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def check_git_ignored(env_path: Path, repo_root: Path) -> Check:
    result = _git(repo_root, "check-ignore", "-q", str(env_path))
    if result.returncode == 0:
        return Check("git ignores .env", True)
    return Check(
        "git ignores .env",
        False,
        "not matched by any .gitignore rule — it could be committed by accident",
    )


def check_untracked(env_path: Path, repo_root: Path) -> Check:
    result = _git(repo_root, "ls-files", "--error-unmatch", str(env_path))
    if result.returncode != 0:
        return Check("not tracked by git", True)
    return Check(
        "not tracked by git",
        False,
        "TRACKED — the credential file is in the repository index; remove it with "
        "`git rm --cached` and rotate every value it holds",
    )


def check_permissions(env_path: Path, *, fix: bool) -> Check:
    mode = stat.S_IMODE(env_path.lstat().st_mode)
    if mode == REQUIRED_MODE:
        return Check(f"permissions are {REQUIRED_MODE:04o}", True)
    if not fix:
        return Check(
            f"permissions are {REQUIRED_MODE:04o}",
            False,
            f"found {mode:04o}; readable beyond the owner",
        )
    env_path.chmod(REQUIRED_MODE)
    return Check(
        f"permissions are {REQUIRED_MODE:04o}",
        True,
        f"REMEDIATED: was {mode:04o}, now {REQUIRED_MODE:04o}",
    )


def run_checks(
    env_path: Path, *, repo_root: Path, fix_permissions: bool = True
) -> list[Check]:
    """Every check, always in the same order. Never raises on a bad file."""
    if not env_path.exists():
        absent = "file absent"
        return [
            Check("file exists", False, f"no file at {env_path.name}"),
            *[Check(n, False, absent) for n in ("regular file", "lines well-formed",
                                                "no duplicate assignments",
                                                "exactly the required variables")],
            *[Check(f"format: {v}", False, absent) for v in REQUIRED_VARS],
            *[Check(n, False, absent) for n in ("git ignores .env", "not tracked by git",
                                                f"permissions are {REQUIRED_MODE:04o}")],
        ]

    checks = [Check("file exists", True)]

    if not env_path.is_file() or env_path.is_symlink():
        kind = "symlink" if env_path.is_symlink() else "not a regular file"
        checks.append(Check("regular file", False, kind))
        return checks
    checks.append(Check("regular file", True))

    values, malformed, duplicates = parse_assignments(
        env_path.read_text(encoding="utf-8", errors="replace")
    )
    checks.append(Check("lines well-formed", not malformed, "; ".join(malformed)))
    checks.append(Check("no duplicate assignments", not duplicates, "; ".join(duplicates)))

    missing = [name for name in REQUIRED_VARS if name not in values]
    extras = sorted(set(values) - set(REQUIRED_VARS) - set(OPTIONAL_VARS))
    problems = []
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    if extras:
        problems.append(f"unexpected {', '.join(extras)}")
    checks.append(
        Check("exactly the required variables", not problems, "; ".join(problems))
    )

    for name in REQUIRED_VARS:
        if name in values:
            checks.append(check_value(name, values[name]))
        else:
            checks.append(Check(f"format: {name}", False, "variable absent"))
    for name in OPTIONAL_VARS:
        if name in values:
            # Present means the operator attempted a pin: full validation, and
            # empty/placeholder/malformed all fail — never "same as absent".
            checks.append(check_value(name, values[name]))

    checks.append(check_git_ignored(env_path, repo_root))
    checks.append(check_untracked(env_path, repo_root))
    checks.append(check_permissions(env_path, fix=fix_permissions))
    return checks


def render(checks: list[Check]) -> str:
    width = max(len(check.name) for check in checks)
    lines = [
        f"{'PASS' if c.ok else 'FAIL'}  {c.name:<{width}}  {c.detail}".rstrip()
        for c in checks
    ]
    failed = [c for c in checks if not c.ok]
    lines.append("")
    lines.append(
        f"{len(failed)} of {len(checks)} checks FAILED" if failed else "ALL PASS"
    )
    return "\n".join(lines)


def assert_no_values(report: str, values: dict[str, str]) -> None:
    """Refuse to print a report containing a credential value.

    The guard names the VARIABLE, never the value. It exists because "we only
    print names" is a review claim, and the next person to add a message will
    not have read this docstring.
    """
    for name, value in values.items():
        if value and len(value) >= 8 and value in report:
            raise SecretLeakError(
                f"refusing to print a report containing the value of {name} "
                f"(§0 iron rule 5). This is a bug in a check's detail text."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=None, help="the .env to validate")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument(
        "--no-fix-permissions",
        action="store_true",
        help="report the mode without correcting it",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root or REPO
    env_path = args.path or (repo_root / ".env")

    checks = run_checks(
        env_path, repo_root=repo_root, fix_permissions=not args.no_fix_permissions
    )
    report = render(checks)

    values: dict[str, str] = {}
    if env_path.is_file() and not env_path.is_symlink():
        values, _, _ = parse_assignments(
            env_path.read_text(encoding="utf-8", errors="replace")
        )
    assert_no_values(report, values)

    print(report)
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
