-- 02_create_profiles.sql
-- A profile is one resume/job-search variant for a user — target roles,
-- constraints, and the resume text itself. A user can have more than one
-- (e.g. an "AI/ML engineer" track and a "data engineer" track with
-- different resumes), which is why this is its own table rather than
-- columns bolted onto users.
--
-- resume_text stays plain TEXT with no embedding column yet — that's added
-- in Phase 2 once the vectorization layer exists, to keep this migration
-- scoped to relational structure only.

CREATE TABLE IF NOT EXISTS profiles (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,

    label             TEXT NOT NULL DEFAULT 'default',

    target_roles      TEXT[] NOT NULL DEFAULT '{}',
    seniority         TEXT,
    salary_min        NUMERIC,
    salary_currency   TEXT NOT NULL DEFAULT 'USD',
    remote_preference TEXT NOT NULL DEFAULT 'any'
                      CHECK (remote_preference IN ('remote_only', 'hybrid', 'onsite', 'any')),
    locations_preferred TEXT[] NOT NULL DEFAULT '{}',
    deal_breakers     TEXT[] NOT NULL DEFAULT '{}',

    resume_text       TEXT,
    resume_filename   TEXT,

    is_default        BOOLEAN NOT NULL DEFAULT false,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT profiles_user_label_key UNIQUE (user_id, label)
);

CREATE INDEX IF NOT EXISTS idx_profiles_user_id ON profiles (user_id);

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'profiles'
ORDER BY ordinal_position;
