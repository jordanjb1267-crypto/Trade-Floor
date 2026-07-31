-- 0001: core decision-trail entities (governing spec §10.2, Phase 2 subset).
-- Timestamps are ISO-8601 UTC text; source timezone preserved where relevant (§10.3).

CREATE TABLE IF NOT EXISTS configuration_versions (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    environment TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    closed_equity TEXT NOT NULL,          -- Decimal as text, never float (§10)
    nav TEXT,
    session_realized_loss TEXT NOT NULL DEFAULT '0',
    weekly_realized_loss TEXT NOT NULL DEFAULT '0',
    source TEXT NOT NULL                  -- 'broker' | 'reconciler'
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    instrument TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('LONG','SHORT')),
    entry_price TEXT NOT NULL,
    stop_price TEXT NOT NULL,
    edge_score INTEGER NOT NULL CHECK (edge_score BETWEEN 0 AND 100),
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id),
    ts TEXT NOT NULL,
    approved INTEGER NOT NULL CHECK (approved IN (0,1)),
    tier TEXT NOT NULL,
    allowed_risk_usd TEXT NOT NULL,
    binding_constraint TEXT,
    reasons_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capital_tier_events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('armed','approved','lapsed','contracted')),
    from_anchor TEXT NOT NULL,
    to_anchor TEXT NOT NULL,
    owner_approved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    trigger TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_candidates_created ON candidates(created_at);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_ts ON risk_decisions(ts);
CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(type);
