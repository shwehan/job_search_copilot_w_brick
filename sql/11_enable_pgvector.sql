-- 11_enable_pgvector.sql
-- Run this first for Phase 2, against your Lakebase Postgres database.
--
-- pgvector provides the VECTOR column type, the cosine-distance operator
-- <=>, and the HNSW index access method that the retrieval endpoint
-- depends on.

CREATE EXTENSION IF NOT EXISTS vector;

-- Confirm the extension is available and note its version. HNSW indexes
-- require pgvector 0.5.0 or newer.
SELECT extname AS extension, extversion AS version
FROM pg_extension
WHERE extname = 'vector';
