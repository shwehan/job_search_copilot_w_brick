-- 03_create_skills.sql
-- Normalized skill taxonomy. Storing skills as their own table (rather than
-- a free-text array on profiles/job_postings) is what makes the skill-gap
-- report and match explanations possible without re-parsing text every
-- time: "how many open postings want Kubernetes that I don't have" becomes
-- a join, not an LLM call.
--
-- id is the normalized slug itself (lowercase, hyphenated) rather than a
-- surrogate key, so upserting a skill mentioned in a new posting is a
-- single idempotent INSERT ... ON CONFLICT (id) DO NOTHING with no
-- lookup-then-insert round trip.

CREATE TABLE IF NOT EXISTS skills (
    id         TEXT PRIMARY KEY,       -- e.g. 'kubernetes', 'python', 'aws-lambda'
    name       TEXT NOT NULL,          -- display form, e.g. 'Kubernetes'
    category   TEXT,                   -- e.g. 'cloud', 'language', 'framework' (optional)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'skills'
ORDER BY ordinal_position;
