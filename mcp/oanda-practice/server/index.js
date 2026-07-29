#!/usr/bin/env node
/**
 * OANDA Practice (Read-Only) — MCP stdio server.
 *
 * Constitution constraints (Master Handoff v1.1.0):
 *  - §2  Prohibited architecture: no LLM-facing order path. This server exposes
 *        ZERO order-placement/modification/cancellation tools. GET-only.
 *  - §13 Staging: the PRACTICE host is hard-coded. This server cannot reach
 *        the live host (api-fxtrade.oanda.com) by design.
 *  - §17 Credential isolation: the token arrives via the OANDA_PRACTICE_API_TOKEN
 *        environment variable, injected by Claude Desktop from keychain-backed
 *        user_config. It is never logged or echoed by any tool.
 *
 * Dependency-free on purpose: one auditable file, MCP stdio JSON-RPC done by
 * hand (newline-delimited JSON messages). Requires Node 18+ (global fetch).
 */

"use strict";

const HOST = "https://api-fxpractice.oanda.com"; // practice ONLY — do not change (§13)
const DEFAULT_INSTRUMENTS = ["GBP_USD", "EUR_USD"];
const PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"];

const token = process.env.OANDA_PRACTICE_API_TOKEN;
let cachedAccountId = null;

// ---------------------------------------------------------------- OANDA client

async function oandaGet(path) {
  if (!token) {
    throw new Error(
      "OANDA_PRACTICE_API_TOKEN is not set. Configure the token in the " +
        "extension settings (it is stored in the OS keychain)."
    );
  }
  let res;
  try {
    res = await fetch(HOST + path, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch (err) {
    throw new Error(
      `Network error reaching ${HOST}: ${err.message}. Check connectivity; ` +
        "this server only talks to the OANDA practice host."
    );
  }
  if (res.status === 401) {
    throw new Error(
      "401 Unauthorized from the PRACTICE host. The token is invalid or " +
        "belongs to a LIVE account. Generate a personal access token from " +
        "your fxTrade Practice account and update the extension settings. " +
        "This server will not talk to the live host."
    );
  }
  if (!res.ok) {
    const body = (await res.text()).slice(0, 300);
    throw new Error(`OANDA HTTP ${res.status} on ${path}: ${body}`);
  }
  return res.json();
}

async function resolveAccountId(args) {
  if (args && typeof args.account_id === "string" && args.account_id) {
    return args.account_id;
  }
  if (!cachedAccountId) {
    const { accounts } = await oandaGet("/v3/accounts");
    if (!accounts || accounts.length === 0) {
      throw new Error("No accounts found on this token.");
    }
    cachedAccountId = accounts[0].id;
  }
  return cachedAccountId;
}

function pipLocationFor(instrument) {
  return instrument.endsWith("_JPY") ? -2 : -4;
}

function spreadInPips(instrument, bid, ask) {
  return (ask - bid) / Math.pow(10, pipLocationFor(instrument));
}

// --------------------------------------------------------------------- tools

const ACCOUNT_ID_PROP = {
  account_id: {
    type: "string",
    description:
      "OANDA account id. Omit to use the first account on the token.",
  },
};

const TOOLS = [
  {
    name: "oanda_list_accounts",
    description:
      "List OANDA practice accounts available on the configured token (ids and tags).",
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
    handler: async () => oandaGet("/v3/accounts"),
  },
  {
    name: "oanda_account_summary",
    description:
      "Account summary: balance, NAV, unrealized P&L, margin used/available, margin rate " +
      "(leverage), hedging flag, open trade/position counts, last transaction id.",
    inputSchema: {
      type: "object",
      properties: { ...ACCOUNT_ID_PROP },
      additionalProperties: false,
    },
    handler: async (args) => {
      const id = await resolveAccountId(args);
      return oandaGet(`/v3/accounts/${id}/summary`);
    },
  },
  {
    name: "oanda_instruments",
    description:
      "Instrument specs for the account: minimum trade size, trade-unit precision, pip " +
      "location, margin rate, max order units. Defaults to GBP_USD and EUR_USD.",
    inputSchema: {
      type: "object",
      properties: {
        ...ACCOUNT_ID_PROP,
        instruments: {
          type: "array",
          items: { type: "string" },
          description: 'Instrument names like "GBP_USD". Default: GBP_USD, EUR_USD.',
        },
      },
      additionalProperties: false,
    },
    handler: async (args) => {
      const id = await resolveAccountId(args);
      const list = (args.instruments && args.instruments.length
        ? args.instruments
        : DEFAULT_INSTRUMENTS
      ).join(",");
      return oandaGet(`/v3/accounts/${id}/instruments?instruments=${encodeURIComponent(list)}`);
    },
  },
  {
    name: "oanda_pricing",
    description:
      "Live bid/ask pricing with computed spread in pips. Defaults to GBP_USD and EUR_USD.",
    inputSchema: {
      type: "object",
      properties: {
        ...ACCOUNT_ID_PROP,
        instruments: {
          type: "array",
          items: { type: "string" },
          description: 'Instrument names like "GBP_USD". Default: GBP_USD, EUR_USD.',
        },
      },
      additionalProperties: false,
    },
    handler: async (args) => {
      const id = await resolveAccountId(args);
      const list = (args.instruments && args.instruments.length
        ? args.instruments
        : DEFAULT_INSTRUMENTS
      ).join(",");
      const data = await oandaGet(
        `/v3/accounts/${id}/pricing?instruments=${encodeURIComponent(list)}`
      );
      for (const p of data.prices || []) {
        const bid = parseFloat(p.bids?.[0]?.price);
        const ask = parseFloat(p.asks?.[0]?.price);
        if (Number.isFinite(bid) && Number.isFinite(ask)) {
          p.spread_pips = Number(spreadInPips(p.instrument, bid, ask).toFixed(2));
        }
      }
      return data;
    },
  },
  {
    name: "oanda_candles",
    description:
      "Historical candles for an instrument. Granularities: S5..M1,M5,M15,M30,H1,H4,D,W,M. " +
      "Use price 'M' (mid), 'B' (bid), 'A' (ask), or combinations like 'BA'.",
    inputSchema: {
      type: "object",
      properties: {
        instrument: { type: "string", description: 'e.g. "GBP_USD"' },
        granularity: {
          type: "string",
          description: "Candle granularity, default M15.",
          enum: ["S5", "S10", "S30", "M1", "M2", "M5", "M15", "M30", "H1", "H2", "H4", "H8", "D", "W", "M"],
        },
        count: {
          type: "integer",
          minimum: 1,
          maximum: 500,
          description: "Number of candles (max 500). Ignored if both from and to are set.",
        },
        from: { type: "string", description: "RFC3339 start time (optional)." },
        to: { type: "string", description: "RFC3339 end time (optional)." },
        price: { type: "string", description: "M, B, A or combination. Default M." },
      },
      required: ["instrument"],
      additionalProperties: false,
    },
    handler: async (args) => {
      const params = new URLSearchParams();
      params.set("granularity", args.granularity || "M15");
      params.set("price", args.price || "M");
      if (args.from) params.set("from", args.from);
      if (args.to) params.set("to", args.to);
      if (args.count && !(args.from && args.to)) params.set("count", String(args.count));
      return oandaGet(`/v3/instruments/${encodeURIComponent(args.instrument)}/candles?${params}`);
    },
  },
  {
    name: "oanda_open_positions",
    description: "Open positions on the account (read-only reconciliation view).",
    inputSchema: {
      type: "object",
      properties: { ...ACCOUNT_ID_PROP },
      additionalProperties: false,
    },
    handler: async (args) => {
      const id = await resolveAccountId(args);
      return oandaGet(`/v3/accounts/${id}/openPositions`);
    },
  },
  {
    name: "oanda_pending_orders",
    description: "Pending orders on the account (read-only reconciliation view).",
    inputSchema: {
      type: "object",
      properties: { ...ACCOUNT_ID_PROP },
      additionalProperties: false,
    },
    handler: async (args) => {
      const id = await resolveAccountId(args);
      return oandaGet(`/v3/accounts/${id}/pendingOrders`);
    },
  },
  {
    name: "oanda_recent_transactions",
    description:
      "Most recent transactions on the account (default 20, max 50): orders, fills, " +
      "funding, admin events. Read-only audit view.",
    inputSchema: {
      type: "object",
      properties: {
        ...ACCOUNT_ID_PROP,
        count: { type: "integer", minimum: 1, maximum: 50, description: "Default 20." },
      },
      additionalProperties: false,
    },
    handler: async (args) => {
      const id = await resolveAccountId(args);
      const summary = await oandaGet(`/v3/accounts/${id}/summary`);
      const last = parseInt(summary.lastTransactionID, 10);
      if (!Number.isFinite(last) || last < 1) return { transactions: [] };
      const count = Math.min(args.count || 20, 50);
      const from = Math.max(1, last - count + 1);
      return oandaGet(`/v3/accounts/${id}/transactions/idrange?from=${from}&to=${last}`);
    },
  },
  {
    name: "oanda_connection_audit",
    description:
      "Run the Master Handoff §16 demo connection audit: token accepted, USD account, " +
      "margin rate vs the US 50:1 cap, hedging disabled (FIFO), 1-unit granularity on " +
      "GBP_USD/EUR_USD, live spread sanity. Returns PASS/FAIL per check.",
    inputSchema: {
      type: "object",
      properties: { ...ACCOUNT_ID_PROP },
      additionalProperties: false,
    },
    handler: async (args) => {
      const id = await resolveAccountId(args);
      const checks = [];
      const push = (check, pass, detail) => checks.push({ check, pass, detail });

      const summary = (await oandaGet(`/v3/accounts/${id}/summary`)).account;
      push("API reachable, token accepted (practice)", true, HOST);
      push("Account currency is USD", summary.currency === "USD", `currency=${summary.currency}`);
      const marginRate = parseFloat(summary.marginRate);
      push(
        "Margin rate consistent with US 50:1 majors cap",
        marginRate >= 0.02,
        `marginRate=${summary.marginRate} (leverage ${(1 / marginRate).toFixed(0)}:1)`
      );
      push(
        "Hedging disabled (NFA FIFO expectation)",
        summary.hedgingEnabled === false,
        `hedgingEnabled=${summary.hedgingEnabled}`
      );

      const instruments = (
        await oandaGet(
          `/v3/accounts/${id}/instruments?instruments=${DEFAULT_INSTRUMENTS.join(",")}`
        )
      ).instruments;
      for (const name of DEFAULT_INSTRUMENTS) {
        const inst = instruments.find((i) => i.name === name);
        if (!inst) {
          push(`${name} tradeable on account`, false, "not returned");
          continue;
        }
        push(
          `${name}: 1-unit granularity`,
          parseFloat(inst.minimumTradeSize) <= 1 && parseInt(inst.tradeUnitsPrecision, 10) === 0,
          `minimumTradeSize=${inst.minimumTradeSize} tradeUnitsPrecision=${inst.tradeUnitsPrecision} marginRate=${inst.marginRate}`
        );
      }

      const pricing = await oandaGet(
        `/v3/accounts/${id}/pricing?instruments=${DEFAULT_INSTRUMENTS.join(",")}`
      );
      for (const p of pricing.prices || []) {
        const bid = parseFloat(p.bids?.[0]?.price);
        const ask = parseFloat(p.asks?.[0]?.price);
        const spread = spreadInPips(p.instrument, bid, ask);
        push(
          `${p.instrument}: live pricing, spread sane (< 3 pips)`,
          spread > 0 && spread < 3,
          `bid=${bid} ask=${ask} spread=${spread.toFixed(1)} pips tradeable=${p.tradeable}`
        );
      }

      const failures = checks.filter((c) => !c.pass).length;
      return {
        result: failures === 0 ? "PASS" : "FAIL",
        passed: checks.length - failures,
        total: checks.length,
        checks,
      };
    },
  },
];

// ------------------------------------------------------- MCP stdio transport

function send(msg) {
  process.stdout.write(JSON.stringify(msg) + "\n");
}

function toolResult(id, payload, isError = false) {
  send({
    jsonrpc: "2.0",
    id,
    result: {
      content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
      isError,
    },
  });
}

async function handle(msg) {
  const { id, method, params } = msg;
  if (method === "initialize") {
    const requested = params?.protocolVersion;
    send({
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: PROTOCOL_VERSIONS.includes(requested)
          ? requested
          : PROTOCOL_VERSIONS[PROTOCOL_VERSIONS.length - 1],
        capabilities: { tools: {} },
        serverInfo: { name: "oanda-practice-readonly", version: "0.1.0" },
      },
    });
  } else if (method === "notifications/initialized" || (method || "").startsWith("notifications/")) {
    // notifications need no response
  } else if (method === "ping") {
    send({ jsonrpc: "2.0", id, result: {} });
  } else if (method === "tools/list") {
    send({
      jsonrpc: "2.0",
      id,
      result: {
        tools: TOOLS.map(({ name, description, inputSchema }) => ({
          name,
          description,
          inputSchema,
          annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: true },
        })),
      },
    });
  } else if (method === "tools/call") {
    const tool = TOOLS.find((t) => t.name === params?.name);
    if (!tool) {
      send({
        jsonrpc: "2.0",
        id,
        error: { code: -32602, message: `Unknown tool: ${params?.name}` },
      });
      return;
    }
    try {
      toolResult(id, await tool.handler(params?.arguments || {}));
    } catch (err) {
      toolResult(id, { error: err.message }, true);
    }
  } else if (id !== undefined) {
    send({ jsonrpc: "2.0", id, error: { code: -32601, message: `Method not found: ${method}` } });
  }
}

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let nl;
  while ((nl = buffer.indexOf("\n")) !== -1) {
    const line = buffer.slice(0, nl).trim();
    buffer = buffer.slice(nl + 1);
    if (!line) continue;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
      continue;
    }
    handle(msg).catch((err) => {
      if (msg.id !== undefined) {
        send({ jsonrpc: "2.0", id: msg.id, error: { code: -32603, message: err.message } });
      }
    });
  }
});
process.stdin.on("end", () => process.exit(0));
