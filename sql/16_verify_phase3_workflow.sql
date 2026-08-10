-- 16_verify_phase3_workflow.sql
-- Inspection only: confirms the Phase 3 dashboard relationships and counts.
-- It does not create, alter, or delete data.

SELECT
    (SELECT count(*) FROM users) AS users,
    (SELECT count(*) FROM profiles) AS profiles,
    (SELECT count(*) FROM saved_jobs) AS saved_jobs,
    (SELECT count(*) FROM applications) AS applications,
    (SELECT count(*) FROM interview_notes) AS interview_notes,
    (SELECT count(*) FROM contacts) AS contacts;

SELECT stage, count(*) AS applications
FROM applications
GROUP BY stage
ORDER BY CASE stage
    WHEN 'saved' THEN 1 WHEN 'applied' THEN 2 WHEN 'interviewing' THEN 3
    WHEN 'rejected' THEN 4 WHEN 'offer' THEN 5 END;

-- Both checks should return zero rows. A non-zero result means an orphaned
-- relationship exists and should be investigated.
SELECT a.id AS orphan_application_id
FROM applications a
LEFT JOIN users u ON u.id = a.user_id
LEFT JOIN job_postings p ON p.id = a.job_posting_id
WHERE u.id IS NULL OR p.id IS NULL;

SELECT n.id AS orphan_note_id
FROM interview_notes n
LEFT JOIN applications a ON a.id = n.application_id
WHERE a.id IS NULL;

-- Recent workflow activity for a screenshot/manual review.
SELECT a.id, u.email, p.title, p.company, a.stage,
       a.stage_updated_at, count(n.id) AS interview_notes
FROM applications a
JOIN users u ON u.id = a.user_id
JOIN job_postings p ON p.id = a.job_posting_id
LEFT JOIN interview_notes n ON n.application_id = a.id
GROUP BY a.id, u.email, p.title, p.company, a.stage, a.stage_updated_at
ORDER BY a.stage_updated_at DESC
LIMIT 25;
