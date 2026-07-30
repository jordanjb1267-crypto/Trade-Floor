"""Load an untracked `.env` into the process environment (§17).

`.env.example` tells the owner to "copy to .env on the trading laptop", but
nothing ever read that file: every entry point calls `os.environ.get(...)`
directly and there is no dotenv dependency. A correctly filled-in `.env`
therefore did nothing, and the scripts failed closed with "token not set"
while the token sat in the file. This module closes that gap.

Rules, in keeping with §17 and §0 iron rule 5:

- **The real environment always wins.** A variable already present in
  `os.environ` is never overwritten, so exported values and CI/session
  settings take precedence over a stale file on disk.
- **Values are never logged.** Callers get back the NAMES that were loaded,
  never the values; parse errors report a line number, never line content.
- **Absence is not an error.** No `.env` simply loads nothing — the caller
  still fails closed on the missing variable, as before.

This does not make `.env` a blessed secret store. §17 still prefers the OS
keychain; `.env` remains a local, untracked convenience (it is gitignored,
and the pre-write hook scans for credential patterns).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_env_text(text: str) -> dict[str, str]:
    """Parse `.env` content into a mapping. Raises ValueError on a bad line.

    Accepts `KEY=value`, a leading `export `, blank lines, and `#` comments.
    Surrounding single or double quotes are stripped. Values are otherwise
    taken verbatim after the first `=` (no inline-comment stripping — a
    credential may legitimately contain `#`).
    """
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            # Never echo the line itself — it may hold a credential.
            raise ValueError(f".env line {number} is not KEY=VALUE")
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f".env line {number} has an empty key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(path: Path | None = None) -> list[str]:
    """Load `.env` into os.environ without overriding existing variables.

    Returns the sorted names actually applied (empty if the file is absent,
    empty, or every key was already set). Never returns or logs values.
    """
    env_path = path if path is not None else REPO_ROOT / ".env"
    if not env_path.is_file():
        return []
    applied: list[str] = []
    for key, value in parse_env_text(env_path.read_text()).items():
        if os.environ.get(key):
            continue  # real environment wins
        if not value:
            continue  # empty placeholder, as shipped in .env.example
        os.environ[key] = value
        applied.append(key)
    return sorted(applied)
