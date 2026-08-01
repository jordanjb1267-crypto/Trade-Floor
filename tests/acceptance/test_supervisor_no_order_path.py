"""§0 iron rule 1 / §12.1 for the supervisor: shadow mode cannot place orders.

Not a policy statement — a property of the import graph. The runner package
must not reach, directly or transitively, any module that can submit, modify,
or cancel an order. The composition script's read-only probe imports the
transport lazily inside a function, and that is the single, visible exception:
a GET of open positions, made where a reviewer can see it.
"""

import ast
import sys
from pathlib import Path

FORBIDDEN_MODULES = {
    "trading_firm.execution.adapter",  # order submission lives here
    "trading_firm.execution.fake",
}


def _imports(nodes) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _module_imports(path: Path) -> set[str]:
    """Every import anywhere in the file — lazy ones included."""
    return _imports(ast.walk(ast.parse(path.read_text())))


def _top_level_imports(path: Path) -> set[str]:
    """Imports that run at import time. The lazy/at-top distinction is the
    entire contract this test file enforces, so the two must not be conflated
    — the first version of this test did, and flagged the sanctioned lazy
    import as a violation."""
    return _imports(ast.parse(path.read_text()).body)


class TestRunnerPackageCannotReachTheOrderPath:
    def test_no_runner_module_imports_execution_at_all(self) -> None:
        runner = Path("src/trading_firm/runner")
        for module in runner.glob("*.py"):
            imports = _module_imports(module)
            execution = sorted(i for i in imports if "execution" in i)
            assert not execution, (
                f"{module.name} imports {execution}: the supervisor package must not "
                f"link the execution package — shadow mode never places orders "
                f"(§12.1, §0 iron rule 1)"
            )

    def test_importing_the_runner_does_not_load_the_order_path(self) -> None:
        """Deterministic under any test order: evict the runner, notify, and
        execution trees, import the supervisor fresh, and assert the ORDER
        path stayed unloaded.

        The first version asserted no execution module at all loads, and was
        order-dependent theatre: it passed in the full suite (everything
        already cached in sys.modules) and failed alone, because the notify
        transport legitimately imports execution.credentials — the shared §17
        preflight that PR #18 deliberately promoted for exactly this reuse.
        Credentials validation is not an order path. The adapter is.
        """
        for name in list(sys.modules):
            if name.startswith(("trading_firm.runner", "trading_firm.notify",
                                "trading_firm.execution")):
                del sys.modules[name]

        import trading_firm.runner.supervisor  # noqa: F401

        loaded = sorted(n for n in sys.modules if n in FORBIDDEN_MODULES)
        assert not loaded, (
            f"importing the runner loaded the order path {loaded}: shadow mode "
            f"must be unable to place an order by construction (§12.1, §0 rule 1)"
        )
        # And the read-only credential preflight IS expected to load — if this
        # starts failing, the notify transport stopped using the shared §17
        # vocabulary, which is its own regression.
        assert "trading_firm.execution.credentials" in sys.modules

    def test_the_composition_script_touches_only_the_transport(self) -> None:
        # The read-only probe is the one sanctioned exception, and it must not
        # widen: the adapter (order path) stays unreachable even from there.
        imports = _top_level_imports(Path("scripts/run_supervisor.py"))
        assert "trading_firm.execution.oanda_transport" not in imports, (
            "the transport import must stay INSIDE probe(), not at module level — "
            "lazy and visible is the contract"
        )
        forbidden = sorted(FORBIDDEN_MODULES & imports)
        assert not forbidden, f"run_supervisor.py imports the order path: {forbidden}"

        source = Path("scripts/run_supervisor.py").read_text()
        tree = ast.parse(source)
        lazy = {
            node.module
            for fn in ast.walk(tree)
            if isinstance(fn, ast.FunctionDef)
            for node in ast.walk(fn)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "trading_firm.execution.oanda_transport" in lazy, (
            "the probe's lazy transport import moved or vanished — if the probe "
            "no longer reads broker state, the §18 flat check is gone"
        )
