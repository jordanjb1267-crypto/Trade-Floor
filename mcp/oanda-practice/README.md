# OANDA Practice (Read-Only) — MCP bundle

A Claude Desktop extension (`.mcpb`) exposing **read-only** OANDA fxTrade
**Practice** tools for the Claude London Trading Firm project.

## Constitution constraints (governing spec §2, §17)

- **No order tools.** §2 prohibits any LLM-facing order path. This server has
  zero order-placement/modification/cancellation tools; it is GET-only.
  Execution belongs to the deterministic broker adapter, never to an MCP tool.
- **Practice host only.** `api-fxpractice.oanda.com` is hard-coded (§13
  staging). A live-account token gets a 401 and an explanatory error.
- **Credential isolation.** The token is entered once in the extension
  settings; Claude Desktop stores it in the OS keychain (`sensitive: true`)
  and injects it as an environment variable (§17). It is never logged.

## Tools

| Tool | Purpose |
|---|---|
| `oanda_list_accounts` | Accounts available on the token |
| `oanda_account_summary` | Balance, NAV, margin rate, hedging flag, open counts |
| `oanda_instruments` | Min trade size, unit precision, pip location, margin rate |
| `oanda_pricing` | Live bid/ask with spread computed in pips |
| `oanda_candles` | Historical candles (S5…M granularities, max 500) |
| `oanda_open_positions` | Read-only reconciliation view |
| `oanda_pending_orders` | Read-only reconciliation view |
| `oanda_recent_transactions` | Recent transaction audit view (max 50) |
| `oanda_connection_audit` | One-call §16 demo connection audit (PASS/FAIL per check) |

## Install (Claude Desktop on the laptop)

1. Get `oanda-practice-readonly.mcpb` (built from this directory).
2. Claude Desktop → **Settings → Extensions** → drag the `.mcpb` file in.
3. When prompted, paste your **practice** API token (fxTrade Practice →
   Manage API Access). It goes to the OS keychain, not to a file.
4. Ask Claude: *"Run the OANDA connection audit."*

## Build from source

```bash
cd mcp/oanda-practice
npx @anthropic-ai/mcpb pack . ../../dist/oanda-practice-readonly.mcpb
```

The server is a single dependency-free Node 18+ file
(`server/index.js`) — no `node_modules`, auditable in one sitting.

## Scope notes

- This bundle is for **Claude Desktop** (and other MCPB-compatible hosts) on
  your own machine. It does not grant cloud sessions network access to OANDA,
  and claude.ai web connectors require remote HTTP MCP servers instead.
- When the project reaches live probation (§13, Phase 7+), live-account access
  still does not go through an MCP server: reads stay practice/deterministic,
  and execution stays in the audited broker adapter service.
