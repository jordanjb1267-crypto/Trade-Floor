"""§30.2 / §0 iron rule 1 for the surveillance division: it cannot reach an
order path. A property of the import graph, mirroring the runner-package
guard — the glob auto-covers every surveillance module, present and future,
so a new file is in scope the moment it exists."""

import ast
import importlib
import sys
from pathlib import Path

SURVEILLANCE = Path("src/trading_firm/surveillance")

FORBIDDEN_MODULES = {
    "trading_firm.execution.adapter",
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


class TestSurveillanceCannotReachTheOrderPath:
    def test_no_surveillance_module_imports_execution_at_all(self) -> None:
        modules = sorted(SURVEILLANCE.glob("**/*.py"))
        assert len(modules) >= 25, "glob must actually cover the package"
        for module in modules:
            imports = _imports(ast.walk(ast.parse(module.read_text())))
            execution = sorted(i for i in imports if "execution" in i)
            assert not execution, (
                f"{module} imports {execution}: the division observes, classifies, "
                f"interprets, and escalates — it may not place orders, alter stops, "
                f"size positions, or bypass the candidate and risk workflow "
                f"(§30.1 rule 6, §30.2, §0 iron rule 1)"
            )

    def test_importing_the_division_does_not_load_the_order_path(self) -> None:
        """Evict and reimport fresh, then assert the order modules stayed
        unloaded — the same deterministic contract as the runner guard."""
        for name in sorted(sys.modules):
            if name.startswith(("trading_firm.surveillance", "trading_firm.execution")):
                del sys.modules[name]
        for module_path in sorted(SURVEILLANCE.glob("**/*.py")):
            relative = module_path.relative_to(Path("src")).with_suffix("")
            importlib.import_module(".".join(relative.parts))
        loaded = sorted(set(sys.modules) & FORBIDDEN_MODULES)
        assert not loaded, f"importing surveillance loaded the order path: {loaded}"


class TestOneConfigDisable:
    def test_a_disabled_coordinator_is_a_no_op(self) -> None:
        """§30.17 acceptance: one command or config change disables the
        entire new division. The master switch dominates even a wired
        coordinator."""
        import datetime as dt

        from trading_firm.runner.schedule import ScheduledEvent, SessionEvent
        from trading_firm.surveillance.config import (
            BASE_SURVEILLANCE_CONFIG_PATH,
            load_surveillance_config,
        )
        from trading_firm.surveillance.coordinator import Coordinator

        calls = {"build": 0, "record": 0, "notify": 0}

        def build(scheduled, prior):
            calls["build"] += 1
            return None

        coordinator = Coordinator(
            config=load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH),
            build_state=build,
            record_event=lambda e: calls.__setitem__("record", calls["record"] + 1),
            notify=lambda kind, body: calls.__setitem__("notify", calls["notify"] + 1) or True,
            now=lambda: dt.datetime(2026, 7, 29, 8, 0, tzinfo=dt.UTC),
            configuration_version="test",
        )
        scheduled = ScheduledEvent(
            event=SessionEvent.BRIEFING,
            at=dt.datetime(2026, 7, 29, 7, 30, tzinfo=dt.UTC),
            session_date=dt.date(2026, 7, 29),
        )
        result = coordinator.run(scheduled)
        assert result.market_state_id is None
        assert calls == {"build": 0, "record": 0, "notify": 0}, (
            "enabled: false must short-circuit before any work at all (§30.12)"
        )
