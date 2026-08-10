-- Phase 4 persistent stale flag maintained by the scheduled pipeline.
ALTER TABLE applications
    ADD COLUMN IF NOT EXISTS is_stale BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS stale_flagged_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_applications_stale
    ON applications (user_id, is_stale) WHERE is_stale = true;

-- Phase 4 audit history for scheduled Spark ingestion/embedding runs.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id UUID PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    query_count INTEGER NOT NULL DEFAULT 0,
    fetched_rows INTEGER NOT NULL DEFAULT 0,
    prepared_rows INTEGER NOT NULL DEFAULT 0,
    synced_rows INTEGER NOT NULL DEFAULT 0,
    embedded_postings INTEGER NOT NULL DEFAULT 0,
    written_chunks INTEGER NOT NULL DEFAULT 0,
    stale_applications INTEGER NOT NULL DEFAULT 0,
    source_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
    ON pipeline_runs (started_at DESC);

SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name IN ('applications', 'pipeline_runs')
ORDER BY ordinal_position;
