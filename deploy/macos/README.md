# macOS supervisor — install, status, and repair

The §18 supervisor runs as a **LaunchAgent** in the owner's login session (not a
LaunchDaemon): it needs the untracked `.env` and any keychain material, both of
which belong to the logged-in user.

Nothing in this directory enables trading. The supervisor keeps a schedule and
reports health; `live_allowed` stays empty and the process cannot place an order
(§0 iron rule 1, asserted by `tests/acceptance/test_supervisor_no_order_path.py`).

## Install

```bash
bash deploy/macos/install.sh
```

The installer refuses to proceed unless all of the following hold, because each
one of them otherwise produces a silent 60-second crash loop that *looks* like a
successful install:

| Guard | Exit | Why |
|---|---|---|
| `.env` present | 2 | credentials must exist before a session starts |
| `.venv/bin/python` present | 3 | the plist pins this interpreter by absolute path |
| project importable in the venv | 4 | `import trading_firm, yaml` must work |
| `scripts/check_runtime.py` passes | 5 | Python >= 3.11 (§23) and TLS to the practice host |
| post-bootstrap verification | 6 | the process actually reached a healthy running state |

**`launchctl bootstrap` returning 0 does not mean the supervisor is running.**
It means launchd accepted the job. The installer therefore polls for up to 30
seconds after bootstrap and asserts three separate things: the agent is still
running, the heartbeat was written by the pinned venv interpreter, and that
heartbeat is fresh. If any fails it prints a diagnosis and recent stderr,
unloads the agent so it does not crash-loop in the background, and exits
nonzero. It does not report success it has not verified.

## Status

```bash
.venv/bin/python scripts/supervisor_status.py
```

`launchctl print` cannot answer the question you actually have: it reports
whether launchd holds a job, not whether the supervisor's loop is turning. A
hung process and a working one look identical to it, and a process respawning
every throttle interval reads as "running" at whichever instant you look.

The status command combines the launchd job state, the heartbeat written each
sleep slice, and the count of startup events inside the crash-loop window:

| State | Meaning | Exit |
|---|---|---|
| `HEALTHY` | running, heartbeat fresh | 0 |
| `STALE` | process up, loop not turning (or heartbeat from a dead pid) | 3 |
| `STOPPED` | not loaded, or loaded and cleanly exited | 4 |
| `CRASH_LOOPING` | repeated startups in the window, or a nonzero last exit | 5 |

Exit 0 only when healthy, so it drops straight into a monitoring check. Add
`--json` for machine-readable output. The command is read-only — it cannot
start, stop, or reconfigure anything.

## Stop

```bash
launchctl bootout gui/$(id -u)/com.tradefloor.supervisor
```

## Files it writes

| Path | Contents |
|---|---|
| `logs/supervisor.{out,err}.log` | raw stdio from launchd |
| `logs/supervisor-events.jsonl` | append-only structured startup events |
| `logs/supervisor-heartbeat.json` | latest liveness record, atomically replaced |
| `state/ops/supervisor-startup-notify.json` | rate-limit marker for the Telegram startup message |

All are gitignored and all are secret-free by assertion: every payload is
checked against the values of the known credential variables before it reaches
disk, and a match raises instead of writing (§0 iron rule 5).

## Notification delivery: two records, two questions

The startup message uses **two separate files** because they answer different
questions, and the earlier single "sent" marker conflated them — it was stamped
on *attempt*, so a failed delivery was recorded as if it had succeeded.

| File | Written when | Governs |
|---|---|---|
| `supervisor-startup-delivered.json` | **only on confirmed delivery** | deduplication |
| `supervisor-startup-attempts.json` | **every attempt**, either outcome | retry interval and bound |
| `supervisor-startup-legacy-assumption.json` | once, on upgrade | duplicate suppression, finite |

Splitting them is what lets a failed delivery stay eligible for retry while a
crash loop still cannot flood: retries are spaced 300s apart and bounded at 5
per episode. Every outcome, success or failure, is appended to
`supervisor-events.jsonl`.

**Episode state persists across restarts.** The failure count lives on disk, so
a crash loop does not get a fresh budget of retries every 60 seconds — an
in-memory counter would reset on exactly the event it must suppress. It resets
on a **confirmed success**, never on a process restart. (It also resets if an
episode lapses with no attempt at all, so one bad hour cannot permanently mute
the surface.)

## Process health and notifier health are independent axes

`supervisor_status.py` reports both, separately, and never lets one mask the
other. A healthy supervisor with a dead notification path is a real condition,
and collapsing the axes would hide a silent alerting failure behind a green
process.

| Notify state | Meaning |
|---|---|
| `confirmed` | Telegram acknowledged a real delivery |
| `legacy_assumed_confirmation` | a migrated marker is suppressing a duplicate — **not** a delivery |
| `unconfirmed` | never delivered, or the last attempt failed |
| `exhausted` | bounded retries spent without a confirmation |

**Installation does not fail the install on a degraded notifier.** The
supervisor is genuinely running, and uninstalling it would be the wrong remedy.
The installer prints a prominent warning block instead and reports the state in
its summary — a §19 alert nobody receives is worse than no alert at all, so it
is never allowed to pass silently.

**Live readiness is different.** Any live-readiness procedure — the §25
definition of done, a probation start, any owner activation — must require:

```bash
.venv/bin/python scripts/supervisor_status.py --require-notify-confirmed
```

exiting 0. See `governance/strategy-promotion-policy.md`.

## The legacy marker migration

An older build wrote `supervisor-startup-notify.json`, stamped on *attempt*.
Carrying that forward as a delivery would be a lie told by an upgrade. It is
therefore migrated **once** into an explicit
`legacy_assumed_confirmation` with:

- its own file and its own state, never the delivery marker;
- a **finite TTL** (1 hour), after which it expires and a real send runs,
  producing a real confirmation;
- an explicit `supervisor_startup_notify_legacy_assumption` event recording what
  was inherited, from when, and that it is not a confirmed delivery.

It does not satisfy `--require-notify-confirmed`.

## Manual repair: TLS trust store

**The installer will never modify your system certificates.** It detects the
problem, prints these steps, and stops. Changing a trust store affects every
program using that interpreter, so it stays an explicit owner action.

A python.org framework build ships **no root certificates**. `ssl.get_default_
verify_paths()` returns `None`, and every HTTPS call fails with
`CERTIFICATE_VERIFY_FAILED`. The trap is that this reads like a bad credential
in any preflight summary, when in fact the TLS handshake never completed and no
token was transmitted or evaluated.

Normally `/Applications/Python 3.11/Install Certificates.command` fixes this. If
that file is absent, do what it does:

```bash
/usr/local/bin/python3 -m pip install --upgrade certifi
```

```bash
mkdir -p /Library/Frameworks/Python.framework/Versions/3.11/etc/openssl && ln -sf "$(/usr/local/bin/python3 -c 'import certifi;print(certifi.where())')" /Library/Frameworks/Python.framework/Versions/3.11/etc/openssl/cert.pem
```

Installing `certifi` alone is **not** sufficient — OpenSSL looks for
`etc/openssl/cert.pem` inside the framework, and that path does not exist until
you create it. Recreate the virtualenv afterwards (or confirm it inherited the
fix) and verify:

```bash
.venv/bin/python scripts/check_runtime.py
```

## Why the plist pins an absolute interpreter

launchd runs with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`. `/usr/local/bin` is
absent, so `/usr/bin/env python3` resolves to the **macOS system Python**
(3.9.x) — below the §23 floor, without the project's dependencies, and without
whatever TLS repair was applied to the framework build. The failure is invisible
at install time and surfaces only as a crash loop. The plist therefore names
`__REPO_PATH__/.venv/bin/python`, which `install.sh` substitutes.

There is also deliberately **no `StartCalendarInterval`**: launchd calendar
times fire in the machine's local zone, which on a Chicago laptop reintroduces
finding C-2. The agent stays alive and the Python supervisor computes every
wakeup in `Europe/London` via `zoneinfo`.
