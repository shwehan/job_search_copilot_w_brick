-- Phase 6 explicit preference signal used for transparent reranking.
CREATE TABLE IF NOT EXISTS job_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    feedback TEXT NOT NULL CHECK (feedback IN ('good', 'bad', 'skip')),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT job_feedback_user_job_key UNIQUE (user_id, job_posting_id)
);

CREATE INDEX IF NOT EXISTS idx_job_feedback_user_feedback
    ON job_feedback(user_id, feedback);

SELECT column_name, data_type, is_nullable
FROM information_schema.columns WHERE table_name='job_feedback'
ORDER BY ordinal_position;
