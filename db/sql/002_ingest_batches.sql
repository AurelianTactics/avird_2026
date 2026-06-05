-- ingest_batches: one row per file load. Makes monthly refreshes auditable
-- and powers the sha256 double-ingest guard. ingested_at is an ISO-8601 TEXT
-- timestamp (portable across sqlite + Postgres, orderable lexicographically).
CREATE TABLE IF NOT EXISTS ingest_batches (
    "batch_id"       TEXT PRIMARY KEY,
    "source_file"    TEXT NOT NULL,
    "sha256"         TEXT NOT NULL,
    "row_count"      INTEGER NOT NULL,
    "schema_version" TEXT NOT NULL,
    "ingested_at"    TEXT NOT NULL,
    "notes"          TEXT
);
