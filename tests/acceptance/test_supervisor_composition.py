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
from trading_firm.runner import power
from trading_firm.runner.power import PowerSource, PowerState, SuspensionDetector
from trading_firm.runner.schedule import next_event
from trading_firm.runner.supervisor import HealthReport, SessionRecord, Supervisor
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


# --------------------------------------------------------------------------
# The wiring manifest: the production composition contract, pinned statically.
# --------------------------------------------------------------------------


def _script_tree() -> ast.Module:
    return ast.parse(SCRIPT.read_text())


def _constructs_supervisor(node: ast.Call) -> bool:
    """Match `Supervisor(...)` AND `anything.Supervisor(...)`: an attribute-
    qualified second composition site must not slip past a Name-only match."""
    func = node.func
    if isinstance(func, ast.Name) and func.id == "Supervisor":
        return True
    return isinstance(func, ast.Attribute) and func.attr == "Supervisor"


def _supervisor_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _constructs_supervisor(node)
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
