"""The launchctl adapter in `scripts/supervisor_status.py`.

The parser is tested against output captured from a real macOS Sequoia run —
both the healthy case and the crash-looping case this repository actually
produced. The shape of `launchctl print` is an OS detail that changes between
releases, and discovering that in production is how a status tool starts lying
about a trading system's state.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from trading_firm.runner.liveness import SupervisorState

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load("supervisor_status")

# Captured verbatim from a healthy run.
RUNNING = """\
gui/502/com.tradefloor.supervisor = {
	active count = 1
	path = /Users/x/Library/LaunchAgents/com.tradefloor.supervisor.plist
	type = LaunchAgent
	state = running

	program = /usr/bin/caffeinate

	runs = 1
	pid = 30859
	last exit code = (never exited)
}
"""

# Captured verbatim while the supervisor was dying on import every 60 seconds.
CRASHING = """\
gui/502/com.tradefloor.supervisor = {
	active count = 0
	path = /Users/x/Library/LaunchAgents/com.tradefloor.supervisor.plist
	type = LaunchAgent
	state = spawn scheduled

	runs = 2
	last exit code = 1
}
"""


class TestParseLaunchctl:
    def test_running_job(self) -> None:
        parsed = status.parse_launchctl(RUNNING, found=True)
        assert parsed.loaded and parsed.running
        assert parsed.pid == 30859
        assert parsed.runs == 1

    def test_never_exited_is_none_not_zero(self) -> None:
        """'(never exited)' must not parse as exit code 0 — that would make a
        healthy long-runner indistinguishable from a clean shutdown."""
        assert status.parse_launchctl(RUNNING, found=True).last_exit_code is None

    def test_crashing_job(self) -> None:
        parsed = status.parse_launchctl(CRASHING, found=True)
        assert parsed.loaded
        assert not parsed.running  # 'spawn scheduled' is not running
        assert parsed.last_exit_code == 1
        assert parsed.runs == 2

    def test_absent_job(self) -> None:
        parsed = status.parse_launchctl("Could not find service", found=False)
        assert not parsed.loaded
        assert not parsed.running

    def test_unknown_output_does_not_claim_running(self) -> None:
        """A parser that fails open would report a dead supervisor as healthy."""
        parsed = status.parse_launchctl("something entirely unexpected", found=True)
        assert parsed.loaded and not parsed.running


class TestExitCodes:
    def test_every_state_maps_to_a_distinct_exit_code(self) -> None:
        assert set(status.EXIT_BY_STATE) == set(SupervisorState)
        codes = list(status.EXIT_BY_STATE.values())
        assert len(set(codes)) == len(codes)

    def test_only_healthy_exits_zero(self) -> None:
        for state, code in status.EXIT_BY_STATE.items():
            assert (code == 0) == (state is SupervisorState.HEALTHY)
