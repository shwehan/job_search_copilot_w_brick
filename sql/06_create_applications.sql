-- 06_create_applications.sql
-- The formal pipeline: once a posting is deliberately being pursued (not
-- just bookmarked -- see saved_jobs in the next file), it gets an
-- applications row and moves through a fixed stage machine.
--
-- One row per (user, job_posting) — re-applying isn't modeled as a new row,
-- it's a stage transition on the existing one, which is what makes
-- stage_updated_at meaningful for stale-application detection later.

CREATE TABLE IF NOT EXISTS applications (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id           UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    profile_id        UUID REFERENCES profiles (id) ON DELETE SET NULL,
    job_posting_id    TEXT NOT NULL REFERENCES job_postings (id) ON DELETE CASCADE,

    stage             TEXT NOT NULL DEFAULT 'saved'
                      CHECK (stage IN ('saved', 'applied', 'interviewing', 'rejected', 'offer')),
    stage_updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at        TIMESTAMPTZ,

    match_score       NUMERIC,          -- populated once scoring exists (Phase 2/6)
    match_reasoning   TEXT,

    notes             TEXT,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT applications_user_job_key UNIQUE (user_id, job_posting_id)
);

CREATE INDEX IF NOT EXISTS idx_applications_user_stage ON applications (user_id, stage);
CREATE INDEX IF NOT EXISTS idx_applications_stage_updated_at ON applications (stage_updated_at);

-- REPLICA IDENTITY FULL is what Lakebase's Change Data Feed requires on a
-- table before it can stream row-level changes to Unity Catalog. Enabled
-- here so the table is ready the moment the Phase 1 CDF spike (see the
-- capstone plan) gets a "yes" -- if it doesn't, this line is simply unused
-- and harmless.
ALTER TABLE applications REPLICA IDENTITY FULL;

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'applications'
ORDER BY ordinal_position;
