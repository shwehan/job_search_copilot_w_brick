-- 05_create_skill_joins.sql
-- The two many-to-many joins that make the `skills` table useful:
--
--   profile_skills     — what a person already has (and how well)
--   job_posting_skills — what a posting is asking for (and how strictly)
--
-- Both reference skills(id) directly and are cheap to populate/query, which
-- is what makes the skill-gap report a join instead of an LLM call:
--
--   SELECT skill_id FROM job_posting_skills WHERE job_posting_id = ANY(...)
--   EXCEPT
--   SELECT skill_id FROM profile_skills WHERE profile_id = ...

CREATE TABLE IF NOT EXISTS profile_skills (
    profile_id       UUID NOT NULL REFERENCES profiles (id) ON DELETE CASCADE,
    skill_id         TEXT NOT NULL REFERENCES skills (id) ON DELETE CASCADE,
    proficiency      TEXT CHECK (proficiency IN ('beginner', 'intermediate', 'advanced', 'expert')),
    years_experience NUMERIC,

    PRIMARY KEY (profile_id, skill_id)
);

CREATE TABLE IF NOT EXISTS job_posting_skills (
    job_posting_id   TEXT NOT NULL REFERENCES job_postings (id) ON DELETE CASCADE,
    skill_id         TEXT NOT NULL REFERENCES skills (id) ON DELETE CASCADE,
    requirement_type TEXT NOT NULL DEFAULT 'required'
                      CHECK (requirement_type IN ('required', 'preferred')),

    PRIMARY KEY (job_posting_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_profile_skills_skill_id ON profile_skills (skill_id);
CREATE INDEX IF NOT EXISTS idx_job_posting_skills_skill_id ON job_posting_skills (skill_id);

-- Verify.
SELECT 'profile_skills' AS table_name, count(*) AS present FROM profile_skills
UNION ALL
SELECT 'job_posting_skills', count(*) FROM job_posting_skills;
