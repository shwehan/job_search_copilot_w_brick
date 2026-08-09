-- 07_create_saved_jobs.sql
-- Lightweight bookmarks, deliberately kept separate from `applications`.
--
-- The distinction is intent, not just naming: saved_jobs is for browsing —
-- one click while scanning search results, no commitment, no stage
-- machine, cheap to bulk-add many at once. applications.stage = 'saved' is
-- a heavier, single-item action: "I've decided to seriously track this."
-- A posting can be bookmarked here without ever entering the formal
-- pipeline at all.

CREATE TABLE IF NOT EXISTS saved_jobs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    job_posting_id TEXT NOT NULL REFERENCES job_postings (id) ON DELETE CASCADE,
    note           TEXT,
    saved_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT saved_jobs_user_job_key UNIQUE (user_id, job_posting_id)
);

CREATE INDEX IF NOT EXISTS idx_saved_jobs_user_id ON saved_jobs (user_id);

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'saved_jobs'
ORDER BY ordinal_position;
