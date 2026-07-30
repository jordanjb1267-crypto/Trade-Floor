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

---

# Attempt 2 — 2026-07-30T18:26:43Z — **PASS (6/6)**

The first attempt above is preserved unedited (§0.11). This section records
the completed run.

| | |
|---|---|
| **Environment** | Claude Code remote VM, branch `claude/env-loading-and-eur-extension` (from `origin/main` @ `de0f7c2`) |
| **Method** | `scripts/broker_sandbox_lifecycle.py --confirm-demo-order`, unmodified apart from the `.env` load added this session; the sole sanctioned order path (§0 iron rule 1) |
| **Credential** | Rotated practice token supplied via the session environment as `OANDA_DEMO_API_TOKEN`. Verified by hash to be **different** from the token that passed through chat (that one remains on the rotation list). Never printed, logged, or committed. |
| **Result** | **6/6 checks PASS** — order placed, stop verified, trade closed, account flat |

## Pre-run gate

`python3 -m pytest -q` → 262 passed; `ruff check src tests scripts` clean,
both before the network call.

## Exact command and complete output

```
$ date -u +"%Y-%m-%dT%H:%M:%SZ"
2026-07-30T18:26:43Z
$ python3 scripts/broker_sandbox_lifecycle.py --confirm-demo-order

RESULT CHECK
PASS   account reachable
       balance=99999.9998
PASS   pricing fetched
       bid=1.15260
PASS   1-unit market order filled
       {'orderCreateTransaction': {'id': '10', 'accountID': '101-001-…-001', 'userID': …, 'batchID': '10', 'requestID': '…', 'time': '20
PASS   broker-held stop confirmed active (§0.9)
       stop={'id': '12', 'createTime': '2026-07-30T18:26:45.082814971Z', 'type': 'STOP_LOSS', 'tradeID': '11', 'price': '1.14760', 'timeInForce': 'GTC', 'triggerCondition': 'DEFAULT', 'triggerMode': 'TOP_OF_BOOK', 'state': 'PENDING'}
PASS   trade closed
       {'orderCreateTransaction': {'id': '13', 'accountID': '101-001-…-001', 'userID': …, 'batchID': '13', 'reque
PASS   account flat after lifecycle

6/6 lifecycle checks passed.
exit=0
```

Account id and user id are redacted above beyond the broker-environment
prefix; the script prints raw transaction dicts, so redaction here is
manual and deliberate. No token appears in the output.

## Verdict per lifecycle check

| Check | Result | Evidence |
|---|---|---|
| Account reachable (practice host) | **PASS** | balance 99999.9998 returned |
| Pricing fetched | **PASS** | EUR_USD closeout bid 1.15260 |
| 1-unit EUR_USD market order filled | **PASS** | fill transaction, trade id 11 |
| Broker-held stop confirmed active (§0.9) | **PASS** | STOP_LOSS id 12 @ 1.14760, GTC, state PENDING, bound to trade 11 |
| Trade closed | **PASS** | closing fill transaction id 13 |
| Account flat after lifecycle | **PASS** | no open trade ids remain |

**6/6 — the §22 Phase 4 "demo lifecycle tests" deliverable is satisfied.**
The stop was broker-held and price-exact (bid 1.15260 − 50 pips = 1.14760),
confirming §0.9 end-to-end against the real venue rather than the fake
broker — the integration truth the 21-finding adversarial review said unit
tests against a friendly fake could not provide.

Scope limits, stated plainly: this validates **transport and order
mechanics only**. It is not a strategy trade, spends no §12.4 test, and
says nothing about fill quality or slippage — practice-feed caveat F-5
still stands, and live re-audit (F-2) remains a Phase 7 gate.
