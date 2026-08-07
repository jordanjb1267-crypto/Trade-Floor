#!/usr/bin/env python3
"""Verify that text quoted next to a §-reference actually appears in that section.

`check_spec_refs.py` proves every `§N` resolves to a real heading. It cannot
prove the section says what the citing code claims, and that gap is not
theoretical: the 2026-07-30 adversarial review found `agents/bench.py` quoting
two real sentences — "consulted by default" and "no trade quota and no automatic
capital allocation" — and attributing both to §6.3, when they live in §1. The
checker was green throughout, because §6.3 is a real section.

An operator following a citation during an incident opens the cited section and
does not find the rule the code says it is implementing. That is the same class
of failure as the six agent files that passed CI for three spec versions while
pointing at v1.1.3: the reference resolved, the claim did not.

What counts as an attribution here is deliberately narrow — a quoted phrase
within `WINDOW` characters of a §-reference, on the same line or the one before.
Quotation marks are also used for illustration ("the week has been flat" as an
example of forbidden reasoning), and flagging those would train people to ignore
the checker. When in doubt this stays silent: a false negative costs one missed
citation, a false positive costs the tool's credibility.

Usage:
    python3 scripts/check_spec_quotes.py          # check
    python3 scripts/check_spec_quotes.py --list   # show what it considers an attribution
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOVERNING = ROOT / "docs" / "spec" / "CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.5.0.md"

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
    # Vendored dependencies are not ours to quote-check (see check_spec_refs.py).
    ".venv",
    "venv",
    "site-packages",
}
SUFFIXES = {".py", ".md", ".yaml", ".yml"}

# A quote is attributed if a §-ref sits this close to it.
WINDOW = 160
# Three, not four. The first version used four and therefore did NOT catch the
# misattribution it was written for — `"consulted by default"` is three words,
# so the checker passed a reintroduced copy of the exact bug. A guard that
# cannot catch its own motivating example is the failure this whole review kept
# finding, and writing the guard is no protection against writing it wrong.
MIN_WORDS = 3

TRIPLE_DQ = chr(34) * 3
TRIPLE_SQ = chr(39) * 3

QUOTE = re.compile(r'"([^"\n]{18,240})"')
REF = re.compile(r"§(\d+)(?:\.(\d+))?")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("—", "-"), ("–", "-")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip().lower()


def section_bodies(spec: str) -> dict[str, str]:
    """Map "6" and "6.3" to their text. A major section includes its subsections,
    so a quote cited as §6 resolves if it appears anywhere beneath §6."""
    lines = spec.splitlines()
    starts: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        major = re.match(r"^#\s+(\d+)\.\s", line)
        minor = re.match(r"^##\s+(\d+)\.(\d+)\s", line)
        if major:
            starts.append((i, major.group(1)))
        elif minor:
            starts.append((i, f"{minor.group(1)}.{minor.group(2)}"))

    bodies: dict[str, str] = {}
    for idx, (start, key) in enumerate(starts):
        if "." in key:
            end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        else:
            end = len(lines)
            for later_start, later_key in starts[idx + 1:]:
                if "." not in later_key:
                    end = later_start
                    break
        bodies[key] = normalize("\n".join(lines[start:end]))
    return bodies


def candidate_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(p in SKIP_DIRS for p in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(SKIP_PREFIXES) or path.suffix not in SUFFIXES:
            continue
        out.append(path)
    return out


def prose_lines(path: Path, text: str) -> set[int]:
    """Line numbers carrying PROSE, not code.

    The first version of this checker scanned every line and produced 391 false
    positives — Python error messages and f-string fragments all look like
    quotations to a regex. A checker that cries wolf 391 times is worse than no
    checker, because the next real finding is scrolled past.

    The second version counted triple-quote characters to find docstrings, and
    a single unbalanced count left `in_doc` stuck True for the rest of the file,
    so every assertion message after it was scanned as prose. It flagged one
    immediately. Counting delimiters is a parser, and writing a bad parser by
    accident is how the first two attempts here failed.

    So the docstring ranges come from the AST and the comments from `tokenize`,
    both of which already know exactly where they are.
    """
    if path.suffix in {".md", ".yaml", ".yml"}:
        return set(range(1, len(text.splitlines()) + 1))

    prose: set[int] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return prose

    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            prose.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                prose.add(token.start[0])
    except (tokenize.TokenError, IndentationError):
        pass

    return prose


def attributions(path: Path, text: str) -> list[tuple[int, str, str]]:
    """(lineno, cited_section, quote) for quotes sitting beside a §-reference."""
    found: list[tuple[int, str, str]] = []
    lines = text.splitlines()
    allowed = prose_lines(path, text)
    for lineno, line in enumerate(lines, 1):
        if lineno not in allowed:
            continue
        # Strip docstring delimiters first. A line opening with triple quotes
        # pairs its third quote with the first quote of the phrase inside it, so
        # `"""... says are "consulted by default" in ...` captured the PREFIX and
        # never the phrase — which is why the first version of this checker
        # silently passed a reintroduced copy of the bug it was written for.
        scan = line.replace(TRIPLE_DQ, "   ").replace(TRIPLE_SQ, "   ")
        context = (lines[lineno - 2] if lineno >= 2 else "") + " " + scan
        for match in QUOTE.finditer(scan):
            quote = match.group(1)
            if quote.count(" ") + 1 < MIN_WORDS or quote.rstrip().endswith(":"):
                continue
            # Format placeholders, embedded §-refs, and fragments starting
            # mid-sentence are code or self-reference, never a citation.
            if "{" in quote or "}" in quote or "§" in quote:
                continue
            if not quote[0].isalnum():
                continue
            near = context[max(0, match.start() - WINDOW):match.end() + WINDOW]
            refs = REF.findall(near)
            if not refs:
                continue
            # Attribute to the nearest cited section; a quote beside several is
            # checked against all of them and passes if any contains it.
            for major, minor in refs:
                found.append((lineno, f"{major}.{minor}" if minor else major, quote))
    return found


def main() -> int:
    if not GOVERNING.exists():
        print(f"FAIL: governing spec not found at {GOVERNING.relative_to(ROOT)}")
        return 2
    bodies = section_bodies(GOVERNING.read_text())

    grouped: dict[tuple[str, int, str], list[str]] = {}
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, section, quote in attributions(path, text):
            grouped.setdefault((rel, lineno, quote), []).append(section)

    if "--list" in sys.argv:
        for (rel, lineno, quote), sections in sorted(grouped.items()):
            print(f"{rel}:{lineno}  §{'/§'.join(sections)}  \"{quote[:70]}\"")
        print(f"\n{len(grouped)} attributed quote(s)")
        return 0

    bad = []
    for (rel, lineno, quote), sections in sorted(grouped.items()):
        needle = normalize(quote)
        if any(needle in bodies.get(s, "") for s in sections):
            continue
        # Only report when at least one cited section exists; a nonexistent
        # section is check_spec_refs.py's job, not this one.
        if any(s in bodies for s in sections):
            bad.append((rel, lineno, sections, quote))

    if bad:
        print(f"FAIL: {len(bad)} quote(s) not found in the section they cite\n")
        for rel, lineno, sections, quote in bad:
            print(f"  {rel}:{lineno}  cited §{'/§'.join(sections)}")
            print(f'    "{quote[:100]}"')
            for key, body in bodies.items():
                if normalize(quote) in body and "." in key:
                    print(f"    -> this text is in §{key}")
                    break
        print("\nQuote the section the sentence is actually in, or paraphrase without")
        print("quotation marks. A citation an auditor cannot follow is worse than none.")
        return 1

    print(f"OK: all {len(grouped)} attributed quote(s) appear in the section they cite")
    return 0


if __name__ == "__main__":
    sys.exit(main())
