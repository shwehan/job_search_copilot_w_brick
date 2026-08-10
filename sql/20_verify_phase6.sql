-- Inspection only.
SELECT feedback, count(*) AS responses
FROM job_feedback GROUP BY feedback ORDER BY feedback;

SELECT f.id, u.email, p.title, p.company, f.feedback, f.reason, f.updated_at
FROM job_feedback f JOIN users u ON u.id=f.user_id
JOIN job_postings p ON p.id=f.job_posting_id
ORDER BY f.updated_at DESC LIMIT 30;

SELECT f.id AS orphan_feedback_id FROM job_feedback f
LEFT JOIN users u ON u.id=f.user_id
LEFT JOIN job_postings p ON p.id=f.job_posting_id
WHERE u.id IS NULL OR p.id IS NULL;
