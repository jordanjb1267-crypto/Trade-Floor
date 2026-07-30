# Phase 4 audit record — practice order-lifecycle run (2026-07-30)

| | |
|---|---|
| **Environment** | Claude Code remote VM, fresh session on branch `claude/practice-lifecycle-evidence` (from `origin/main` @ `6dcd98e`) |
| **Method** | `scripts/broker_sandbox_lifecycle.py --confirm-demo-order` — the sole sanctioned order path for this validation (§0 iron rule 1); script unmodified |
| **Reference** | §22 Phase 4 "Demo lifecycle tests"; standing owner to-do in `governance/decision-log.md` |
| **Result** | **FAILED CLOSED — no order placed, no network contact.** `OANDA_DEMO_API_TOKEN` was not present in the environment; the transport refused construction before any network I/O. |

## Pre-run gate

- `pip install -e ".[dev]"` succeeded; `python3 -m pytest -q` → **219 passed** before any network-facing step.
- Token presence check (existence only; value never printed): environment
  variable `OANDA_DEMO_API_TOKEN` **not set**; untracked `.env` **absent**.
- Per the run directive, no token was requested from anyone and the
  chat-exposed token on the rotation list was not used. The attempt was
  recorded and the run stopped, as instructed.

## Exact command and complete output

Run at **2026-07-30T15:03:46Z**:

```
$ python3 scripts/broker_sandbox_lifecycle.py --confirm-demo-order
Traceback (most recent call last):
  File "/home/user/Trade-Floor/scripts/broker_sandbox_lifecycle.py", line 94, in <module>
    sys.exit(main())
             ^^^^^^
  File "/home/user/Trade-Floor/scripts/broker_sandbox_lifecycle.py", line 34, in main
    transport = OandaPracticeTransport()
                ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/user/Trade-Floor/src/trading_firm/execution/oanda_transport.py", line 43, in __init__
    raise RuntimeError("OANDA_DEMO_API_TOKEN not set (see .env.example; §17)")
RuntimeError: OANDA_DEMO_API_TOKEN not set (see .env.example; §17)
exit=1
```

No account IDs appear because no account was ever contacted; there is
nothing to redact.

## Verdict per lifecycle check

| Check | Result |
|---|---|
| Token available from environment (§17) | **FAIL (closed)** — transport refused construction |
| Account reachable | NOT RUN |
| Pricing fetched | NOT RUN |
| 1-unit EUR_USD market order filled | NOT RUN |
| Broker-held stop confirmed active (§0.9) | NOT RUN |
| Trade closed | NOT RUN |
| Account flat after lifecycle | NOT RUN |

**0/7 — the run did not reach the broker.** The fail-closed behavior
itself worked exactly as designed (§0 iron rule 3): missing credential →
immediate refusal before any network call, no partial state, no order.

## What unblocks the re-run

The standing to-do's prerequisites remain: a **rotated** practice token
(the chat-exposed one must not be used) placed in an untracked `.env` or
exported as `OANDA_DEMO_API_TOKEN` in the session environment, plus a VM
whose egress policy allows the OANDA practice host. With those in place,
re-run the exact command above from a clean checkout of `main` and append
the evidence to this record — do not edit this attempt (§0.11).
