-- pgvector store for narrative RAG (plan P2, U8).
--
-- Enables the `vector` extension and creates the table the RAG retriever queries
-- by cosine distance (`embedding <=> $1`). The 768 dimension matches the
-- BAAI/bge-base-en-v1.5 embeddings already cached under data/embeddings/.
--
-- Idempotent; safe to re-run. `incident_id` and `narrative` come from re-deriving
-- the deduped canonical rows (the embedding cache stores neither — see
-- apps/api/app/rag/ingest.py), the vector from the cache.
--
--   psql "$DATABASE_URL" -f db/pgvector_setup.sql
--
-- RESOLVED (2026-07-01, plan Open Questions): `CREATE EXTENSION vector` FAILS on
-- the local Windows PG 17 (no vector.control shipped). Per KTD-3 the in-memory
-- retrieval fallback (rag/store.py) is therefore the LOCAL default — set
-- RAG_STORE=memory for the api service locally. This script is the
-- Railway/production path; confirm the extension on Railway PG 16 before any
-- live exposure (`SELECT * FROM pg_available_extensions WHERE name='vector'`).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS narrative_embeddings (
    incident_id text PRIMARY KEY,
    embedding   vector(768) NOT NULL,
    narrative   text NOT NULL
);

-- Cosine-distance ANN index. ivfflat needs ANALYZE after a bulk load to pick
-- list counts; for the corpus sizes here a flat scan is also fine.
CREATE INDEX IF NOT EXISTS narrative_embeddings_cos_idx
    ON narrative_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
