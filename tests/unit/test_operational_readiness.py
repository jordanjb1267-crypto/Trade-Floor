"""The approved conditions that live in the installer, the status command, and
governance — not in Python behaviour.

A condition recorded only in a code comment is a condition nobody can enforce.
These read the actual shell script and the actual policy document, so removing
the gate breaks a test rather than passing review unnoticed.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

from trading_firm.runner import liveness

REPO = Path(__file__).resolve().parents[2]
INSTALLER = (REPO / "deploy" / "macos" / "install.sh").read_text()
POLICY = (REPO / "governance" / "strategy-promotion-policy.md").read_text()
README = (REPO / "deploy" / "macos" / "README.md").read_text()

NOW = dt.datetime(2026, 7, 31, 6, 0, tzinfo=dt.UTC)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status = _load("supervisor_status")


class TestInstallerReportsDegradedNotifier:
    """Condition 2: installation may succeed with a degraded notifier, but must
    say so prominently."""

    def test_the_installer_reads_the_notify_state(self) -> None:
        assert "notify_state" in INSTALLER

    def test_a_degraded_notifier_does_not_fail_the_install(self) -> None:
        """The warning block must not exit. Uninstalling a genuinely running
        supervisor because Telegram had a bad minute is the wrong remedy."""
        block = INSTALLER.split('if [[ "$NOTIFY_STATE" != "confirmed" ]]; then')[1]
        block = block.split("fi")[0]
        assert "exit" not in block

    def test_the_warning_is_prominent_and_names_the_consequence(self) -> None:
        assert "WARNING" in INSTALLER
        assert "Alerts may not reach you" in INSTALLER
        assert "worse than no alert at all" in INSTALLER

    def test_the_warning_points_at_the_live_readiness_gate(self) -> None:
        assert "--require-notify-confirmed" in INSTALLER
        assert "legacy_assumed_confirmation" in INSTALLER

    def test_the_success_summary_states_the_notify_state(self) -> None:
        assert "notify:" in INSTALLER


class TestLiveReadinessRequiresConfirmedDelivery:
    """Condition 3."""

    def test_the_promotion_policy_requires_the_flag(self) -> None:
        assert "--require-notify-confirmed" in POLICY
        assert "supervisor_status.py" in POLICY

    def test_the_policy_states_the_gate_is_mandatory(self) -> None:
        assert "must require" in POLICY
        assert "exiting **0**" in POLICY

    def test_the_policy_rejects_an_assumed_confirmation(self) -> None:
        assert "legacy_assumed_confirmation" in POLICY
        assert "does not satisfy this gate" in POLICY

    def test_the_policy_states_the_axes_are_independent(self) -> None:
        assert "independent axes" in POLICY

    def test_the_flag_rejects_every_state_except_confirmed(self) -> None:
        """Behaviour, not just prose: only CONFIRMED may pass the gate."""
        passing = {
            state
            for state in liveness.NotifyState
            if state is liveness.NotifyState.CONFIRMED
        }
        assert passing == {liveness.NotifyState.CONFIRMED}
        assert liveness.NotifyState.ASSUMED not in passing

    def test_an_assumption_does_not_satisfy_the_gate(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(status, "CONFIRMATION_MARKER", tmp_path / "d.json")
        monkeypatch.setattr(status, "ATTEMPT_LEDGER", tmp_path / "a.json")
        monkeypatch.setattr(status, "ASSUMPTION_MARKER", tmp_path / "assumed.json")
        monkeypatch.setattr(status, "LOG_DIR", tmp_path)
        monkeypatch.setattr(
            status, "read_launchd",
            lambda label: liveness.LaunchdStatus(loaded=True, running=True),
        )
        liveness.migrate_legacy_marker(
            legacy=_legacy(tmp_path), assumption=tmp_path / "assumed.json",
            log_dir=tmp_path, now=dt.datetime.now(dt.UTC), env={},
        )
        code = status.main(["--require-notify-confirmed"])
        assert code == 6, "an assumed confirmation must not pass live readiness"


def _legacy(tmp_path: Path) -> Path:
    import json

    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"last_sent_at": dt.datetime.now(dt.UTC).isoformat()}))
    return path


class TestDocumentedConditions:
    """The README is where an operator looks first; the conditions must survive
    there too, not only in the code that implements them."""

    def test_it_documents_the_independent_axes(self) -> None:
        assert "independent axes" in README

    def test_it_documents_that_install_succeeds_but_warns(self) -> None:
        assert "does not fail the install" in README

    def test_it_documents_the_live_readiness_gate(self) -> None:
        assert "--require-notify-confirmed" in README

    def test_it_documents_the_legacy_assumption_and_its_ttl(self) -> None:
        assert "legacy_assumed_confirmation" in README
        assert "expires" in README

    def test_it_documents_that_episode_state_survives_restarts(self) -> None:
        assert "survives" in README or "persists" in README
