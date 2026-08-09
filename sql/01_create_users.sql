-- 01_create_users.sql
-- One row per person using the copilot. No auth in Phase 1 — a stable
-- identifier (email) is enough to scope profiles, applications, and saved
-- jobs to a person.

CREATE TABLE IF NOT EXISTS users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Verify.
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;
