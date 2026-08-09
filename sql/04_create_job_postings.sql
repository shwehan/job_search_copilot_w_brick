-- 04_create_job_postings.sql
-- Normalized documents harvested from three sources: Adzuna, USAJobs, and
-- RemoteOK. One row per posting, regardless of source, so retrieval and the
-- rest of the app never need to know which API a listing came from.
--
-- Mirrors the id/content_hash/payload pattern used for the weather-app
-- homework: a stable dedup key, a hash of the embeddable text for
-- re-embed-only-what-changed in Phase 2, and the raw source response kept
-- for provenance. No embedding column yet — added in Phase 2.

CREATE TABLE IF NOT EXISTS job_postings (
    -- '<source>:<external_id>', e.g. 'adzuna:126977586' or
    -- 'usajobs:21947200' or 'remoteok:1136299'.
    id               TEXT PRIMARY KEY,

    source           TEXT NOT NULL CHECK (source IN ('adzuna', 'usajobs', 'remoteok')),
    external_id      TEXT NOT NULL,

    title            TEXT NOT NULL,
    company          TEXT,
    location         TEXT,
    remote           BOOLEAN,

    salary_min       NUMERIC,
    salary_max       NUMERIC,
    salary_currency  TEXT DEFAULT 'USD',

    employment_type  TEXT,             -- e.g. 'full_time', 'contract', 'permanent'
    category         TEXT,             -- e.g. Adzuna's category label, USAJobs job category

    -- Cleaned, plain-text narrative -- what Phase 2 chunks and embeds.
    description_text TEXT NOT NULL,

    apply_url        TEXT,

    posted_at        TIMESTAMPTZ,

    -- SHA-256 of description_text. Lets the Phase 2 embedding job re-embed
    -- only postings whose text actually changed on re-sync.
    content_hash     TEXT NOT NULL,

    -- Full raw API response, kept for provenance and reprocessing without
    -- re-fetching.
    payload           JSONB NOT NULL,

    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT job_postings_source_external_id_key UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_source ON job_postings (source);
CREATE INDEX IF NOT EXISTS idx_job_postings_posted_at ON job_postings (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_postings_remote ON job_postings (remote);

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'job_postings'
ORDER BY ordinal_position;
