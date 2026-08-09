-- 10_verify_schema.sql
-- Run after 01-09 to confirm every table exists and to poke at the data
-- once you've run a sync.

-- 1. All 10 tables present (8 required + 2 skill joins).
SELECT table_name,
       to_regclass('public.' || table_name) IS NOT NULL AS present
FROM (VALUES
    ('users'), ('profiles'), ('skills'), ('job_postings'),
    ('profile_skills'), ('job_posting_skills'),
    ('applications'), ('saved_jobs'), ('interview_notes'), ('contacts')
) AS t(table_name);

-- 2. Foreign keys resolve where expected.
SELECT tc.table_name, kcu.column_name, ccu.table_name AS references_table
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
ORDER BY tc.table_name;

-- 3. Row counts across the board (all zero until you sync + create a user).
SELECT
    (SELECT count(*) FROM users)              AS users,
    (SELECT count(*) FROM profiles)           AS profiles,
    (SELECT count(*) FROM skills)             AS skills,
    (SELECT count(*) FROM job_postings)       AS job_postings,
    (SELECT count(*) FROM applications)       AS applications,
    (SELECT count(*) FROM saved_jobs)         AS saved_jobs,
    (SELECT count(*) FROM interview_notes)    AS interview_notes,
    (SELECT count(*) FROM contacts)           AS contacts;

-- 4. Postings by source, once synced.
SELECT source, count(*) AS postings,
       count(*) FILTER (WHERE remote) AS remote_postings,
       min(posted_at) AS oldest, max(posted_at) AS newest
FROM job_postings
GROUP BY source
ORDER BY source;

-- 5. Sample the newest postings.
SELECT id, source, title, company, location, remote,
       salary_min, salary_max, posted_at, synced_at
FROM job_postings
ORDER BY synced_at DESC
LIMIT 10;

-- 6. Confirm applications is ready for Lakebase CDF (Phase 1 spike).
SELECT relname, relreplident
FROM pg_class
WHERE relname = 'applications';
-- relreplident should be 'f' (full) -- if it shows 'd' (default), the
-- ALTER TABLE ... REPLICA IDENTITY FULL in 06_create_applications.sql
-- didn't take; re-run it before attempting the CDF spike.
