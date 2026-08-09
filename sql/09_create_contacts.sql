-- 09_create_contacts.sql
-- Recruiter / hiring-manager contact info. application_id is nullable
-- because a contact sometimes exists before a formal application does
-- (e.g. a recruiter reaches out about a company generally, or a referral
-- contact isn't tied to one specific posting).

CREATE TABLE IF NOT EXISTS contacts (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    application_id UUID REFERENCES applications (id) ON DELETE SET NULL,

    name           TEXT NOT NULL,
    role           TEXT,             -- e.g. 'Technical Recruiter', 'Hiring Manager'
    company        TEXT,
    email          TEXT,
    phone          TEXT,
    linkedin_url   TEXT,
    notes          TEXT,

    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contacts_user_id ON contacts (user_id);
CREATE INDEX IF NOT EXISTS idx_contacts_application_id ON contacts (application_id);

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'contacts'
ORDER BY ordinal_position;
