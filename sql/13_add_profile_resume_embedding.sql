-- 13_add_profile_resume_embedding.sql
-- Adds vector support to profiles, deferred from Phase 1's
-- 02_create_profiles.sql on purpose -- the column width couldn't be
-- chosen before an embedding model was.
--
-- A profile gets ONE embedding, not chunks: matching is "does this whole
-- profile fit this posting," and the future tailoring feature works from
-- resume_text directly rather than needing chunk-level resume retrieval.
-- job_postings gets chunked (see 12_create_job_posting_embeddings.sql)
-- because posting length varies wildly across sources; a single resume is
-- a bounded, human-authored document that fits comfortably in one
-- embedding call.

ALTER TABLE profiles
    ADD COLUMN IF NOT EXISTS resume_embedding VECTOR(1024),
    ADD COLUMN IF NOT EXISTS resume_content_hash TEXT,
    ADD COLUMN IF NOT EXISTS resume_embedded_at TIMESTAMPTZ;

-- No HNSW index here -- profiles are searched by primary key or user_id in
-- every query path in this project (a person's own profile, looked up
-- directly), never by "find the most similar profile to X." An ANN index
-- only pays for itself when you're searching *among* many vectors, which
-- job_posting_embeddings does and profiles does not.

-- Verify.
SELECT column_name, data_type, udt_name
FROM information_schema.columns
WHERE table_name = 'profiles'
ORDER BY ordinal_position;
