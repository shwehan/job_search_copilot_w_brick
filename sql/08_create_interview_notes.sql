-- 08_create_interview_notes.sql
-- Free-text notes tied to a specific application, with an optional
-- follow-up date. This is what the future "surface stale applications"
-- and "upcoming follow-ups" agent tools query against.

CREATE TABLE IF NOT EXISTS interview_notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id  UUID NOT NULL REFERENCES applications (id) ON DELETE CASCADE,

    note            TEXT NOT NULL,
    interview_type  TEXT CHECK (interview_type IN
                      ('phone_screen', 'technical', 'onsite', 'behavioral', 'other')),
    interview_date  TIMESTAMPTZ,
    follow_up_date  DATE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_interview_notes_application_id ON interview_notes (application_id);
CREATE INDEX IF NOT EXISTS idx_interview_notes_follow_up_date ON interview_notes (follow_up_date);

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'interview_notes'
ORDER BY ordinal_position;
