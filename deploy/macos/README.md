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

**What refreshes readiness confirmation.** Every approved owner notification
that the API confirms — supervisor startup health, session-start health, the
daily session report, and any other §19 kind — refreshes the canonical
confirmation evidence (`state/ops/notifier-last-delivery.json`). They all route
through one `deliver()` function in `scripts/run_supervisor.py`, and the marker
is written strictly inside its success branch.

A delivery that fails, returns a non-success status, is skipped or suppressed
by the dedup/retry rules, or never runs because the notifier is disabled
refreshes **nothing**. Confirmation is evidence of a real delivery or it is not
evidence at all.

**Readiness still expires.** The marker holds a timestamp, not a flag. Once
`DELIVERY_CONFIRMED_TTL_SECONDS` (1 hour) passes with no newer successful
delivery, the surface returns to `unconfirmed` and the gate closes again. A
confirmation is never permanent — the point is to prove the notifier works
*now*, not that it once worked.

> Before 2026-08-03 only the startup delivery refreshed this, so a healthy
> supervisor that had been up more than an hour reported `unconfirmed` even
> while delivering session messages successfully. That was a false negative on
> a mandatory gate, which is how operators learn to distrust gates.

**Manual bypass is prohibited.** Do not hand-write, copy, back-date, or
`touch` the confirmation marker, and do not pass `--max-beat-age` or any other
flag to make a failing check appear to pass. If the gate is closed, the correct
response is to find out why the notifier is not delivering — start with
`scripts/verify_telegram.py` and `logs/supervisor-events.jsonl`, which records
every delivery outcome with its status code. Running `verify_telegram.py`
deliberately does **not** refresh readiness: a manually-run diagnostic must not
be able to satisfy a gate about the supervisor's own delivery path.

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

## Laptop-phase operational rule (§31.5) — read this before every session

**The MacBook must remain open and connected to AC power throughout the London
session**, unless you have deliberately provisioned an Apple-supported
closed-display configuration.

Closing the lid in a configuration that causes clamshell sleep **invalidates
the autonomous session**. This is not a style preference — it happened. On
2026-08-05 and 2026-08-06 the machine entered `Clamshell Sleep` and the
supervisor was suspended through repeated Sleep/DarkWake cycles; boundaries
executed up to **76 minutes late**, including the inviolate 11:00 flatten, and
the old validator reported both sessions as "nominal, 5/5 events clean".

The supervisor now launches under `caffeinate -si` (adding
`PreventSystemSleep` to the existing idle assertion). **That is defense in
depth, not permission.** An assertion is a request to macOS, and the incident
proved the machine can sleep anyway. The physical configuration is the control;
the assertion is a backstop.

What the runtime now does about it:

- **Pre-startup** checks what macOS can actually prove — AC power, both sleep
  assertions, and recent sleep history. It never claims to check lid state,
  because macOS does not reliably expose it. Failing any check marks the
  session **non-qualifying** for the stability gate.
- **During the session** a suspension detector compares wall-clock against
  monotonic progress. Time the monotonic clock did not see is suspension, and
  it marks the session degraded and non-qualifying.
- **Expired boundaries are never replayed as timely.** Every event is stamped
  with its real execution instant and compared to its scheduled instant, so a
  boundary reached late after a wake is classified LATE on its own evidence.
- **Entry eligibility consults the wall clock, never the handler**, so a
  suspended scheduler cannot extend the entry window past 10:30.

If AC power disappears mid-session the runtime records the power-state
failure, marks the session degraded and non-qualifying, alerts you, and remains
fail closed.

## Database operations: backup, migrate, verify, sweep

The database is never created as a side effect of a process starting.
`database/firm.sqlite` comes into existence only through the explicit command
below, and every future schema change repeats this exact sequence in this
exact order:

**1. Back up — if a database exists.** On a fresh installation this correctly
fails with "nothing to back up," and that is the *only* time skipping a backup
is acceptable (§30.1 rule 3):

```bash
.venv/bin/python scripts/db_backup.py
```

**2. Migrate explicitly.** Creates the file (and parent directory) if absent,
applies pending migrations in filename order, and prints what existed before,
what was applied, and the final ledger state. Idempotent — a second run is a
printed no-op:

```bash
.venv/bin/python scripts/db_migrate.py
```

**3. Verify.** Re-run the same command: it must print `no-op — already fully
migrated` and `integrity: ok`, and exit 0. A migration error instead leaves
the database at the last fully-applied migration and exits non-zero; restore
with `scripts/db_restore.py` if needed.

**4. Run the observe-only sweep.** The sweep reads fixtures and writes a JSON
report only — it neither initializes nor writes the SQLite database, and it
has no database argument by design:

```bash
.venv/bin/python scripts/run_surveillance_sweep.py --date 2026-07-29
```

Sweep reports land in `reports/ops/surveillance/` (gitignored runtime
output). None of these steps touch a feature flag, `live_allowed`, the
broker, or any runtime service.

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
