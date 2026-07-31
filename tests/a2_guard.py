"""Shared A-2 pressure-invariance guard (§5.1, §6.6).

Every module that classifies, scores, ranks, or sets a significance threshold
must be a pure function of the market. §5.1 states it; this is how it is
checked.

**Why this file exists.** The first version of this guard, written inline in
`test_classification.py` and copied into four other test modules, matched a
single literal string: `FirmSnapshot`. An adversarial review defeated it by
mutation in under a minute — importing `AccountState` instead and making a
significance threshold depend on `session_realized_loss` left all 65 tests in
`test_experiments.py` green. The guard had been checking a *name*, not a
*property*, and `FirmSnapshot` is only one of several types that carry firm
state. Copying it five times multiplied the blind spot rather than the
protection.

So the denylist here is over the whole firm-state vocabulary, not one type, and
it lives in one place so strengthening it strengthens every caller at once. It
is still a denylist and therefore still defeasible by a sufficiently determined
rename — but the names below are the ones the codebase actually uses, and a
contributor who invents a synonym to route around this has left an obvious
trail in the diff.
"""

from __future__ import annotations

import ast
import pathlib
from types import ModuleType

# Types that carry firm state. Reaching any of them from a classification path
# is an A-2 violation regardless of what the module then does with it.
FIRM_STATE_TYPES = frozenset(
    {
        "FirmSnapshot",
        "AccountState",
        "DrawdownState",
        "PendingPromotion",
        "RiskDecision",
        "SizingResult",
    }
)

# Field names that ARE firm state, whatever type happens to hold them. These
# catch the case where someone passes the values individually rather than
# passing the object — the mutation that defeated the original guard.
FIRM_STATE_FIELDS = frozenset(
    {
        "closed_equity",
        "tier_anchor",
        "session_realized_loss",
        "weekly_realized_loss",
        "trades_this_session",
        "exceptional_trades_this_session",
        "open_positions",
        "drawdown_state",
        "allowed_risk_usd",
        "days_elapsed",
        "cumulative_return",
        "progress_to_target",
    }
)

FORBIDDEN = FIRM_STATE_TYPES | FIRM_STATE_FIELDS


def _executable_source(source: str) -> str:
    """Source with comments and docstrings removed.

    Prose may legitimately discuss firm state — this whole guard is explained
    in a docstring that names it. Only code counts.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                node.value.value = ""  # blank the docstring, keep the structure
    return ast.unparse(tree)


def assert_pressure_blind(module: ModuleType, allow: frozenset[str] = frozenset()) -> None:
    """Fail if `module` can reach firm state (A-2, §5.1).

    `allow` exists for a module with a legitimate, reviewed reason to name one
    of these — pass the specific string, never a blanket exemption, and say why
    at the call site.
    """
    path = pathlib.Path(module.__file__)
    source = path.read_text()
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {alias.name for alias in node.names}
            imported |= {(alias.asname or alias.name) for alias in node.names}
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
            imported |= {(alias.asname or alias.name) for alias in node.names}

    banned = FORBIDDEN - allow
    bad_imports = sorted(banned & imported)
    assert not bad_imports, (
        f"{module.__name__} imports firm state {bad_imports}: classification, scoring, "
        f"ranking, and significance thresholds must be pure functions of the market. "
        f"Firm state reaches the risk gate only, where it may lower and never raise "
        f"(A-2, §5.1)"
    )

    # An aliased import (`from ... import AccountState as A`) hides the name from
    # the import scan, and a fully-qualified reference (`models.AccountState`)
    # never appears in it at all. The source scan catches both.
    executable = _executable_source(source)
    used = sorted(name for name in banned if name in executable)
    assert not used, (
        f"{module.__name__} references firm state {used} in executable code: a value "
        f"describing the firm's position, performance, or capacity must not reach a "
        f"path that decides what the evidence supports (A-2, §5.1)"
    )
