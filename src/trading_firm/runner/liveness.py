"""Process liveness signals for the §18 supervisor: startup event and heartbeat.

Why this module exists. The supervisor wrote nothing on a healthy start, so
`supervisor.out.log` stayed empty forever and the logs could not tell
"running correctly" apart from "hung" — only a crash produced output. A crash
loop then produced the same traceback every throttle interval with nothing to
say how many times it had happened, and the installer reported success while
the process was failing on a loop. Observability was the gap; this is it
closed.

Four properties are deliberate:

- **Stdlib only, and no import of the order path.** The acceptance test
  `tests/acceptance/test_supervisor_no_order_path.py` asserts that no module
  under `runner/` links the execution package, and it globs the whole
  directory, so this module is covered the moment it exists. Observability is
  not a reason to weaken §0 iron rule 1: this writes files and computes
  states, and imports nothing that could reach a broker.

- **Flushed and fsynced.** A liveness signal still sitting in a stdio buffer
  when the process is killed is not a liveness signal. The heartbeat is
  written to a temporary file and atomically replaced, so a reader never sees
  a half-written record.

- **Secret-free by assertion, not by care.** Every payload is checked against
  the values of the known credential variables before it reaches disk, and a
  match raises instead of writing. "We only put safe fields in" is a review
  claim that does not survive the next person adding a field (§0 iron rule 5).

- **Diagnosis is a pure function.** `diagnose()` takes plain data and returns
  a state, so every transition is unit-tested without launchd, without a
  clock, and without a running process. The launchctl parsing is a thin
  adapter in `scripts/supervisor_status.py`.

The heartbeat says the loop is turning. It deliberately says nothing about
whether the firm is trading, and nothing here can change that: no value in
this module is read by the risk gate, the scheduler, or any order path.
"""

from __future__ import annotations

import datetime as dt
import enum
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1

HEARTBEAT_FILENAME = "supervisor-heartbeat.json"
EVENTS_FILENAME = "supervisor-events.jsonl"

STARTUP_EVENT = "supervisor_startup"

# `runner.supervisor` sleeps in slices of at most MAX_SLEEP_SLICE_SECONDS (300)
# and beats once per slice, so a beat older than three slices means the loop is
# not turning. Generous on purpose: a false "hung" reading after a laptop lid
# close would train the owner to ignore the signal, which is worse than no
# signal at all.
DEFAULT_MAX_BEAT_AGE_SECONDS = 900.0

# Repeated startups inside this window are a crash loop, not restarts. The
# launchd ThrottleInterval is 60s, so three starts in ten minutes cannot happen
# to a process that is staying up.
CRASH_LOOP_WINDOW_SECONDS = 600.0
CRASH_LOOP_MIN_STARTS = 3

# Checked against every payload before it is written. Names only ever appear in
# error messages; values never do.
SECRET_ENV_VARS = (
    "OANDA_DEMO_API_TOKEN",
    "OANDA_API_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)

# Below this length a value is too short to be a credential and too likely to
# collide with an ordinary field (a pid, a version component).
MIN_SECRET_LENGTH = 8

# Transport detail is already bounded upstream; bounded again here so a hostile
# or malformed error string cannot grow the events log without limit.
DETAIL_LIMIT = 200


class SecretLeakError(RuntimeError):
    """Raised instead of writing a payload that contains a credential value."""


class SupervisorState(enum.StrEnum):
    HEALTHY = "healthy"
    STALE = "stale"
    STOPPED = "stopped"
    CRASH_LOOPING = "crash_looping"


@dataclass(frozen=True)
class Heartbeat:
    """The last liveness record the supervisor wrote."""

    schema_version: int
    pid: int
    interpreter: str
    python_version: str
    started_at: dt.datetime
    beat_at: dt.datetime
    beats: int
    phase: str

    def age_seconds(self, now: dt.datetime) -> float:
        return (now - self.beat_at).total_seconds()


@dataclass(frozen=True)
class LaunchdStatus:
    """What the launchd domain says. Parsed by the status script, not here."""

    loaded: bool
    running: bool = False
    pid: int | None = None
    runs: int | None = None
    # None means the job has never exited — the healthy case for a long-runner.
    last_exit_code: int | None = None


@dataclass(frozen=True)
class Diagnosis:
    state: SupervisorState
    reason: str
    beat_age_seconds: float | None = None
    recent_starts: int = 0

    @property
    def healthy(self) -> bool:
        return self.state is SupervisorState.HEALTHY


# --------------------------------------------------------------- secret guard


def _secret_names_present(text: str, env: Mapping[str, str]) -> list[str]:
    hits = []
    for name in SECRET_ENV_VARS:
        value = env.get(name)
        if value and len(value) >= MIN_SECRET_LENGTH and value in text:
            hits.append(name)
    return hits


def assert_secret_free(text: str, env: Mapping[str, str] | None = None) -> None:
    """Raise if `text` contains the value of a known credential variable.

    The error names the VARIABLE, never the value — an exception string reaches
    logs and the audit trail, and §0 rule 11 makes that record immutable.
    """
    hits = _secret_names_present(text, os.environ if env is None else env)
    if hits:
        raise SecretLeakError(
            f"refusing to write a liveness payload containing the value of "
            f"{', '.join(hits)} (§0 iron rule 5). This is a bug in the caller: "
            f"liveness records carry process facts, never credentials."
        )


# ------------------------------------------------------------------- writing


def _fsync_write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _write_heartbeat_file(path: Path, payload: dict, env: Mapping[str, str] | None) -> None:
    text = json.dumps(payload, sort_keys=True) + "\n"
    assert_secret_free(text, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace: a reader polling this file during install must never see
    # a partial record and call it corrupt.
    temporary = path.with_name(path.name + ".tmp")
    _fsync_write(temporary, text)
    os.replace(temporary, path)


def _append_event(path: Path, payload: dict, env: Mapping[str, str] | None) -> None:
    text = json.dumps(payload, sort_keys=True) + "\n"
    assert_secret_free(text, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def startup_payload(
    *,
    now: dt.datetime,
    pid: int,
    interpreter: str,
    python_version: str,
    mode: str,
    repo: str,
) -> dict:
    """The structured startup record. Every field is a process fact."""
    return {
        "schema_version": SCHEMA_VERSION,
        "event": STARTUP_EVENT,
        "at": now.isoformat(),
        "pid": pid,
        "interpreter": interpreter,
        "python_version": python_version,
        "mode": mode,
        "repo": repo,
    }


def record_startup(
    log_dir: Path,
    *,
    now: dt.datetime,
    pid: int,
    interpreter: str,
    python_version: str,
    mode: str,
    repo: str,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Append the startup event AND lay down the first heartbeat.

    Both, immediately: the event gives the installer something to prove the
    process reached its own entry point, and the initial heartbeat means a
    status check moments after bootstrap does not have to wait for the first
    sleep slice to see a live signal.
    """
    payload = startup_payload(
        now=now,
        pid=pid,
        interpreter=interpreter,
        python_version=python_version,
        mode=mode,
        repo=repo,
    )
    _append_event(log_dir / EVENTS_FILENAME, payload, env)
    write_heartbeat(
        log_dir,
        now=now,
        started_at=now,
        pid=pid,
        interpreter=interpreter,
        python_version=python_version,
        beats=0,
        phase="startup",
        env=env,
    )
    return payload


def write_heartbeat(
    log_dir: Path,
    *,
    now: dt.datetime,
    started_at: dt.datetime,
    pid: int,
    interpreter: str,
    python_version: str,
    beats: int,
    phase: str,
    env: Mapping[str, str] | None = None,
) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "pid": pid,
        "interpreter": interpreter,
        "python_version": python_version,
        "started_at": started_at.isoformat(),
        "beat_at": now.isoformat(),
        "beats": beats,
        "phase": phase,
    }
    _write_heartbeat_file(log_dir / HEARTBEAT_FILENAME, payload, env)
    return payload


class HeartbeatWriter:
    """Stateful convenience wrapper the composition script injects as a callback.

    Kept out of `Supervisor` itself: the supervisor takes a plain callable, so
    the trading loop has no knowledge of files, schemas, or this class.
    """

    def __init__(
        self,
        log_dir: Path,
        *,
        started_at: dt.datetime,
        pid: int,
        interpreter: str,
        python_version: str,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._log_dir = log_dir
        self._started_at = started_at
        self._pid = pid
        self._interpreter = interpreter
        self._python_version = python_version
        self._now = now
        self._beats = 0

    def __call__(self, phase: str) -> None:
        self._beats += 1
        moment = self._now() if self._now is not None else dt.datetime.now(dt.UTC)
        write_heartbeat(
            self._log_dir,
            now=moment,
            started_at=self._started_at,
            pid=self._pid,
            interpreter=self._interpreter,
            python_version=self._python_version,
            beats=self._beats,
            phase=phase,
        )


# ------------------------------------------------------------------- reading


def read_heartbeat(log_dir: Path) -> Heartbeat | None:
    """Return the last heartbeat, or None if absent or unreadable.

    Unreadable is treated as absent on purpose: a corrupt heartbeat means the
    supervisor's liveness is unknown, which `diagnose()` reports as stale
    rather than healthy. Failing towards "not healthy" is the §0.10 direction.
    """
    path = log_dir / HEARTBEAT_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return Heartbeat(
            schema_version=int(raw["schema_version"]),
            pid=int(raw["pid"]),
            interpreter=str(raw["interpreter"]),
            python_version=str(raw["python_version"]),
            started_at=dt.datetime.fromisoformat(str(raw["started_at"])),
            beat_at=dt.datetime.fromisoformat(str(raw["beat_at"])),
            beats=int(raw["beats"]),
            phase=str(raw["phase"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def recent_start_count(
    log_dir: Path,
    *,
    now: dt.datetime,
    window_seconds: float = CRASH_LOOP_WINDOW_SECONDS,
) -> int:
    """How many startup events were recorded inside the window."""
    path = log_dir / EVENTS_FILENAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if record.get("event") != STARTUP_EVENT:
                continue
            at = dt.datetime.fromisoformat(str(record["at"]))
        except (ValueError, KeyError, TypeError):
            continue  # a torn or foreign line is not evidence of a restart
        if 0 <= (now - at).total_seconds() <= window_seconds:
            count += 1
    return count


def pid_alive(pid: int) -> bool:
    """Signal 0 probe: does this pid exist and are we allowed to see it?"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


# ----------------------------------------------------------------- diagnosis


def diagnose(
    *,
    launchd: LaunchdStatus,
    heartbeat: Heartbeat | None,
    recent_starts: int,
    now: dt.datetime,
    max_beat_age_seconds: float = DEFAULT_MAX_BEAT_AGE_SECONDS,
    heartbeat_pid_alive: bool | None = None,
) -> Diagnosis:
    """Classify the supervisor into exactly one of four states.

    Pure: no clock, no filesystem, no launchctl. Order matters — the crash-loop
    check runs before the running/not-running split, because a job that is
    respawning fast is briefly "running" at the moment you look at it, and
    reporting that snapshot as healthy is precisely the failure this exists to
    prevent.
    """
    age = heartbeat.age_seconds(now) if heartbeat is not None else None

    if not launchd.loaded:
        return Diagnosis(
            state=SupervisorState.STOPPED,
            reason="launchd has no such job: the agent is not loaded",
            beat_age_seconds=age,
            recent_starts=recent_starts,
        )

    if recent_starts >= CRASH_LOOP_MIN_STARTS:
        return Diagnosis(
            state=SupervisorState.CRASH_LOOPING,
            reason=(
                f"{recent_starts} startups in the last "
                f"{int(CRASH_LOOP_WINDOW_SECONDS // 60)} minutes: the process is "
                f"restarting, not running"
            ),
            beat_age_seconds=age,
            recent_starts=recent_starts,
        )

    if not launchd.running:
        if launchd.last_exit_code in (None, 0):
            return Diagnosis(
                state=SupervisorState.STOPPED,
                reason="loaded but not running, last exit was clean",
                beat_age_seconds=age,
                recent_starts=recent_starts,
            )
        return Diagnosis(
            state=SupervisorState.CRASH_LOOPING,
            reason=(
                f"loaded but not running, last exit code "
                f"{launchd.last_exit_code}: awaiting a throttled respawn"
            ),
            beat_age_seconds=age,
            recent_starts=recent_starts,
        )

    if heartbeat is None:
        return Diagnosis(
            state=SupervisorState.STALE,
            reason="running, but no readable heartbeat has been written",
            beat_age_seconds=None,
            recent_starts=recent_starts,
        )

    if heartbeat_pid_alive is False:
        return Diagnosis(
            state=SupervisorState.STALE,
            reason=(
                f"the heartbeat names pid {heartbeat.pid}, which no longer exists: "
                f"the record is from a previous process"
            ),
            beat_age_seconds=age,
            recent_starts=recent_starts,
        )

    if age is not None and age > max_beat_age_seconds:
        return Diagnosis(
            state=SupervisorState.STALE,
            reason=(
                f"heartbeat is {age:.0f}s old (limit {max_beat_age_seconds:.0f}s): "
                f"the process is up but its loop is not turning"
            ),
            beat_age_seconds=age,
            recent_starts=recent_starts,
        )

    return Diagnosis(
        state=SupervisorState.HEALTHY,
        reason=f"running, heartbeat {age:.0f}s old, {heartbeat.beats} beat(s)",
        beat_age_seconds=age,
        recent_starts=recent_starts,
    )


# ------------------------------------------------ notification delivery state
#
# Two records, deliberately separate files, because they answer two different
# questions and conflating them is what the previous single "sent" marker got
# wrong. It was stamped on ATTEMPT, which capped the flood but silently
# recorded a failed delivery as if it had succeeded.
#
#   delivery marker  — written ONLY after a confirmed delivery. Answers
#                      "has the owner actually been told?" Governs dedup.
#   attempt ledger   — written on EVERY attempt, success or failure. Answers
#                      "may we try again yet, and how many times have we?"
#                      Governs the retry interval and the bound.
#
# Splitting them is what lets a failed delivery stay eligible for retry
# (§18 advisory posture) while a crash loop still cannot hammer the API: the
# ledger gates the interval and the bound regardless of outcome.

NOTIFY_EVENT = "supervisor_startup_notify"
LEGACY_ASSUMPTION_EVENT = "supervisor_startup_notify_legacy_assumption"

# Once confirmed, do not re-announce the same startup for this long.
DELIVERY_CONFIRMED_TTL_SECONDS = 3600.0

# A migrated legacy marker is an ASSUMPTION, not a delivery. The old marker was
# stamped on attempt, so it proves only that a send was tried. It suppresses a
# duplicate for this long and then EXPIRES, at which point a real send happens
# and produces a real confirmation. Finite by design: an assumption that never
# expired would permanently masquerade as evidence the owner had been reached.
LEGACY_ASSUMPTION_TTL_SECONDS = 3600.0
# A failed attempt may be retried no sooner than this. Matched to the
# supervisor's sleep slice so a retry rides an existing wakeup.
NOTIFY_RETRY_INTERVAL_SECONDS = 300.0
# Bounded: after this many consecutive failures, stop trying until a genuinely
# new episode. An unbounded retry against a dead endpoint is a slow flood.
NOTIFY_MAX_ATTEMPTS = 5


class NotifyState(enum.StrEnum):
    """Whether the owner has actually been reached (§19 surface health).

    `ASSUMED` is deliberately NOT `CONFIRMED`. It means a migrated legacy marker
    is suppressing a duplicate, and that marker recorded an *attempt*, never a
    delivery. Anything gating live readiness must require CONFIRMED, so an
    assumption inherited from an upgrade can never stand in for evidence that
    the owner is reachable.
    """

    CONFIRMED = "confirmed"
    ASSUMED = "legacy_assumed_confirmation"
    UNCONFIRMED = "unconfirmed"  # never delivered, or the last attempt failed
    EXHAUSTED = "exhausted"  # bounded retries spent without a confirmation


@dataclass(frozen=True)
class NotifyLedger:
    last_attempt_at: dt.datetime | None = None
    consecutive_failures: int = 0


@dataclass(frozen=True)
class NotifyDecision:
    should_send: bool
    reason: str
    attempt_number: int = 0


def _read_timestamp(path: Path, key: str) -> dt.datetime | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return dt.datetime.fromisoformat(str(raw[key]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_delivery_marker(path: Path) -> dt.datetime | None:
    """When delivery was last CONFIRMED by the API, or None.

    Reads ONLY real confirmations. A migrated legacy marker is never returned
    here — see `migrate_legacy_marker`, which keeps assumptions in a separate
    file and a separate state so they cannot be mistaken for deliveries.
    """
    return _read_timestamp(path, "delivered_at")


def record_delivered(path: Path, *, now: dt.datetime) -> None:
    """Write the success marker. Callers MUST only reach this after ok is True."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _fsync_write(path, json.dumps({"delivered_at": now.isoformat()}) + "\n")


def read_assumed_confirmation(path: Path) -> dt.datetime | None:
    """When a legacy marker was migrated, or None. Not a delivery."""
    return _read_timestamp(path, "assumed_at")


def migrate_legacy_marker(
    *,
    legacy: Path,
    assumption: Path,
    log_dir: Path,
    now: dt.datetime,
    env: Mapping[str, str] | None = None,
) -> dt.datetime | None:
    """Convert the old attempt-stamped marker into an explicit, finite assumption.

    Run ONCE: if the assumption file already exists, the migration has happened
    and the legacy value is never re-read. Returns the assumed timestamp (the
    existing one on later calls), or None if there is nothing to migrate.

    The old marker recorded that a send was ATTEMPTED. Carrying that forward as
    a delivery would be a lie told by an upgrade — so it becomes an assumption
    with its own state, its own finite TTL, and an event record naming what was
    inherited and from when. It never writes the delivery marker.
    """
    existing = read_assumed_confirmation(assumption)
    if existing is not None:
        return existing

    inherited = _read_timestamp(legacy, "last_sent_at")
    if inherited is None:
        return None

    assumption.parent.mkdir(parents=True, exist_ok=True)
    _fsync_write(
        assumption,
        json.dumps(
            {
                "assumed_at": inherited.isoformat(),
                "migrated_at": now.isoformat(),
                "source": legacy.name,
                "basis": "legacy marker recorded a send ATTEMPT, not a confirmation",
                "ttl_seconds": LEGACY_ASSUMPTION_TTL_SECONDS,
            }
        )
        + "\n",
    )
    _append_event(
        log_dir / EVENTS_FILENAME,
        {
            "schema_version": SCHEMA_VERSION,
            "event": LEGACY_ASSUMPTION_EVENT,
            "at": now.isoformat(),
            "assumed_at": inherited.isoformat(),
            "ttl_seconds": LEGACY_ASSUMPTION_TTL_SECONDS,
            "detail": (
                "migrated a legacy attempt-stamped marker; suppressing a duplicate "
                "startup message until the assumption expires. This is NOT a "
                "confirmed delivery and does not satisfy --require-notify-confirmed."
            ),
        },
        env,
    )
    return inherited


def read_attempt_ledger(path: Path) -> NotifyLedger:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return NotifyLedger(
            last_attempt_at=dt.datetime.fromisoformat(str(raw["last_attempt_at"])),
            consecutive_failures=int(raw.get("consecutive_failures", 0)),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return NotifyLedger()


def record_attempt(path: Path, *, now: dt.datetime, ok: bool) -> NotifyLedger:
    """Record one attempt. Success resets the failure count; failure raises it.

    This is written for BOTH outcomes — that is the whole point. A success-only
    ledger would let a failing path retry on every restart.
    """
    previous = read_attempt_ledger(path)
    ledger = NotifyLedger(
        last_attempt_at=now,
        consecutive_failures=0 if ok else previous.consecutive_failures + 1,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _fsync_write(
        path,
        json.dumps(
            {
                "last_attempt_at": now.isoformat(),
                "consecutive_failures": ledger.consecutive_failures,
            }
        )
        + "\n",
    )
    return ledger


def _live_failures(
    ledger: NotifyLedger, now: dt.datetime, episode_ttl_seconds: float
) -> tuple[int, bool]:
    """Failure count for the CURRENT episode, and whether the episode lapsed.

    The count lives on disk, so it survives process restarts — a crash loop must
    not get a fresh budget of retries every 60 seconds, which is precisely what
    an in-memory counter would hand it. It resets on a confirmed success (see
    `record_attempt`) or when an episode lapses with no attempt at all; never
    on a restart.
    """
    lapsed = (
        ledger.last_attempt_at is None
        or (now - ledger.last_attempt_at).total_seconds() >= episode_ttl_seconds
    )
    return (0 if lapsed else ledger.consecutive_failures), lapsed


def plan_notification(
    *,
    delivered_at: dt.datetime | None,
    ledger: NotifyLedger,
    now: dt.datetime,
    assumed_at: dt.datetime | None = None,
    confirmed_ttl_seconds: float = DELIVERY_CONFIRMED_TTL_SECONDS,
    assumption_ttl_seconds: float = LEGACY_ASSUMPTION_TTL_SECONDS,
    retry_interval_seconds: float = NOTIFY_RETRY_INTERVAL_SECONDS,
    max_attempts: int = NOTIFY_MAX_ATTEMPTS,
) -> NotifyDecision:
    """Decide whether to send now. Pure, so every branch is tested directly."""
    failures, episode_over = _live_failures(ledger, now, confirmed_ttl_seconds)

    if delivered_at is not None:
        age = (now - delivered_at).total_seconds()
        if 0 <= age < confirmed_ttl_seconds:
            return NotifyDecision(False, f"delivery confirmed {age:.0f}s ago; not repeating")

    # A legacy assumption suppresses a duplicate, but only until it expires —
    # after that a real send runs and produces a real confirmation.
    if assumed_at is not None:
        age = (now - assumed_at).total_seconds()
        if 0 <= age < assumption_ttl_seconds:
            return NotifyDecision(
                False,
                f"legacy assumed confirmation {age:.0f}s ago (expires in "
                f"{assumption_ttl_seconds - age:.0f}s); not repeating yet",
            )

    if failures >= max_attempts:
        return NotifyDecision(
            False, f"bounded retry spent ({failures}/{max_attempts}) without confirmation"
        )

    if not episode_over and ledger.last_attempt_at is not None:
        since = (now - ledger.last_attempt_at).total_seconds()
        if since < retry_interval_seconds:
            return NotifyDecision(
                False, f"last attempt {since:.0f}s ago; retry due in "
                f"{retry_interval_seconds - since:.0f}s"
            )

    return NotifyDecision(True, "eligible", attempt_number=failures + 1)


def notify_surface_state(
    *,
    delivered_at: dt.datetime | None,
    ledger: NotifyLedger,
    now: dt.datetime,
    assumed_at: dt.datetime | None = None,
    confirmed_ttl_seconds: float = DELIVERY_CONFIRMED_TTL_SECONDS,
    assumption_ttl_seconds: float = LEGACY_ASSUMPTION_TTL_SECONDS,
    max_attempts: int = NOTIFY_MAX_ATTEMPTS,
) -> NotifyState:
    """§19 surface health: has the owner actually been reached?

    Deliberately a SEPARATE AXIS from `SupervisorState`. A healthy supervisor
    with a dead notification path is a real and important condition, and
    collapsing the two would hide a silent alerting failure behind a green
    process. Nothing here feeds `diagnose()`, and nothing here can change the
    supervisor's own state.

    CONFIRMED requires a real delivery. A live assumption reports ASSUMED, which
    is a distinct, weaker claim.
    """
    if delivered_at is not None:
        age = (now - delivered_at).total_seconds()
        if 0 <= age < confirmed_ttl_seconds:
            return NotifyState.CONFIRMED

    failures, _ = _live_failures(ledger, now, confirmed_ttl_seconds)
    if failures >= max_attempts:
        return NotifyState.EXHAUSTED

    if assumed_at is not None:
        age = (now - assumed_at).total_seconds()
        if 0 <= age < assumption_ttl_seconds:
            return NotifyState.ASSUMED

    return NotifyState.UNCONFIRMED


def record_notification_attempt(
    log_dir: Path,
    *,
    now: dt.datetime,
    ok: bool,
    stage: str,
    status: int | None,
    attempt: int,
    detail: str,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Append the delivery outcome to the events log, secret-free.

    `detail` must already be redacted by the caller: this module cannot import
    the notify package (the runner may not link it), so the composition script
    scrubs the transport's detail before handing it over. The secret guard here
    is the backstop, not the primary scrub.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event": NOTIFY_EVENT,
        "at": now.isoformat(),
        "ok": ok,
        "stage": stage,
        "status": status,
        "attempt": attempt,
        "detail": detail[:DETAIL_LIMIT],
    }
    _append_event(log_dir / EVENTS_FILENAME, payload, env)
    return payload
