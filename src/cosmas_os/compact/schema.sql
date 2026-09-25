-- Local-only additive extension v1. Core Alembic history is deliberately unchanged.
CREATE TABLE IF NOT EXISTS compact_schema_version (
    singleton integer PRIMARY KEY CHECK (singleton = 1),
    version integer NOT NULL CHECK (version = 1)
);
CREATE TABLE IF NOT EXISTS compact_claims (
    operation_id uuid PRIMARY KEY REFERENCES operations(id),
    token uuid NOT NULL,
    phase varchar(24) NOT NULL CHECK (phase IN ('claimed', 'dispatching', 'waiting', 'done', 'uncertain')),
    lease_until timestamptz NOT NULL,
    next_attempt_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS compact_synthetic_receipts (
    operation_id uuid PRIMARY KEY REFERENCES operations(id),
    box_id uuid NOT NULL REFERENCES box_contexts(id),
    request_hash varchar(64) NOT NULL,
    external_reference varchar(200) NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS compact_worker_heartbeats (
    box_id uuid PRIMARY KEY REFERENCES box_contexts(id),
    worker_id uuid NOT NULL,
    observed_at timestamptz NOT NULL
);
INSERT INTO compact_schema_version (singleton, version) VALUES (1, 1)
ON CONFLICT (singleton) DO NOTHING;
