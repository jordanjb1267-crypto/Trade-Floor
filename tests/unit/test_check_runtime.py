"""`scripts/check_runtime.py` — the interpreter and TLS gate.

The script duplicates the practice host rather than importing it, so that it
still runs when the package import is the thing that is broken. That trade is
only safe if the duplicate cannot drift, which is what this file enforces.

No test here opens a socket: `check_tls()` is exercised through injected
failures, not against the real host.
"""

from __future__ import annotations

import importlib.util
import socket
import ssl
from pathlib import Path

from trading_firm.execution.oanda_transport import PRACTICE_HOST

REPO = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = _load("check_runtime")


class TestHostDoesNotDrift:
    def test_the_duplicated_host_still_matches_the_package(self) -> None:
        assert PRACTICE_HOST == f"https://{runtime.PRACTICE_TLS_HOST}"

    def test_it_is_the_practice_host_not_the_live_one(self) -> None:
        """§13/D-1: the live host never appears outside the broker adapter."""
        assert "fxpractice" in runtime.PRACTICE_TLS_HOST
        assert runtime.PRACTICE_TLS_HOST != "api-fxtrade.oanda.com"


class TestPythonFloor:
    def test_the_floor_matches_the_project_requirement(self) -> None:
        pyproject = (REPO / "pyproject.toml").read_text()
        wanted = ".".join(str(part) for part in runtime.MIN_PYTHON)
        assert f'requires-python = ">={wanted}"' in pyproject

    def test_the_running_interpreter_passes(self) -> None:
        ok, summary, _ = runtime.check_python()
        assert ok
        assert "Python" in summary


class TestTlsFailuresAreDiagnosedNotMisattributed:
    def _with_connection(self, monkeypatch, error: Exception):
        def boom(*args, **kwargs):
            raise error

        monkeypatch.setattr(runtime.socket, "create_connection", boom)

    def test_certificate_failure_prints_the_manual_repair(self, monkeypatch) -> None:
        self._with_connection(monkeypatch, ssl.SSLError("CERTIFICATE_VERIFY_FAILED"))
        ok, summary, remedy = runtime.check_tls()
        assert not ok
        assert "certifi" in remedy
        # The remediation must be instructions, never something the installer
        # silently performs on a system trust store.
        assert "will not do this for you" in remedy

    def test_a_network_failure_is_not_blamed_on_credentials(self, monkeypatch) -> None:
        """The exact misdiagnosis that already happened once here: an egress
        denial reported as a credential problem sends the operator to rotate a
        perfectly good token."""
        self._with_connection(monkeypatch, socket.gaierror("nodename nor servname"))
        ok, _, remedy = runtime.check_tls()
        assert not ok
        assert "NETWORK result, not a credential" in remedy
        assert "certifi" not in remedy

    def test_failures_report_nonzero(self, monkeypatch) -> None:
        self._with_connection(monkeypatch, ssl.SSLError("boom"))
        assert runtime.main() == 1
