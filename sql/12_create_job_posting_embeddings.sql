-- 12_create_job_posting_embeddings.sql
-- Chunk-level vector store for job postings. Mirrors the weather-app
-- homework's weather_embeddings table exactly -- same reasoning applies:
-- job descriptions vary from a two-line RemoteOK blurb to a multi-page
-- federal qualification summary, so chunking matters for some sources and
-- is a no-op for others.
--
-- VECTOR(1024) matches databricks-gte-large-en, a Databricks Model Serving
-- Foundation Model API endpoint called over REST -- not a local model. See
-- config.py for why: a local sentence-transformers model pulls in torch,
-- and torch's compiled extensions are exactly the kind of thing that
-- crashes the Python kernel on Databricks serverless compute (SIGABRT),
-- including Free Edition, which is serverless-only. This was learned the
-- hard way on the weather-app homework; applied here from the start.

CREATE TABLE IF NOT EXISTS job_posting_embeddings (
    -- "<job_posting_id>#<chunk_index>", so re-embedding a posting
    -- overwrites its own chunks instead of duplicating them.
    id             TEXT PRIMARY KEY,

    job_posting_id TEXT NOT NULL
                   REFERENCES job_postings (id) ON DELETE CASCADE,

    chunk_index    INTEGER NOT NULL,
    chunk_text     TEXT NOT NULL,

    embedding      VECTOR(1024) NOT NULL,

    model_name     TEXT NOT NULL,

    -- Copied from job_postings.content_hash at embed time. A mismatch
    -- means the source posting's description changed since this vector
    -- was computed -- the embedding job re-embeds only these.
    content_hash   TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT job_posting_embeddings_posting_chunk_key
        UNIQUE (job_posting_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_job_posting_embeddings_posting_id
    ON job_posting_embeddings (job_posting_id);

CREATE INDEX IF NOT EXISTS idx_job_posting_embeddings_model_hash
    ON job_posting_embeddings (model_name, content_hash);

-- Approximate nearest-neighbour index for cosine distance. vector_cosine_ops
-- must match the <=> operator used at query time, or Postgres falls back
-- to a sequential scan.
CREATE INDEX IF NOT EXISTS idx_job_posting_embeddings_hnsw
    ON job_posting_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- On pgvector older than 0.5.0, drop the HNSW index above and use IVFFlat
-- instead (built *after* the table holds data, since it clusters existing
-- rows):
--
--   CREATE INDEX idx_job_posting_embeddings_ivfflat
--       ON job_posting_embeddings
--       USING ivfflat (embedding vector_cosine_ops)
--       WITH (lists = 100);

-- Verify the vector column really is VECTOR(1024).
SELECT column_name, data_type, udt_name
FROM information_schema.columns
WHERE table_name = 'job_posting_embeddings'
ORDER BY ordinal_position;
