#!/usr/bin/env python3
"""Verify every §-reference in the repo resolves against the governing spec.

The 2026-07-30 coupling audit found 857 §-references across 97 files — inside
module docstrings, YAML comments, agent frontmatter, and (most consequentially)
the ValueError messages that 18 config validators raise for an operator to read
during an incident. Nothing verified that a cited section still meant what the
citing code claimed. A spec renumber would have invalidated all of them
silently, with no test failing.

This closes that gap: §N and §N.N must resolve to a real heading, and §0.N must
resolve to a position in the §0 iron-rule list (which has no anchors — the
references are positional, so an inserted rule silently corrupts every citation
after it).

Append-only historical records are skipped by design: `governance/decision-log.md`,
`docs/audits/`, `docs/reviews/`, and superseded reports cite the spec version in
force when they were written, and §0 rule 11 forbids rewriting them.

Usage:
    python3 scripts/check_spec_refs.py            # check
    python3 scripts/check_spec_refs.py --list     # show the resolved section map
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOVERNING = ROOT / "docs" / "spec" / "CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.4.0.md"

# Paths whose §-citations are historical statements, not live claims.
SKIP_PREFIXES = (
    "docs/spec/",
    "docs/reviews/",
    "docs/audits/",
    "governance/decision-log.md",
    "reports/validation/",
)
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "node_modules",
    # Vendored dependencies are not ours to cite-check: a third-party file whose
    # docstring happens to use the section sign is not a stale reference to this
    # firm's spec (pygments ships one such lexer).
    ".venv",
    "venv",
    "site-packages",
}
SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".sql", ".toml", ".example", ".gitignore"}

REF = re.compile(r"§(\d+)(?:\.(\d+))?")

# A citation naming a spec VERSION -- the words "Master Handoff" followed by a
# semantic version. Distinct
# from a §-reference: the section resolves fine while the version claim is false.
VERSIONED_CITATION = re.compile(r"Master Handoff (v\d+\.\d+\.\d+)")
# A file claiming to name the governing spec.
GOVERNING_CLAIM = re.compile(r"Governing specification[:\s]+\S*?(CLAUDE_\S+?\.md)")


def spec_sections(spec: str) -> tuple[set[str], int]:
    """Return ({"3", "3.2", ...}, number of §0 iron rules)."""
    found: set[str] = set()
    for line in spec.splitlines():
        m = re.match(r"^#\s+(\d+)\.\s", line)
        if m:
            found.add(m.group(1))
            continue
        m = re.match(r"^##\s+(\d+)\.(\d+)\s", line)
        if m:
            found.add(m.group(1))
            found.add(f"{m.group(1)}.{m.group(2)}")
    # §0's rules are an ordered list under "Mandatory operating rules", not headings.
    rules = 0
    in_block = False
    for line in spec.splitlines():
        if line.startswith("## Mandatory operating rules"):
            in_block = True
            continue
        if in_block:
            if line.startswith("#") or line.startswith("---"):
                break
            if re.match(r"^\d+\.\s+\*\*", line):
                rules += 1
    found.add("0")
    return found, rules


def candidate_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue
        if path.suffix in SUFFIXES or path.name in {".env.example", ".gitignore"}:
            out.append(path)
    return out


def main() -> int:
    if not GOVERNING.exists():
        print(f"FAIL: governing spec not found at {GOVERNING.relative_to(ROOT)}")
        return 2
    sections, rule_count = spec_sections(GOVERNING.read_text())
    if "--list" in sys.argv:
        print(f"governing spec: {GOVERNING.name}")
        print(f"§0 iron rules: {rule_count}")
        ordered = sorted(sections, key=lambda s: [int(x) for x in s.split(".")])
        print("sections:", ", ".join(ordered))
        return 0

    bad: list[tuple[str, int, str, str]] = []
    checked = 0
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            for major, minor in REF.findall(line):
                checked += 1
                ref = f"{major}.{minor}" if minor else major
                if major == "0":
                    if minor and not (1 <= int(minor) <= rule_count):
                        bad.append((rel, lineno, f"§{ref}", f"§0 has {rule_count} rules"))
                elif ref not in sections:
                    bad.append((rel, lineno, f"§{ref}", "no such section in the governing spec"))

    # --- stale spec-version pointers -----------------------------------------
    # The §-checker cannot catch these: a versioned citation names a section
    # section that resolves perfectly while naming a spec three versions dead.
    # That is the same failure as the six agent files which passed CI for three
    # versions pointing at v1.1.3 — a reference that resolves while the claim is
    # false. Found in seven files on 2026-07-31, including
    # src/trading_firm/__init__.py, which said "Governing specification:" and
    # named the superseded v1.1.4.
    current_version = re.search(r"_v(\d+\.\d+\.\d+)\.md$", GOVERNING.name)
    current = f"v{current_version.group(1)}" if current_version else None
    stale: list[tuple[str, int, str]] = []
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            for cited in VERSIONED_CITATION.findall(line):
                if current and cited != current:
                    why = f"cites 'Master Handoff {cited}', current is {current}"
                    stale.append((rel, lineno, why))
            for named in GOVERNING_CLAIM.findall(line):
                if named != GOVERNING.name:
                    stale.append((rel, lineno, f"claims the governing spec is {named}"))

    # Paths this process cannot edit: §7.2/§7.3 protected files need
    # OWNER_APPROVED_PROTECTED_EDIT, and .env* is read-blocked so a secret cannot
    # be pulled into context. Drift there is real and must stay visible, but CI
    # cannot be held red on a fix only the owner can apply — so it is reported
    # every run and attributed, rather than suppressed or blocking.
    owner_only = (".claude/hooks/", ".claude/settings", ".env.example")
    blocking = [f for f in stale if not f[0].startswith(owner_only)]
    for_owner = [f for f in stale if f[0].startswith(owner_only)]

    if for_owner:
        print(f"NOTE: {len(for_owner)} stale spec-version pointer(s) in owner-only paths")
        for rel, lineno, why in for_owner:
            print(f"  {rel}:{lineno}  {why}")
        print("  These need OWNER_APPROVED_PROTECTED_EDIT=1 and a decision-log entry")
        print("  (§7.2/§7.3). Not failing CI: the implementer cannot apply the fix.\n")

    if blocking:
        print(f"FAIL: {len(blocking)} stale spec-version pointer(s)\n")
        for rel, lineno, why in blocking:
            print(f"  {rel}:{lineno}  {why}")
        print("\nThese resolve as §-references while naming a superseded spec. Cite the")
        print("section without a version, or name the current governing document.")
        return 1

    if bad:
        print(f"FAIL: {len(bad)} unresolved §-reference(s) of {checked} checked\n")
        for rel, lineno, ref, why in bad:
            print(f"  {rel}:{lineno}  {ref} — {why}")
        return 1
    print(f"OK: all {checked} §-references resolve against {GOVERNING.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
