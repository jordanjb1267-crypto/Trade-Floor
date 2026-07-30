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

# Attempt 2 — appended 2026-07-30 (attempt 1 above is unedited, §0.11)

| | |
|---|---|
| **Environment** | Claude Code remote VM, branch `claude/oanda-token-env-f7asv9` (from `origin/main` @ `de0f7c2`) |
| **Trigger** | Owner reported "Oanda token added to environment" |
| **Method** | `scripts/broker_sandbox_lifecycle.py --confirm-demo-order`, script unmodified at the time of the attempt |
| **Result** | **FAILED CLOSED — no order placed.** Both OANDA variables are present but hold the literal placeholder text, not credentials. |

## What changed since attempt 1: network access

Prerequisite 1 of 2 is now **satisfied**. The practice host is reachable from
this VM — an unauthenticated probe returned a genuine OANDA response rather
than a connection failure:

```
HTTP 401
server hdr: cloudflare
via/proxy hdr: None None
body: {"errorMessage":"Insufficient authorization to perform request."}
```

The `Server: cloudflare` header, OANDA's own error schema, and the absence of
any proxy `Via` header together establish that this answer came from OANDA and
not from the egress proxy. Attempt 1's "no network contact" condition no longer
holds.

## What still blocks: the credential is a placeholder

Prerequisite 2 of 2 is **not** satisfied. Both variables are set, which is why
this looked like a resolved to-do, but their contents are placeholder notation
copied verbatim from the usage docstring / `.env.example`:

| Variable | Set? | Length | Content |
|---|---|---|---|
| `OANDA_DEMO_API_TOKEN` | yes | 16 | bracket-wrapped placeholder (`<practice token>`-shaped) |
| `OANDA_DEMO_ACCOUNT_ID` | yes | 4 | bracket-wrapped placeholder (`<id>`) |

Values were inspected by length and pattern only and are **not** reproduced
here or anywhere in the repository (§0 iron rule 5). Neither is a real
credential, so no token rotation has occurred and the chat-exposed token from
setup remains on the standing rotation list.

## Defect this attempt exposed (fixed in this change)

The pre-fix run failed with a materially **wrong** diagnosis:

```
$ python3 scripts/broker_sandbox_lifecycle.py --confirm-demo-order
  File ".../oanda_transport.py", line 84, in _first_account_id
    raise RuntimeError("no practice accounts on this token")
RuntimeError: no practice accounts on this token
```

Root cause: `_request` preserved **all** HTTP error bodies as ordinary
responses — correct for order rejections carrying `orderRejectTransaction`
(finding 5), wrong for authentication failures. A 401 therefore became
`{"errorMessage": ...}`, `_first_account_id` read `.get("accounts", [])` as an
empty list, and a rejected credential was reported as an account that does not
exist. An operator following that message would go create a practice account
they already have. `scripts/verify_oanda_demo.py` was differently misleading,
attributing the 401 to an invalid **or live** token without considering
misconfiguration.

Both now report the actual cause, before any request is sent:

```
$ python3 scripts/verify_oanda_demo.py
FAIL: OANDA_DEMO_API_TOKEN holds the literal placeholder from .env.example,
      not a real credential — substitute the practice value (§17). Nothing was sent.

$ python3 scripts/broker_sandbox_lifecycle.py --confirm-demo-order
Refusing to run: OANDA_DEMO_API_TOKEN holds the literal placeholder from
      .env.example, not a real credential — substitute the practice value (§17).
      Nothing was sent.
```

## Verdict per lifecycle check

| Check | Result |
|---|---|
| Token available from environment (§17) | **FAIL (closed)** — placeholder refused pre-flight |
| Account reachable | NOT RUN |
| Pricing fetched | NOT RUN |
| 1-unit EUR_USD market order filled | NOT RUN |
| Broker-held stop confirmed active (§0.9) | NOT RUN |
| Trade closed | NOT RUN |
| Account flat after lifecycle | NOT RUN |

**0/7 — the run did not reach the broker.** Fail-closed behavior held (§0 iron
rule 3): no order, no partial state. Phase 4's lifecycle run remains
outstanding.

## What unblocks the re-run

Exactly one thing now: a **rotated** fxTrade Practice token in
`OANDA_DEMO_API_TOKEN` (untracked `.env` or session environment), replacing the
placeholder. `OANDA_DEMO_ACCOUNT_ID` is optional — leave it unset to use the
first account on the token, or pin a real account id; the placeholder must be
removed either way. Network access no longer needs arranging. Re-run the exact
command above and append a third section — do not edit either attempt (§0.11).
