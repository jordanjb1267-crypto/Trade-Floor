"""Power and suspension integrity for the laptop deployment (§31.5, §18).

§18 has always required "Laptop connected to power during live window" and
"Sleep and hibernation disabled during session". Nothing checked either, and
on 2026-08-05/06 the machine entered clamshell sleep mid-session: the
supervisor was suspended through repeated Sleep/DarkWake cycles and executed
its boundaries up to 76 minutes late, including the inviolate flatten. This
module makes those requirements machine-checkable.

Two independent mechanisms, because they answer different questions:

- **Readiness** (`read_power_state`) is a BEFORE question, asked at
  pre-startup: is this machine in a state that can stay awake for a session?
  It shells out to `pmset`, which is a documented macOS interface.
- **Suspension detection** (`SuspensionDetector`) is a DURING question: did
  wall-clock time advance further than the monotonic clock while we were
  sleeping? That difference is the definition of a suspension, and it needs no
  operating-system cooperation at all — which matters, because the thing being
  detected is the OS declining to run us.

Deliberate limits. macOS does not reliably expose lid state to userspace, so
this module never claims to prove it (§31.5). `caffeinate -si` is defense in
depth, not permission: nothing here represents an assertion as a guarantee
against unsupported closed-display operation.

Stdlib only, and no import of execution, risk, or surveillance — the
`runner` package may not link the order path (§0 iron rule 1), and an
observability module is no reason to weaken that.
"""

from __future__ import annotations

import enum
import subprocess
import time
from dataclasses import dataclass

# A monotonic-vs-wall-clock divergence smaller than this is ordinary scheduler
# jitter and NTP correction, not a suspension. Generous relative to the 120s
# checkpoint tolerance so a routine clock adjustment never disqualifies a
# session, tight enough that the shortest real sleep on record (~45s of
# DarkWake) is still caught.
SUSPENSION_THRESHOLD_SECONDS = 30.0

# Sleep entries within this window before session start count as an unresolved
# wake condition: a machine that slept twenty minutes ago is a machine that
# will very likely sleep again mid-session.
RECENT_SLEEP_WINDOW_SECONDS = 3600.0


class PowerSource(enum.StrEnum):
    AC = "ac_power"
    BATTERY = "battery"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PowerState:
    """What macOS can actually prove before a session starts (§31.5)."""

    source: PowerSource
    prevent_system_sleep: bool
    prevent_idle_sleep: bool
    recent_sleep_events: int
    detail: str = ""

    @property
    def ready(self) -> bool:
        """Every machine-observable requirement, all of which must hold.

        Lid state is deliberately absent: macOS does not reliably expose it, so
        claiming to check it would be a lie told by a health gate.
        """
        return (
            self.source is PowerSource.AC
            and self.prevent_system_sleep
            and self.prevent_idle_sleep
            and self.recent_sleep_events == 0
        )

    def reasons(self) -> tuple[str, ...]:
        problems: list[str] = []
        if self.source is not PowerSource.AC:
            problems.append(f"not on AC power ({self.source})")
        if not self.prevent_system_sleep:
            problems.append("PreventSystemSleep assertion absent (caffeinate -s)")
        if not self.prevent_idle_sleep:
            problems.append("PreventUserIdleSystemSleep assertion absent (caffeinate -i)")
        if self.recent_sleep_events:
            problems.append(
                f"{self.recent_sleep_events} sleep event(s) in the last hour — the "
                f"machine is sleeping despite the assertions (lid closed?)"
            )
        return tuple(problems)


def _pmset(*args: str) -> str:
    """Run pmset read-only. Any failure yields empty output, never an exception:
    a health probe that crashes the supervisor inverts its own purpose."""
    try:
        result = subprocess.run(
            ["pmset", *args], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def parse_power_source(ps_output: str) -> PowerSource:
    """`pmset -g ps` names the drawing source on its first line."""
    head = ps_output.splitlines()[0] if ps_output.splitlines() else ""
    lowered = head.lower()
    if "ac power" in lowered:
        return PowerSource.AC
    if "battery power" in lowered:
        return PowerSource.BATTERY
    return PowerSource.UNKNOWN


def parse_assertions(assertions_output: str) -> tuple[bool, bool]:
    """Return (prevent_system_sleep, prevent_idle_sleep) from `pmset -g assertions`.

    The summary block prints each assertion with a count; a zero means held by
    nobody. Parsed rather than pattern-matched loosely, because "the assertion
    named in a process line" and "the assertion actually in force" differ.
    """
    system = idle = False
    for line in assertions_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("PreventSystemSleep"):
            system = stripped.split()[-1] != "0"
        elif stripped.startswith("PreventUserIdleSystemSleep"):
            idle = stripped.split()[-1] != "0"
    return system, idle


def count_recent_sleep_events(log_output: str, *, limit: int = 400) -> int:
    """Sleep entries in `pmset -g log` output. Caller supplies a pre-filtered
    window; this counts the transitions that matter."""
    count = 0
    for line in log_output.splitlines()[-limit:]:
        if "Entering Sleep state" in line:
            count += 1
    return count


def read_power_state(*, recent_sleep_lines: str | None = None) -> PowerState:
    """Probe macOS for everything §31.5 requires. Never raises."""
    source = parse_power_source(_pmset("-g", "ps"))
    system, idle = parse_assertions(_pmset("-g", "assertions"))
    log_text = recent_sleep_lines if recent_sleep_lines is not None else _pmset("-g", "log")
    recent = count_recent_sleep_events(log_text)
    return PowerState(
        source=source,
        prevent_system_sleep=system,
        prevent_idle_sleep=idle,
        recent_sleep_events=recent,
        detail="pmset",
    )


@dataclass(frozen=True)
class SuspensionEvent:
    """One detected gap between monotonic and wall-clock progress."""

    wall_gap_seconds: float
    monotonic_gap_seconds: float

    @property
    def suspended_seconds(self) -> float:
        return max(0.0, self.wall_gap_seconds - self.monotonic_gap_seconds)


class SuspensionDetector:
    """Detect that the process was frozen, by comparing two clocks.

    `time.monotonic()` does not advance while macOS is asleep; wall-clock time
    does. So a sample pair whose wall delta materially exceeds its monotonic
    delta means the process lost that difference to suspension. This needs no
    cooperation from the OS, which is the point — `pmset` can tell us the
    machine slept, but only these two clocks can tell us that *we* missed it.

    Injected clocks so the whole thing is testable without sleeping.
    """

    def __init__(
        self,
        *,
        wall: object = None,
        monotonic: object = None,
        threshold_seconds: float = SUSPENSION_THRESHOLD_SECONDS,
    ) -> None:
        self._wall = wall if wall is not None else time.time
        self._monotonic = monotonic if monotonic is not None else time.monotonic
        self._threshold = threshold_seconds
        self._last_wall = self._wall()
        self._last_monotonic = self._monotonic()
        self.total_suspended_seconds = 0.0
        self.events: list[SuspensionEvent] = []

    def sample(self) -> SuspensionEvent | None:
        """Call once per scheduler wake. Returns an event if time was lost."""
        wall_now, monotonic_now = self._wall(), self._monotonic()
        wall_gap = wall_now - self._last_wall
        monotonic_gap = monotonic_now - self._last_monotonic
        self._last_wall, self._last_monotonic = wall_now, monotonic_now

        drift = wall_gap - monotonic_gap
        if drift <= self._threshold:
            return None
        event = SuspensionEvent(wall_gap_seconds=wall_gap, monotonic_gap_seconds=monotonic_gap)
        self.total_suspended_seconds += event.suspended_seconds
        self.events.append(event)
        return event

    @property
    def detected(self) -> bool:
        return bool(self.events)
