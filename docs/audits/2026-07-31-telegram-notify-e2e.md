# §18 audit record — Telegram notification path, end-to-end (2026-07-31)

| | |
|---|---|
| **Environment** | Claude Code remote VM, fresh session on branch `claude/telegram-api-allowlist-hm22t2` (from `origin/main` @ `5d76b62`). Fresh container was required: the owner added `api.telegram.org` to the environment's network allowlist, and policy changes only reach new containers. |
| **Credentials** | `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` supplied by the owner as Claude Code environment variables (names recorded here; values never printed, §17). No `.env` file present. |
| **Method** | `scripts/verify_telegram_notify.py`, which exercises `trading_firm.notify.telegram` — the same module any future runtime caller will use. No mock; one real message. No broker contact; the notify package carries no order capability (§0 iron rule 1). |
| **Reference** | §18 minimum operational requirements — "Local notifications plus optional Telegram/Discord notification path"; §17 redaction rules |
| **Result** | **PASSED 2/2.** Bot identity confirmed and one real message delivered to the owner chat, with the server-assigned `message_id` returned as delivery evidence. |

## Pre-run gate

All five CI steps green before the network-facing step, same interpreter
(`python3` 3.11.15; the standalone `pytest` shim in this container is a
uv-isolated interpreter that cannot see the editable install — suite run as
`python3 -m pytest`):

- `python3 -m pytest -q` → **862 passed** (includes the 21 new
  `tests/unit/test_notify.py` cases: fail-closed preflight, token-leak
  containment, deterministic retry policy, truncation, redaction)
- `ruff check src tests scripts` → clean
- `python3 scripts/validate_config.py` → 1/1 layers valid, `live_allowed=EMPTY`
- `python3 scripts/check_spec_refs.py` → all 1814 §-references resolve
- `python3 scripts/check_spec_quotes.py` → all 33 attributed quotes verified

## Exact command and complete output

Run at **2026-07-31T02:37:27Z**:

```
$ python3 scripts/verify_telegram_notify.py
Credentials present: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 
(values never printed; §17). Target chat: 50…33

RESULT CHECK
PASS   getMe: token resolves to a live bot
       bot @Tradingfloorlondonbot reachable (status=200 attempts=1)
PASS   sendMessage: real message delivered to owner chat
       message_id=8 status=200 attempts=1 chat=50…33

2/2 checks passed. Notification path verified end-to-end.
exit=0
```

The delivered message body (composed by the script; contains nothing
sensitive; `{stamp}` is the script's own UTC clock at send time, within a
second of the run timestamp above):

```
Trade-Floor notification-path verification — {stamp}.
Deterministic notify module, end-to-end check from the Claude Code remote
environment. Research phase; no live trading; this is not a trade signal.
```

## Verdict per check

| Check | Result |
|---|---|
| Credential preflight (names present, no placeholder, token shape) | **PASS** — refused-before-network path unit-tested; live run proceeded |
| `getMe`: token resolves to a live bot | **PASS** — `@Tradingfloorlondonbot`, HTTP 200, attempt 1 |
| `sendMessage`: real delivery to owner chat | **PASS** — `message_id=8`, HTTP 200, attempt 1, chat `50…33` |

## Scope of evidence — what this run proves, and what it does not

Proves: egress from this environment's network policy to `api.telegram.org`
(DNS, TLS via the session CA bundle, proxy); the token is valid and the bot
live; the configured chat is reachable; and the deployed module code path —
preflight, request construction, response parsing, §17 output redaction —
works end to end under success conditions.

Does **not** prove: behavior under failure regimes (the retry/sanitization
paths are exercised by unit tests only); any latency guarantee; delivery
from the trading laptop's own network — §18's laptop deployment must re-run
this same script there; and no runtime caller is wired yet — nothing in the
incident or watchdog paths invokes `send()` today, so this validates the
channel, not its integration.

`message_id=8` implies prior traffic in this chat (ids 1–7 predate this
run — owner-side bot setup); only `message_id=8` is evidence from this run.

Nothing was unlocked by this audit: `live_allowed` remains empty everywhere.
