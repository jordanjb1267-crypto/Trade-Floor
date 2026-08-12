"""The production composition actually wires the §31 control plane.

The defect class this closes is production composition drift: three ratified
controls — the §31.7 operational epoch, the §31.5 suspension detector, and the
§31.5 power verifier — each existed, each passed its unit tests under direct
injection, and NONE was passed by the production composition. Nothing failed,
because a constructor default absorbed each omission: `epoch=None` read as a
fresh install (restart recovery inert), `suspension=None` read as
nothing-to-sample, and `power_verified=True` read as a verification nobody ran.
The epoch wiring was even believed shipped — the A-5 edit targeted a stale
constructor anchor and silently missed.

So every test here goes through THE production builder,
`build_supervisor()` in scripts/run_supervisor.py — never a test-local
`Supervisor(...)` clone. The manifest tests pin the builder's wiring statically
(over the script's AST, so an omitted, renamed, or defaulted keyword fails even
if some runtime path would absorb it); the behavioral tests prove each control
does its governed §31 work when composed exactly as production composes it. A
test that assembles its own Supervisor with the right keywords proves the
Supervisor works; only these prove the production process uses it.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import inspect
import json
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.notify.surface import NotificationKind
from trading_firm.runner import power
from trading_firm.runner.power import PowerSource, PowerState, SuspensionDetector
from trading_firm.runner.schedule import next_event
from trading_firm.runner.supervisor import HealthReport, SessionRecord, Supervisor
from trading_firm.runner.timing import FlatState
from trading_firm.sessions import SessionClock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "run_supervisor.py"
LONDON = ZoneInfo("Europe/London")

# The firm's real operational baseline shape: database initialised 2026-08-01
# (a Saturday), so the first expected trading date is Monday 2026-08-03.
EPOCH_APPLIED_AT = "2026-08-01T06:16:59Z"
EPOCH_DATE = dt.date(2026, 8, 1)
WEEK1 = [dt.date(2026, 8, d) for d in (3, 4, 5, 6)]  # Mon..Thu, reports exist
FRI = dt.date(2026, 8, 7)  # fully missed: suspended through every boundary
MON = dt.date(2026, 8, 10)  # the restart session

# Every Supervisor input the production composition is contractually required
# to wire explicitly (§31.6 owner requirement 8 generalised: absence of
# evidence is not evidence of control). The three recovered controls are here
# BECAUSE their omission was silent; the rest are here so a new constructor
# parameter cannot be added without a deliberate manifest decision.
CONTRACTED = {
    "clock", "probe", "notify", "report_dir", "now", "sleep",
    "heartbeat", "sweep", "epoch", "suspension", "power_check",
}


def _load_runner():
    spec = importlib.util.spec_from_file_location(
        "run_supervisor_composition_under_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


def at(day: dt.date, hour: int, minute: int, second: float = 0) -> dt.datetime:
    whole = int(second)
    micro = int(round((second - whole) * 1_000_000))
    return dt.datetime.combine(
        day, dt.time(hour, minute, whole, micro), tzinfo=LONDON
    )


def healthy() -> HealthReport:
    return HealthReport(broker_reachable=True, account_flat=True, open_position_count=0)


def init_firm_db(path: Path, applied_at: str = EPOCH_APPLIED_AT) -> Path:
    """A database with the real migration-ledger shape (audit/db.py DDL)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_migrations ("
        "  name TEXT PRIMARY KEY,"
        "  applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))"
        ")"
    )
    conn.execute(
        "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)",
        ("0001_init.sql", applied_at),
    )
    conn.commit()
    conn.close()
    return path


def ready_state() -> PowerState:
    return PowerState(
        source=PowerSource.AC,
        prevent_system_sleep=True,
        prevent_idle_sleep=True,
        recent_sleep_events=0,
    )


def battery_state() -> PowerState:
    return PowerState(
        source=PowerSource.BATTERY,
        prevent_system_sleep=True,
        prevent_idle_sleep=True,
        recent_sleep_events=0,
    )


class Composer:
    """Drives the supervisor THE PRODUCTION BUILDER produces.

    Only the side-effect seams the builder itself exposes are substituted
    (probe, notifier, report dir, clock, sleep, heartbeat); the three §31
    controls come from the builder unconditionally — that is the point.
    """

    def __init__(self, clock, tmp_path, monkeypatch, probe=healthy, start=None):
        self.sent: list[tuple[object, str]] = []
        self.moment = start or at(MON, 6, 0)
        self.clock = clock
        self.report_dir = tmp_path / "reports"
        # For run_forever tests: the first sleep slice stops the loop, so one
        # iteration of the real production loop runs and then returns.
        self.stop_on_first_sleep = False
        tmp_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(runner, "DB_PATH", init_firm_db(tmp_path / "firm.sqlite"))
        self.supervisor = runner.build_supervisor(
            clock,
            notify_fn=lambda kind, body: (self.sent.append((kind, body)), True)[1],
            report_dir=self.report_dir,
            now=lambda: self.moment,
            sleep=self._sleep,
            heartbeat=lambda phase: None,
            probe_fn=probe,
        )

    def _sleep(self, seconds: float) -> None:
        if self.stop_on_first_sleep:
            self.supervisor.stopping = True

    def run_events(self, count: int) -> None:
        for _ in range(count):
            scheduled = next_event(self.clock, self.moment)
            self.moment = scheduled.at + dt.timedelta(seconds=1)
            self.supervisor.handle(scheduled)

    def reports(self) -> dict[str, dict]:
        return {
            p.name: json.loads(p.read_text())
            for p in sorted(self.report_dir.glob("*-session.json"))
        }

    def report(self, day: dt.date) -> dict:
        return json.loads((self.report_dir / f"{day}-session.json").read_text())


@pytest.fixture
def ready_power(monkeypatch):
    """§31.5 machine-observable requirements all verifiable and green."""
    monkeypatch.setattr(power, "read_power_state", lambda: ready_state())


class LoopRig:
    """Drives the REAL `run_forever` for one whole session under simulated
    clocks, with a machine suspension injectable into a chosen sleep slice.

    `Composer` calls `handle()` directly, which is right for boundary
    behaviour but structurally cannot exercise the loop's own sequencing. This
    rig exists for the parts of §31.5/§31.6 that live in the loop: the sleep
    slices and the wake sample that follows them.

    The detector the production builder constructs reads `time.time` and
    `time.monotonic` from `runner.power`, so patching that module's `time`
    BEFORE the build gives the real, unmodified detector simulated clocks —
    the wiring under test stays production, only the clocks are ours.
    """

    def __init__(self, clock, tmp_path, monkeypatch, *, gap_seconds=60.0,
                 arm_after="entry_cutoff"):
        self.clock = clock
        self.gap_seconds = gap_seconds
        self.arm_after = arm_after
        self.armed = False
        self.injected = False
        self.sent: list[tuple[object, str]] = []

        self.moment = at(MON, 6, 0)
        self.wall = self.moment.timestamp()
        self.mono = 10_000.0

        rig = self

        class FakeTime:
            @staticmethod
            def time() -> float:
                return rig.wall

            @staticmethod
            def monotonic() -> float:
                return rig.mono

        monkeypatch.setattr(power, "time", FakeTime)
        tmp_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(runner, "DB_PATH", init_firm_db(tmp_path / "firm.sqlite"))
        self.report_dir = tmp_path / "reports"
        self.report_dir.mkdir(parents=True)
        day = dt.date(2026, 8, 2)
        while day < MON:  # every earlier expected date already terminal
            if day.weekday() in (0, 1, 2, 3, 4):
                (self.report_dir / f"{day}-session.json").write_text("{}")
            day += dt.timedelta(days=1)

        self.supervisor = runner.build_supervisor(
            clock,
            notify_fn=self._notify,
            report_dir=self.report_dir,
            now=lambda: self.moment,
            sleep=self._sleep,
            heartbeat=lambda phase: None,
            probe_fn=healthy,
        )
        self._wrap_handle()

    def _notify(self, kind, body) -> bool:
        self.sent.append((kind, body))
        if "daily_session_report" in str(kind):
            self.supervisor.stopping = True  # exactly one session, then stop
        return True

    def _wrap_handle(self) -> None:
        inner = self.supervisor.handle

        def handle(scheduled):
            inner(scheduled)
            if scheduled.event.value == self.arm_after:
                self.armed = True

        self.supervisor.handle = handle

    def _sleep(self, seconds: float) -> None:
        self.moment += dt.timedelta(seconds=seconds)
        self.wall += seconds
        self.mono += seconds
        if self.armed and not self.injected:
            # The machine slept: wall-clock time advanced that the monotonic
            # clock never saw. This is the definition of a suspension, and the
            # only moment it can be observed is the wake that follows.
            self.injected = True
            self.moment += dt.timedelta(seconds=self.gap_seconds)
            self.wall += self.gap_seconds

    def run_one_session(self) -> None:
        self.supervisor.run_forever()
        assert self.injected, "the rig never injected a suspension"

    def report(self, day: dt.date) -> dict:
        return json.loads((self.report_dir / f"{day}-session.json").read_text())


# --------------------------------------------------------------------------
# The wiring manifest: the production composition contract, pinned statically.
# --------------------------------------------------------------------------


def _script_tree() -> ast.Module:
    return ast.parse(SCRIPT.read_text())


def _supervisor_bindings(tree: ast.Module) -> set[str]:
    """Every local name in this module that refers to the Supervisor class.

    Matching the literal string "Supervisor" is not enough. `from ...supervisor
    import Supervisor as _S` binds the same class to a different name, and a
    Name-only matcher never sees `_S(...)` — which made the whole "exactly one
    composition site" invariant bypassable: main() could call build_supervisor()
    correctly, satisfying every assertion here, then reassign to an alias-built
    Supervisor with all three §31 controls inert, with the suite fully green.

    Resolved to a fixed point so a chain (`_S = Supervisor; _T = _S`) cannot
    launder the name either.
    """
    bound = {"Supervisor"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "Supervisor":
                    bound.add(alias.asname or alias.name)
    while True:
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            refers = (
                (isinstance(value, ast.Name) and value.id in bound)
                or (isinstance(value, ast.Attribute) and value.attr == "Supervisor")
            )
            if not refers:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in bound:
                    bound.add(target.id)
                    grew = True
        if not grew:
            return bound


def _constructs_supervisor(node: ast.Call, bound: set[str]) -> bool:
    """Match every construction form: the imported name, any alias bound to it,
    and any attribute-qualified `module.Supervisor(...)`."""
    func = node.func
    if isinstance(func, ast.Name) and func.id in bound:
        return True
    return isinstance(func, ast.Attribute) and func.attr == "Supervisor"


def _supervisor_calls(tree: ast.AST, bound: set[str] | None = None) -> list[ast.Call]:
    if bound is None:
        bound = _supervisor_bindings(_script_tree())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _constructs_supervisor(node, bound)
    ]


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"scripts/run_supervisor.py has no function {name}()")


class TestCompositionWiringManifest:
    def test_the_script_assembles_exactly_one_supervisor(self) -> None:
        """No second composition site: a test-only clone or a duplicate
        assembly is where a silently-missed edit hides."""
        tree = _script_tree()
        calls = _supervisor_calls(tree)
        assert len(calls) == 1, (
            f"expected exactly one Supervisor(...) assembly in the production "
            f"script, found {len(calls)} — every composition must go through "
            f"build_supervisor()"
        )
        builder = _function(tree, "build_supervisor")
        assert _supervisor_calls(builder), (
            "the single Supervisor(...) assembly must live inside build_supervisor()"
        )

    def test_main_composes_through_the_exact_builder(self) -> None:
        main = _function(_script_tree(), "main")
        assert not _supervisor_calls(main), (
            "main() must not assemble a Supervisor directly — that duplicate "
            "path is how the epoch wiring was silently lost"
        )
        called = {
            node.func.id
            for node in ast.walk(main)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "build_supervisor" in called, "main() must call build_supervisor()"

    def test_every_contracted_dependency_is_wired_by_keyword(self) -> None:
        call = _supervisor_calls(_function(_script_tree(), "build_supervisor"))[0]
        assert not call.args, "contracted dependencies are wired by KEYWORD only"
        keywords = {kw.arg for kw in call.keywords}
        assert None not in keywords, "no **kwargs: the wiring must be explicit"
        missing = CONTRACTED - keywords
        extra = keywords - CONTRACTED
        assert not missing, (
            f"contracted dependency NOT wired by the production builder: "
            f"{sorted(missing)} — this is exactly the A-5 silent-omission defect"
        )
        assert not extra, (
            f"builder wires {sorted(extra)} which the manifest does not list — "
            f"add it to CONTRACTED deliberately, not by accident"
        )

    def test_the_manifest_covers_the_whole_constructor(self) -> None:
        """A new Supervisor parameter must force a manifest decision here,
        not acquire a silent default in production."""
        params = set(inspect.signature(Supervisor.__init__).parameters) - {"self"}
        assert params == CONTRACTED, (
            f"Supervisor.__init__ and the composition manifest disagree "
            f"({sorted(params.symmetric_difference(CONTRACTED))}): update the "
            f"builder AND this manifest together, deliberately"
        )

    def test_the_recovered_controls_cannot_fall_back_unsafely(self) -> None:
        """`epoch=None`, a fresh detector nobody built, or a power check that
        is not the ratified verifier would satisfy a keyword-presence test and
        still be inert. Pin the wired VALUES."""
        call = _supervisor_calls(_function(_script_tree(), "build_supervisor"))[0]
        wired = {kw.arg: kw.value for kw in call.keywords}

        epoch = wired["epoch"]
        assert (
            isinstance(epoch, ast.Call)
            and isinstance(epoch.func, ast.Name)
            and epoch.func.id == "operational_epoch"
        ), "epoch must be wired from operational_epoch(), the durable DB baseline"

        suspension = wired["suspension"]
        assert (
            isinstance(suspension, ast.Call)
            and isinstance(suspension.func, ast.Name)
            and suspension.func.id == "SuspensionDetector"
        ), "suspension must be the ratified runner.power.SuspensionDetector"

        check = wired["power_check"]
        assert isinstance(check, ast.Name) and check.id == "power_readiness_check", (
            "power_check must be the §31.5 verifier, power_readiness_check"
        )

    def test_the_builder_offers_no_override_for_the_controls(self) -> None:
        """The three recovered controls are wired unconditionally: no caller —
        test or production — can pass a substitute through the builder."""
        params = set(inspect.signature(runner.build_supervisor).parameters)
        forbidden = params & {"epoch", "suspension", "power_check"}
        assert not forbidden, (
            f"build_supervisor exposes {sorted(forbidden)} as parameters — the "
            f"contracted controls must not be overridable at composition"
        )

    def test_the_built_supervisor_actually_received_the_controls(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Constructed-but-never-passed is the failure mode; assert arrival."""
        composer = Composer(clock, tmp_path, monkeypatch)
        sup = composer.supervisor
        assert sup._epoch == EPOCH_DATE, "epoch did not arrive from the database"
        assert isinstance(sup._suspension, SuspensionDetector)
        assert sup._power_check is runner.power_readiness_check

    def test_the_script_never_nulls_a_control_after_construction(self) -> None:
        """M-D. The AST cannot prove the absence of post-construction mutation
        in general — an attribute write through any alias, in any module, is
        not statically decidable. What it CAN do is close the realistic drift:
        a write to a contracted control on any object in the composition
        script itself. Stated narrowly on purpose; the runtime-arrival test
        above is the backstop for the end state, and neither is a general
        guarantee."""
        contracted = {"_epoch", "_suspension", "_power_check"}
        for node in ast.walk(_script_tree()):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in contracted:
                    raise AssertionError(
                        f"scripts/run_supervisor.py assigns {target.attr} after "
                        f"construction (line {target.lineno}) — a contracted "
                        f"control must not be replaced or nulled post-build"
                    )


def _calls_in(source: str) -> list[ast.Call]:
    """Run the manifest's real matcher over synthetic composition source."""
    tree = ast.parse(source)
    return _supervisor_calls(tree, _supervisor_bindings(tree))


class TestManifestCannotBeBypassed:
    """M-A..M-D: the manifest is the primary defense against another silent
    A-5-style omission, so its matcher is itself adversarially tested. Each
    case is a composition form a future editor could plausibly write; every
    one must be seen as a Supervisor assembly."""

    PROLOGUE = "from trading_firm.runner.supervisor import Supervisor\n"

    def test_m_a_alias_import_is_detected(self) -> None:
        source = (
            "from trading_firm.runner.supervisor import Supervisor as _S\n"
            "def build():\n"
            "    return _S(clock=c, probe=p, notify=n)\n"
        )
        assert len(_calls_in(source)) == 1, (
            "an aliased Supervisor import evaded the matcher — this is the "
            "bypass that let main() build correctly and then reassign to an "
            "alias-built Supervisor with every §31 control inert"
        )

    def test_m_b_attribute_qualified_assembly_is_detected(self) -> None:
        source = (
            "from trading_firm.runner import supervisor as sup\n"
            "def build():\n"
            "    return sup.Supervisor(clock=c, probe=p, notify=n)\n"
        )
        assert len(_calls_in(source)) == 1

    def test_m_c_correct_build_plus_an_aliased_second_assembly_is_detected(
        self,
    ) -> None:
        """The realistic shape: the manifest-satisfying builder is left intact
        and a second, inert assembly is added beside it."""
        source = (
            self.PROLOGUE
            + "from trading_firm.runner.supervisor import Supervisor as _S\n"
            "def build_supervisor():\n"
            "    return Supervisor(clock=c, probe=p, notify=n, epoch=e,\n"
            "                      suspension=s, power_check=pc)\n"
            "def main():\n"
            "    supervisor = build_supervisor()\n"
            "    supervisor = _S(clock=c, probe=p, notify=n)\n"
        )
        calls = _calls_in(source)
        assert len(calls) == 2, (
            f"expected both assemblies, saw {len(calls)} — the 'exactly one "
            f"Supervisor assembly' invariant would not have failed"
        )

    def test_a_rebinding_chain_cannot_launder_the_name(self) -> None:
        source = (
            self.PROLOGUE
            + "_S = Supervisor\n"
            "_T = _S\n"
            "def build():\n"
            "    return _T(clock=c, probe=p, notify=n)\n"
        )
        assert len(_calls_in(source)) == 1

    def test_the_real_script_still_has_exactly_one_assembly(self) -> None:
        """The matcher is now strictly more sensitive; production must still
        present exactly one site under it."""
        tree = _script_tree()
        bound = _supervisor_bindings(tree)
        assert bound == {"Supervisor"}, (
            f"the composition script binds Supervisor to {sorted(bound)} — "
            f"extra bindings are exactly how a second assembly hides"
        )
        assert len(_supervisor_calls(tree, bound)) == 1


# --------------------------------------------------------------------------
# §31.7 operational epoch, behaviorally, through the production builder.
# --------------------------------------------------------------------------


class TestEpochWiring:
    def test_database_initialization_establishes_the_epoch(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        composer = Composer(clock, tmp_path, monkeypatch)
        assert composer.supervisor._epoch == EPOCH_DATE

    def test_process_start_is_not_the_epoch(self, clock, tmp_path, monkeypatch) -> None:
        """The process 'starts' on 2026-08-10; the epoch must remain the
        database baseline, nine days earlier."""
        composer = Composer(clock, tmp_path, monkeypatch, start=at(MON, 6, 0))
        assert composer.supervisor._epoch == EPOCH_DATE != composer.moment.date()

    def test_restart_does_not_reset_the_epoch(self, clock, tmp_path, monkeypatch) -> None:
        first = Composer(clock, tmp_path, monkeypatch)
        second = Composer(clock, tmp_path / "restart", monkeypatch)
        assert first.supervisor._epoch == second.supervisor._epoch == EPOCH_DATE

    def test_missing_database_is_the_only_fresh_install(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(runner, "DB_PATH", tmp_path / "does-not-exist.sqlite")
        sup = runner.build_supervisor(
            clock,
            notify_fn=lambda kind, body: True,
            report_dir=tmp_path / "reports",
            now=lambda: at(MON, 6, 0),
            sleep=lambda seconds: None,
            heartbeat=lambda phase: None,
            probe_fn=healthy,
        )
        assert sup._epoch is None
        assert sup.attestation_backlog(MON) == [], (
            "a genuinely uninitialized deployment attests nothing (§31.7)"
        )

    def test_a_corrupt_database_refuses_composition(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """A database that EXISTS but cannot yield its baseline must fail
        LOUDLY. epoch=None here would empty the §31.7 backlog silently —
        an evidence gap masquerading as a fresh install, the exact fail-open
        this remediation closes."""
        bad = tmp_path / "firm.sqlite"
        bad.write_bytes(b"this is not a sqlite database")
        monkeypatch.setattr(runner, "DB_PATH", bad)
        with pytest.raises(RuntimeError, match="operational baseline unreadable"):
            runner.build_supervisor(
                clock,
                notify_fn=lambda kind, body: True,
                report_dir=tmp_path / "reports",
                now=lambda: at(MON, 6, 0),
                sleep=lambda seconds: None,
                heartbeat=lambda phase: None,
                probe_fn=healthy,
            )

    def test_an_empty_migration_ledger_refuses_composition(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        db = tmp_path / "firm.sqlite"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()
        monkeypatch.setattr(runner, "DB_PATH", db)
        with pytest.raises(RuntimeError, match="operational baseline unreadable"):
            runner.build_supervisor(
                clock,
                notify_fn=lambda kind, body: True,
                report_dir=tmp_path / "reports",
                now=lambda: at(MON, 6, 0),
                sleep=lambda seconds: None,
                heartbeat=lambda phase: None,
                probe_fn=healthy,
            )

    def test_an_unparsable_baseline_timestamp_refuses_composition(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        db = init_firm_db(tmp_path / "firm.sqlite", applied_at="not-a-timestamp")
        monkeypatch.setattr(runner, "DB_PATH", db)
        with pytest.raises(RuntimeError, match="operational baseline unreadable"):
            runner.build_supervisor(
                clock,
                notify_fn=lambda kind, body: True,
                report_dir=tmp_path / "reports",
                now=lambda: at(MON, 6, 0),
                sleep=lambda seconds: None,
                heartbeat=lambda phase: None,
                probe_fn=healthy,
            )

    def test_report_deletion_does_not_reset_the_epoch(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """An emptied report directory is an evidence gap to recover — the
        deleted date reappears in the backlog instead of vanishing."""
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.report_dir.mkdir(parents=True)
        for day in [*WEEK1, FRI]:
            (composer.report_dir / f"{day}-session.json").write_text("{}")
        assert composer.supervisor.attestation_backlog(MON) == []
        (composer.report_dir / f"{WEEK1[2]}-session.json").unlink()
        assert composer.supervisor.attestation_backlog(MON) == [WEEK1[2]]

    def test_a_missing_report_directory_is_not_a_fresh_install(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        composer = Composer(clock, tmp_path, monkeypatch)  # report_dir never created
        assert composer.supervisor.attestation_backlog(MON) == [*WEEK1, FRI], (
            "every expected date since the epoch is an evidence gap to recover, "
            "never proof of a fresh install (§31.7)"
        )

    def test_a_fully_missed_session_is_attested_after_restart(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """THE production reproduction: epoch Aug 1, reports Mon-Thu, Friday
        fully missed, process restarts Monday. The restarted composition must
        detect Friday and write its MISSED/NON_QUALIFYING attestation — with
        the unwired epoch this backlog was [] and Friday vanished silently."""
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.report_dir.mkdir(parents=True)
        for day in WEEK1:
            (composer.report_dir / f"{day}-session.json").write_text("{}")

        assert composer.supervisor.attestation_backlog(MON) == [FRI]
        composer.run_events(1)  # Monday pre_startup settles the backlog first

        friday = composer.report(FRI)
        assert friday["qualifying"] is False
        assert friday["degraded"] is True
        assert any("SESSION WINDOW MISSED" in r for r in friday["reasons"])
        assert any("power/sleep readiness not verified" in r for r in friday["reasons"]), (
            "a missed session cannot claim verified power readiness"
        )
        assert composer.supervisor.attestation_backlog(MON) == [], "backlog settled"
        # Saturday and Sunday are never expected, never attested (§31.7).
        attested = set(composer.reports())
        assert f"{dt.date(2026, 8, 8)}-session.json" not in attested
        assert f"{dt.date(2026, 8, 9)}-session.json" not in attested

    def test_attestation_is_idempotent_across_another_restart(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.report_dir.mkdir(parents=True)
        for day in WEEK1:
            (composer.report_dir / f"{day}-session.json").write_text("{}")
        composer.run_events(1)
        friday_first = composer.report(FRI)

        restarted = Composer(clock, tmp_path / "again", monkeypatch)
        restarted.report_dir = composer.report_dir  # same durable report state
        restarted.supervisor._report_dir = composer.report_dir
        restarted.run_events(1)
        assert composer.report(FRI) == friday_first, (
            "the report file is the durable idempotency guard — a restart may "
            "never duplicate or rewrite an attestation (§31.7)"
        )


# --------------------------------------------------------------------------
# §31.5 suspension detection, behaviorally, through the production builder.
# --------------------------------------------------------------------------


class TestSuspensionWiring:
    def test_the_builder_wires_an_operational_detector(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        composer = Composer(clock, tmp_path, monkeypatch)
        detector = composer.supervisor._suspension
        assert isinstance(detector, SuspensionDetector)
        assert detector.sample() is None, "a freshly wired detector samples cleanly"

    def test_a_detected_suspension_degrades_the_session(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """Governed §31.5 consequence through the wired detector: the session
        is degraded and non-qualifying, and the report says why."""
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(1)  # Monday pre_startup opens the session record

        # The machine sleeps: wall-clock time the monotonic clock never saw.
        # Simulated on the REAL wired detector by rewinding its wall anchor —
        # the next sample sees an hour of wall progress with no monotonic
        # progress, exactly the signature of a suspension.
        composer.supervisor._suspension._last_wall -= 3600.0
        composer.supervisor._sample_suspension()  # the run_forever wake sample

        composer.run_events(4)  # the rest of the Monday boundaries
        report = composer.report(MON)
        assert report["suspension_detected"] is True
        assert report["degraded"] is True
        assert report["qualifying"] is False
        assert any("runtime suspension detected" in r for r in report["reasons"])

    def test_the_loop_itself_samples_the_wired_detector(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """run_forever must consult the detector — a detector wired but never
        sampled is inert exactly like an unwired one. BEHAVIORAL on purpose: a
        source-text count survives the calls being commented out, because the
        name still appears in the comment (§31.3's own warning, applied to
        test code)."""
        composer = Composer(clock, tmp_path, monkeypatch)
        sup = composer.supervisor
        # A pre-session suspension the loop's own sampling must observe.
        sup._suspension._last_wall -= 3600.0
        composer.stop_on_first_sleep = True
        assert sup._pending_suspension is False
        sup.run_forever()
        assert sup._pending_suspension is True, (
            "run_forever never sampled the wired detector: the loop is where "
            "sampling happens in production, and it must be provably live"
        )

    def test_the_wake_sample_after_a_sleep_slice_catches_an_in_session_gap(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """§31.5's during-session detection, through the REAL run_forever.

        This is the one place the wake sample can be proven. `run_forever`
        samples twice: once at the top of the outer loop, once after each sleep
        slice. Only the second can observe a machine that slept BETWEEN
        boundaries, because the top-of-loop sample next runs after the current
        boundary's handler has already written its record. Asserting merely
        that "some sample occurred" is satisfied by either site and pins
        neither: deleting the wake sample alone left the whole suite green
        while a 60-second in-session suspension reported NOMINAL/QUALIFYING.

        So this drives the production loop end to end with the machine asleep
        for 60 s between entry_cutoff and flatten — long enough to exceed the
        30 s detector threshold, short enough to breach no boundary, so the
        suspension is the ONLY thing that can degrade the session.
        """
        rig = LoopRig(clock, tmp_path, monkeypatch, gap_seconds=60.0)
        rig.run_one_session()

        report = rig.report(MON)
        assert report["suspension_detected"] is True, (
            "the post-sleep wake sample never ran: a machine that slept "
            "mid-session was recorded as having run cleanly (§31.5)"
        )
        assert report["degraded"] is True
        assert report["qualifying"] is False
        assert any("runtime suspension detected" in r for r in report["reasons"])
        # §31.5: expired boundaries are never replayed as though timely — each
        # required boundary is handled exactly once, on its own evidence.
        handled = [e["event"] for e in report["events"] if "scheduled_at" in e]
        assert len(handled) == len(set(handled)) == 5

    def test_boundary_lateness_stays_independent_of_the_detector(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """A late boundary is classified late on its own timing evidence even
        when the detector saw nothing (§31.5: lateness is not a substitute,
        and neither replaces the other)."""
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(4)  # through entry_cutoff, all on time
        scheduled = next_event(composer.clock, composer.moment)
        # 30 s late: past the 5 s hard tolerance (breach), still inside the
        # §31.2 verification window so flat state verifies and the LATENESS is
        # what degrades the session — the dimension under test.
        composer.moment = scheduled.at + dt.timedelta(seconds=30)
        composer.supervisor.handle(scheduled)
        report = composer.report(MON)
        assert report["suspension_detected"] is False
        assert report["degraded"] is True
        assert any("HARD BOUNDARY BREACH" in r for r in report["reasons"])


# --------------------------------------------------------------------------
# §31.5 power gate, behaviorally, through the production builder.
# --------------------------------------------------------------------------


class TestPowerGateWiring:
    def test_a_ready_machine_verifies_and_qualifies(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(5)
        report = composer.report(MON)
        assert report["qualifying"] is True
        assert report["session_health"] == "NOMINAL"
        pre = report["events"][0]
        assert pre["event"] == "pre_startup"
        assert "power readiness verified" in pre["outcome"]

    def test_verification_is_executed_not_assumed(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """power_verified may only come from a verifier that actually RAN."""
        calls = {"n": 0}

        def counting_read_power_state():
            calls["n"] += 1
            return ready_state()

        monkeypatch.setattr(power, "read_power_state", counting_read_power_state)
        composer = Composer(clock, tmp_path, monkeypatch)
        assert calls["n"] == 0, "building the supervisor must not claim a check ran"
        composer.run_events(1)  # pre_startup
        assert calls["n"] == 1, (
            "the §31.5 verifier must execute at pre-startup — a session that "
            "reports power_verified without this call is asserting an unrun check"
        )
        record = composer.supervisor._record
        assert record is not None and record.power_verified is True

    def test_battery_fails_qualification_closed_without_degrading_execution(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """§31.4's named case, verbatim: NOMINAL execution, NON_QUALIFYING,
        POWER READINESS UNVERIFIED. Power readiness gates the stability streak;
        declaring technically sound execution degraded would be false."""
        monkeypatch.setattr(power, "read_power_state", lambda: battery_state())
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(5)
        report = composer.report(MON)
        assert report["qualifying"] is False
        assert report["qualification"] == "NON_QUALIFYING"
        assert report["qualification_reason"] == "POWER READINESS UNVERIFIED"
        assert report["session_health"] == "NOMINAL"
        assert report["degraded"] is False
        pre = report["events"][0]
        assert "power readiness UNVERIFIED" in pre["outcome"]
        assert "not on AC power" in pre["outcome"]

    def test_an_unreadable_power_state_fails_closed(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """An OS probe error is an unverified power state, never a pass."""

        def broken_read_power_state():
            raise OSError("pmset vanished")

        monkeypatch.setattr(power, "read_power_state", broken_read_power_state)
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(5)
        report = composer.report(MON)
        assert report["qualifying"] is False
        assert report["qualification_reason"] == "POWER READINESS UNVERIFIED"

    def test_an_unknown_power_source_fails_closed(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Readiness requires AC POSITIVELY identified. UNKNOWN is what pmset
        yields when unreadable (e.g. not macOS) — 'not on battery' must never
        be accepted as 'on AC'."""
        unknown = PowerState(
            source=PowerSource.UNKNOWN,
            prevent_system_sleep=True,
            prevent_idle_sleep=True,
            recent_sleep_events=0,
        )
        monkeypatch.setattr(power, "read_power_state", lambda: unknown)
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(5)
        report = composer.report(MON)
        assert report["qualifying"] is False
        assert report["qualification_reason"] == "POWER READINESS UNVERIFIED"

    def test_a_pre_session_suspension_blocks_power_verification(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """§31.5 'no unresolved suspension or wake condition': a suspension
        the wired detector observed BEFORE the session record opened must
        reach the pre-startup gate, fail qualification closed, and then be
        resolved by that recording — the next session starts clean."""
        composer = Composer(clock, tmp_path, monkeypatch)
        sup = composer.supervisor
        # Overnight suspension: the wake sample fires while no record is open.
        sup._suspension._last_wall -= 3600.0
        sup._sample_suspension()
        assert sup._pending_suspension is True

        composer.run_events(5)  # Monday
        monday = composer.report(MON)
        assert monday["qualifying"] is False
        assert monday["qualification_reason"] == "POWER READINESS UNVERIFIED"
        assert monday["session_health"] == "NOMINAL", (
            "execution itself was sound — the two §31.4 axes stay independent"
        )
        pre = monday["events"][0]
        assert "unresolved pre-session suspension" in pre["outcome"]

        composer.run_events(5)  # Tuesday: the condition was recorded, so
        tuesday = composer.report(dt.date(2026, 8, 11))  # it must not linger
        assert tuesday["qualifying"] is True

    def test_a_session_without_pre_startup_never_claims_power(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """Only the executed pre-startup gate may set power_verified. A record
        default, an attestation, or a mid-session join must all stay False."""
        assert SessionRecord(session_date=MON).power_verified is False
        composer = Composer(clock, tmp_path, monkeypatch, start=at(MON, 7, 30))
        composer.run_events(4)  # joined after pre_startup: briefing..flatten only
        report = composer.report(MON)
        assert report["qualifying"] is False
        assert any("power/sleep readiness not verified" in r for r in report["reasons"])


class TestPowerGateFailsClosedAtTheSupervisor:
    """The §31.5 required conditions the supervisor itself must establish:
    a missing verifier, a raising verifier, an unwired detector, and an
    unwired heartbeat are each an UNVERIFIED power state, never a pass.
    Driven on bare Supervisors deliberately — these are the fail-closed
    directions the builder can never produce, and they must fail closed
    anyway (defense in depth under the manifest)."""

    @staticmethod
    def bare(**overrides) -> Supervisor:
        wiring = dict(
            clock=None,
            probe=healthy,
            notify=lambda kind, body: True,
            report_dir=Path("/nonexistent"),
            now=lambda: at(MON, 6, 0),
            sleep=lambda seconds: None,
            heartbeat=lambda phase: None,
            suspension=SuspensionDetector(wall=lambda: 0.0, monotonic=lambda: 0.0),
            power_check=lambda: (True, "ok"),
        )
        wiring.update(overrides)
        return Supervisor(**wiring)

    def test_no_verifier_wired_fails_closed(self) -> None:
        verified, detail = self.bare(power_check=None)._checked_power()
        assert verified is False
        assert "no power verifier wired" in detail

    def test_detector_unavailable_fails_closed(self) -> None:
        verified, detail = self.bare(suspension=None)._checked_power()
        assert verified is False
        assert "suspension detector not operational" in detail

    def test_heartbeat_unwired_fails_closed(self) -> None:
        verified, detail = self.bare(heartbeat=None)._checked_power()
        assert verified is False
        assert "heartbeat not wired" in detail

    def test_a_raising_verifier_fails_closed(self) -> None:
        def exploding() -> tuple[bool, str]:
            raise RuntimeError("boom")

        verified, detail = self.bare(power_check=exploding)._checked_power()
        assert verified is False
        assert "power check failed" in detail

    def test_a_full_pass_requires_every_condition(self) -> None:
        verified, detail = self.bare()._checked_power()
        assert verified is True
        assert detail == "ok"


# --------------------------------------------------------------------------
# §31.5 DURING the session: "If AC power disappears during the session the
# runtime records the power-state failure, marks the session degraded and
# non-qualifying, sends the owner alert ... and remains fail closed."
#
# A single pre-startup sample cannot see a transition. These drive the real
# production builder across whole sessions with power changing mid-flight.
# --------------------------------------------------------------------------


class StagedPower:
    """Power readiness that changes at a chosen London wall-clock time."""

    def __init__(self, moment, switch_at, before=None, after=None):
        self._moment = moment
        self._switch_at = switch_at
        self._before = before or ready_state()
        self._after = after if after is not None else battery_state()
        self.calls = 0

    def __call__(self) -> PowerState:
        self.calls += 1
        state = self._before if self._moment() < self._switch_at else self._after
        if isinstance(state, BaseException):
            raise state
        return state


def assertions_dropped() -> PowerState:
    """caffeinate died: sleep-prevention assertions gone, still on AC."""
    return PowerState(
        source=PowerSource.AC,
        prevent_system_sleep=False,
        prevent_idle_sleep=False,
        recent_sleep_events=0,
    )


class TestMidSessionPowerLoss:
    def _staged(self, composer, monkeypatch, switch_at, after=None):
        staged = StagedPower(lambda: composer.moment, switch_at, after=after)
        monkeypatch.setattr(power, "read_power_state", staged)
        return staged

    def test_power_held_all_session_still_qualifies(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """Case 1: nothing regressed — a genuinely sound machine still earns
        its credit. The gate must be capable of passing, or it is not a gate."""
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(5)
        report = composer.report(MON)
        assert report["qualifying"] is True
        assert report["session_health"] == "NOMINAL"
        assert report["power_lost_in_session"] is False
        assert report["power_failure_boundary"] is None

    def test_power_verified_at_every_boundary_not_just_pre_startup(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """The defect: exactly one sample for the whole session."""
        staged = self._staged(
            Composer(clock, tmp_path / "probe", monkeypatch), monkeypatch,
            at(MON, 23, 0),  # never switches
        )
        composer = Composer(clock, tmp_path, monkeypatch)
        monkeypatch.setattr(power, "read_power_state", staged)
        staged._moment = lambda: composer.moment
        composer.run_events(5)
        assert staged.calls == 5, (
            f"power was verified {staged.calls}x for 5 boundaries — §31.5 "
            f"requires power to hold THROUGHOUT the session, and a transition "
            f"is invisible to a single sample"
        )

    def test_ac_lost_before_the_second_boundary_degrades_and_disqualifies(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 2 — the merge-gate scenario: AC present at pre-startup, gone by
        briefing. §31.5 requires BOTH degraded and non-qualifying."""
        composer = Composer(clock, tmp_path, monkeypatch)
        self._staged(composer, monkeypatch, at(MON, 7, 30))
        composer.run_events(5)
        report = composer.report(MON)
        assert report["degraded"] is True
        assert report["qualifying"] is False
        assert report["session_health"] == "DEGRADED"
        assert report["qualification_reason"] == "POWER LOST DURING SESSION"
        assert report["power_lost_in_session"] is True
        assert report["power_failure_boundary"] == "briefing"
        assert report["power_failure_at"] is not None
        assert "not on AC power" in report["power_failure_reason"]
        assert any("LOST during the session" in r for r in report["reasons"])

    def test_ac_lost_only_before_flatten_still_degrades(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 3: the last boundary is not exempt — and at flatten the power
        sample runs after the §31.2 broker verification, so the flat state is
        still verified on time."""
        composer = Composer(clock, tmp_path, monkeypatch)
        self._staged(composer, monkeypatch, at(MON, 10, 45))
        composer.run_events(5)
        report = composer.report(MON)
        assert report["power_failure_boundary"] == "flatten"
        assert report["degraded"] is True
        assert report["qualifying"] is False
        assert report["flat_state"] == str(FlatState.VERIFIED_FLAT), (
            "the §31.2 verification must not be starved by the power probe"
        )

    def test_a_raising_verifier_mid_session_fails_closed(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 4: cannot verify == not verified, mid-session too."""
        composer = Composer(clock, tmp_path, monkeypatch)
        self._staged(composer, monkeypatch, at(MON, 7, 30),
                     after=OSError("pmset vanished"))
        composer.run_events(5)
        report = composer.report(MON)
        assert report["degraded"] is True
        assert report["qualifying"] is False
        assert report["power_lost_in_session"] is True

    def test_sleep_prevention_assertion_lost_mid_session_degrades(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 5: caffeinate died. §31.5's readiness predicate is the ratified
        one — AC plus the sleep-prevention assertion — and §18 requires sleep
        disabled 'during the session', so losing the assertion is losing
        readiness even while the plug is still in."""
        composer = Composer(clock, tmp_path, monkeypatch)
        self._staged(composer, monkeypatch, at(MON, 7, 30),
                     after=assertions_dropped())
        composer.run_events(5)
        report = composer.report(MON)
        assert report["power_lost_in_session"] is True
        assert report["degraded"] is True
        assert report["qualifying"] is False
        assert "assertion absent" in report["power_failure_reason"]

    def test_recovery_does_not_restore_qualification(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 6 — the latch. Power fails at briefing and is back by
        activation; the session stays degraded and non-qualifying, because the
        interval in which the machine was unprotected did not un-happen
        (§31.2's reasoning about a late flat verification, applied here)."""
        composer = Composer(clock, tmp_path, monkeypatch)
        states = {"n": 0}

        def flapping():
            states["n"] += 1
            return battery_state() if states["n"] == 2 else ready_state()

        monkeypatch.setattr(power, "read_power_state", flapping)
        composer.run_events(5)
        report = composer.report(MON)
        assert report["power_lost_in_session"] is True, "the latch must hold"
        assert report["power_failure_boundary"] == "briefing"
        assert report["degraded"] is True
        assert report["qualifying"] is False

    def test_healthy_heartbeat_does_not_rescue_invalid_power(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 7."""
        composer = Composer(clock, tmp_path, monkeypatch)  # heartbeat wired
        self._staged(composer, monkeypatch, at(MON, 7, 30))
        composer.run_events(5)
        assert composer.report(MON)["qualifying"] is False

    def test_operational_detector_does_not_rescue_absent_ac(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 8: the detector is wired and sees no gap — the machine is awake
        on battery. Suspension detection is not a power check."""
        composer = Composer(clock, tmp_path, monkeypatch)
        self._staged(composer, monkeypatch, at(MON, 7, 30))
        composer.run_events(5)
        report = composer.report(MON)
        assert report["suspension_detected"] is False
        assert report["qualifying"] is False
        assert report["power_lost_in_session"] is True

    def test_the_owner_is_alerted_once_per_failure_event(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 9 + no alert storm: the latch means a failure persisting across
        three boundaries is one alert, not three (§19 severity policy)."""
        composer = Composer(clock, tmp_path, monkeypatch)
        self._staged(composer, monkeypatch, at(MON, 7, 30))
        composer.run_events(5)
        power_alerts = [
            (kind, body) for kind, body in composer.sent
            if "POWER LOST DURING SESSION" in body
        ]
        assert len(power_alerts) == 1, f"expected one alert, got {power_alerts}"
        kind, body = power_alerts[0]
        assert kind == NotificationKind.RISK_HALT
        assert "briefing" in body

    def test_no_power_alert_when_power_holds(
        self, clock, tmp_path, monkeypatch, ready_power
    ) -> None:
        """Case 10: a sound machine must not be alerted about its power."""
        composer = Composer(clock, tmp_path, monkeypatch)
        composer.run_events(5)
        assert not [b for _, b in composer.sent if "POWER LOST" in b]

    def test_a_new_session_does_not_inherit_the_prior_failure(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 11: the latch is per-session, and the next day starts clean."""
        composer = Composer(clock, tmp_path, monkeypatch)
        staged = self._staged(composer, monkeypatch, at(MON, 7, 30))
        composer.run_events(5)
        assert composer.report(MON)["power_lost_in_session"] is True
        # Tuesday: the plug is back in.
        monkeypatch.setattr(power, "read_power_state", lambda: ready_state())
        composer.run_events(5)
        tuesday = composer.report(dt.date(2026, 8, 11))
        assert tuesday["power_lost_in_session"] is False
        assert tuesday["qualifying"] is True
        assert staged.calls >= 5

    def test_restart_chain_recent_pmset_sleep_still_fails_readiness(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """The final-rereview blocking chain, closed end to end: the machine
        slept 45 minutes before pre-startup and the process RESTARTED, losing
        the in-memory pending-suspension flag and the detector's history. The
        pmset recent-sleep backstop is then the only §31.5 guard — and under
        the old line-bounded parser, 400 denser log lines hid the sleep and
        the session could QUALIFY. This drives the REAL read_power_state →
        count_recent_sleep_events path (only `_pmset` is substituted), through
        the production builder."""
        pre_startup_at = at(MON, 7, 15)
        sleep_at = pre_startup_at - dt.timedelta(minutes=45)
        stamp = f"{sleep_at:%Y-%m-%d %H:%M:%S} {sleep_at:%z}"
        dense = "\n".join(
            f"{sleep_at + dt.timedelta(seconds=6 * i):%Y-%m-%d %H:%M:%S} "
            f"{sleep_at:%z} Assertions  PID 4242 Created ..."
            for i in range(1, 401)
        )
        outputs = {
            ("-g", "ps"): "Now drawing from 'AC Power'\n -InternalBattery-0 100%",
            ("-g", "assertions"): (
                "Assertion status system-wide:\n"
                "   PreventUserIdleSystemSleep     1\n"
                "   PreventSystemSleep             1\n"
            ),
            ("-g", "log"): (
                f"{stamp} Sleep  Entering Sleep state due to 'Clamshell Sleep': ...\n"
                + dense
            ),
        }
        monkeypatch.setattr(power, "_pmset", lambda *args: outputs[args])
        # Freeze the window clock at the session moment so the 45-minute-old
        # sleep is genuinely inside the ratified hour when the gate runs.
        real_read = power.read_power_state
        composer = Composer(clock, tmp_path, monkeypatch)  # the RESTARTED process
        monkeypatch.setattr(
            power, "read_power_state",
            lambda: real_read(now=composer.moment),
        )
        composer.run_events(5)
        report = composer.report(MON)
        assert report["power_verified"] is False, (
            "a sleep 45 minutes before pre-startup, buried under 400 newer "
            "log lines, must still be seen by the recent-sleep window"
        )
        assert report["qualifying"] is False
        assert report["qualification_reason"] == "POWER READINESS UNVERIFIED"
        pre = report["events"][0]
        assert "sleep event(s) in the last hour" in pre["outcome"]

    def test_restart_after_the_window_expires_starts_clean(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """The mirror case: the sleep is genuinely older than the hour, so a
        restarted process is NOT haunted by it — no false retained failure."""
        pre_startup_at = at(MON, 7, 15)
        sleep_at = pre_startup_at - dt.timedelta(hours=2)
        outputs = {
            ("-g", "ps"): "Now drawing from 'AC Power'\n -InternalBattery-0 100%",
            ("-g", "assertions"): (
                "Assertion status system-wide:\n"
                "   PreventUserIdleSystemSleep     1\n"
                "   PreventSystemSleep             1\n"
            ),
            ("-g", "log"): (
                f"{sleep_at:%Y-%m-%d %H:%M:%S} {sleep_at:%z} Sleep  "
                f"Entering Sleep state due to 'Clamshell Sleep': ...\n"
            ),
        }
        monkeypatch.setattr(power, "_pmset", lambda *args: outputs[args])
        real_read = power.read_power_state
        composer = Composer(clock, tmp_path, monkeypatch)
        monkeypatch.setattr(
            power, "read_power_state",
            lambda: real_read(now=composer.moment),
        )
        composer.run_events(5)
        report = composer.report(MON)
        assert report["power_verified"] is True
        assert report["qualifying"] is True

    def test_a_restart_cannot_convert_a_completed_failure_into_a_pass(
        self, clock, tmp_path, monkeypatch
    ) -> None:
        """Case 12: the terminal report is the durable record. A fresh process
        starts with clean in-memory power state, and that must not rewrite a
        session already written as power-failed."""
        composer = Composer(clock, tmp_path, monkeypatch)
        self._staged(composer, monkeypatch, at(MON, 7, 30))
        composer.run_events(5)
        before = composer.report(MON)
        assert before["power_lost_in_session"] is True

        restarted = Composer(clock, tmp_path / "restart", monkeypatch)
        restarted.supervisor._report_dir = composer.report_dir
        restarted.report_dir = composer.report_dir
        monkeypatch.setattr(power, "read_power_state", lambda: ready_state())
        assert restarted.supervisor._record is None
        restarted.run_events(1)
        assert composer.report(MON) == before, (
            "a restart must never upgrade a completed power-failed session"
        )
