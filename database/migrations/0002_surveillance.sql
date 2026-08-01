-- 0002: Global Market Intelligence and Surveillance Division (§30, A-3).
-- Additive only: no existing table is modified except one nullable column on
-- candidates (§30.14); nothing is dropped, no row is touched. Rollback paths,
-- in preference order: surveillance.enabled=false leaves every table here
-- empty and inert; scripts/db_restore.py returns to the pre-migration backup.
-- Conventions from 0001: ISO-8601 UTC text timestamps, Decimals as text,
-- CHECK-constrained vocabularies, payload_json for reproducibility (§30.1).

-- §30.8: per-source health transitions. The registry file itself is hashed
-- into the existing configuration_versions table — no duplicate concept.
CREATE TABLE IF NOT EXISTS source_health_events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    source_id TEXT NOT NULL,
    prior_state TEXT NOT NULL CHECK (prior_state IN ('HEALTHY','DEGRADED','FAILED','UNKNOWN')),
    new_state TEXT NOT NULL CHECK (new_state IN ('HEALTHY','DEGRADED','FAILED','UNKNOWN')),
    detail_json TEXT NOT NULL
);

-- §30.4 macro component inputs: scheduled events, versioned per revision so a
-- corrected release time never overwrites the record a decision was made on.
CREATE TABLE IF NOT EXISTS economic_events (
    event_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    name TEXT NOT NULL,
    scheduled_utc TEXT NOT NULL,
    importance TEXT NOT NULL CHECK (importance IN ('low','medium','high')),
    forecast TEXT,
    prior TEXT,
    actual TEXT,
    released_utc TEXT,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (event_id, version)
);

-- §30.8 news: original timestamps preserved; the content hash is the dedup
-- key (duplicate storms collapse instead of alerting repeatedly, §30.6).
CREATE TABLE IF NOT EXISTS news_items (
    news_item_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL UNIQUE,
    headline TEXT NOT NULL,
    event_time_utc TEXT,
    publication_time_utc TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    supersedes_id TEXT REFERENCES news_items(news_item_id),
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_item_sources (
    id INTEGER PRIMARY KEY,
    news_item_id TEXT NOT NULL REFERENCES news_items(news_item_id),
    source_id TEXT NOT NULL,
    source_published_utc TEXT,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_verification_events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    news_item_id TEXT NOT NULL REFERENCES news_items(news_item_id),
    verification_state TEXT NOT NULL CHECK (verification_state IN
        ('UNVERIFIED','SINGLE_SOURCE','CORROBORATED','OFFICIAL_SOURCE',
         'CONFLICTING','CORRECTED','RETRACTED')),
    detail_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cross_market_observations (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    relationship_version TEXT NOT NULL,
    observation_json TEXT NOT NULL
);

-- §30.4 identity: deterministic feature inputs snapshotted so a Market State
-- Object is reproducible from stored inputs and versioned logic (§30.1).
CREATE TABLE IF NOT EXISTS feature_snapshots (
    feature_snapshot_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    checksum TEXT NOT NULL
);

-- §30.4: append-only. market_state_id IS the content checksum; corrections
-- are replacement rows linked by supersedes_market_state_id, never updates.
CREATE TABLE IF NOT EXISTS market_states (
    market_state_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    valid_until_utc TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    dq_status TEXT NOT NULL CHECK (dq_status IN ('HEALTHY','DEGRADED','FAILED')),
    prior_market_state_id TEXT,
    supersedes_market_state_id TEXT,
    stale_components_json TEXT NOT NULL,
    missing_components_json TEXT NOT NULL,
    conflicting_components_json TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

-- §30.6: the durable outbox — every envelope field, nothing else.
CREATE TABLE IF NOT EXISTS surveillance_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    event_time_utc TEXT NOT NULL,
    ingestion_time_utc TEXT NOT NULL,
    producer TEXT NOT NULL,
    instrument_scope TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    data_quality TEXT NOT NULL CHECK (data_quality IN ('HEALTHY','DEGRADED','FAILED')),
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL
);

-- §30.6 alert discipline: acknowledgement and escalation live as columns —
-- a join table would model a multi-operator workflow this deployment
-- does not have (single laptop, single owner).
CREATE TABLE IF NOT EXISTS surveillance_alerts (
    alert_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    market_state_id TEXT REFERENCES market_states(market_state_id),
    severity TEXT NOT NULL CHECK (severity IN ('INFO','WATCH','MATERIAL','CRITICAL')),
    change_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    supersedes_alert_id TEXT REFERENCES surveillance_alerts(alert_id),
    ack_state TEXT NOT NULL DEFAULT 'unacknowledged'
        CHECK (ack_state IN ('unacknowledged','acknowledged')),
    ack_at TEXT,
    escalation_state TEXT NOT NULL DEFAULT 'none'
        CHECK (escalation_state IN ('none','senior_traders','arbiter','cro','owner')),
    delivered_to_owner INTEGER NOT NULL DEFAULT 0 CHECK (delivered_to_owner IN (0,1)),
    expires_at_utc TEXT,
    payload_json TEXT NOT NULL
);

-- §30.5: the packet handed identically to Alpha and Beta, retained so the
-- exact packet behind any candidate is reproducible (§30.4 immutability).
CREATE TABLE IF NOT EXISTS market_state_packets (
    packet_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    market_state_id TEXT NOT NULL REFERENCES market_states(market_state_id),
    prior_market_state_id TEXT,
    checksum TEXT NOT NULL,
    components_json TEXT NOT NULL
);

-- §30.10: registered before entry, immutable after (no exit-rule invention).
CREATE TABLE IF NOT EXISTS thesis_monitoring_plans (
    monitoring_plan_id TEXT PRIMARY KEY,
    candidate_id INTEGER REFERENCES candidates(id),
    schema_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    flatten_boundary_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_contradictions (
    contradiction_id TEXT PRIMARY KEY,
    monitoring_plan_id TEXT NOT NULL REFERENCES thesis_monitoring_plans(monitoring_plan_id),
    ts TEXT NOT NULL,
    classification TEXT NOT NULL CHECK (classification IN
        ('confirmation','noise','soft_contradiction','hard_invalidation',
         'time_expired','event_invalidated','execution_degraded','data_health')),
    escalation TEXT NOT NULL CHECK (escalation IN
        ('none','senior_traders','arbiter','cro','owner')),
    market_state_id TEXT REFERENCES market_states(market_state_id),
    evidence_json TEXT NOT NULL
);

-- §30.13: validated agent outputs, queryable (audit_events stays the hash
-- chain; this is the review store the chain entries point into).
CREATE TABLE IF NOT EXISTS surveillance_agent_reviews (
    review_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN
        ('surveillance_situation_report','opportunity_alert','news_relevance_review')),
    market_state_id TEXT REFERENCES market_states(market_state_id),
    payload_json TEXT NOT NULL
);

-- §30.14: candidates reference the packet they were built on. Nullable, so
-- every pre-amendment row remains valid; the remaining reference ids travel
-- in the existing payload_json.
ALTER TABLE candidates ADD COLUMN market_state_packet_id TEXT;

-- §30 indexing: the measured-need set only (the amendment warns against
-- premature indexing on laptop write throughput).
CREATE INDEX IF NOT EXISTS idx_market_states_instrument_asof
    ON market_states(instrument_id, as_of_utc);
CREATE INDEX IF NOT EXISTS idx_surveillance_events_type_time
    ON surveillance_events(event_type, event_time_utc);
CREATE INDEX IF NOT EXISTS idx_source_health_source_ts
    ON source_health_events(source_id, ts);
CREATE INDEX IF NOT EXISTS idx_news_items_content_hash
    ON news_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_economic_events_scheduled
    ON economic_events(scheduled_utc);
CREATE INDEX IF NOT EXISTS idx_candidates_packet
    ON candidates(market_state_packet_id);
