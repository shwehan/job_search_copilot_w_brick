-- Inspection only. Run after the Phase 4 notebook finishes.
SELECT id, status, started_at, finished_at, fetched_rows, prepared_rows,
       synced_rows, embedded_postings, written_chunks, stale_applications,
       source_errors, error_message
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 20;

SELECT count(DISTINCT p.id) AS total_postings,
       count(DISTINCT e.job_posting_id) AS embedded_postings,
       count(e.id) AS total_chunks
FROM job_postings p
LEFT JOIN job_posting_embeddings e ON e.job_posting_id = p.id;

SELECT p.id, p.source, p.title
FROM job_postings p
WHERE NOT EXISTS (
  SELECT 1 FROM job_posting_embeddings e
  WHERE e.job_posting_id = p.id AND e.content_hash = p.content_hash
)
LIMIT 20;

SELECT a.id, u.email, p.title, p.company, a.stage_updated_at,
       current_date - a.stage_updated_at::date AS days_without_update,
       a.is_stale, a.stale_flagged_at
FROM applications a
JOIN users u ON u.id = a.user_id
JOIN job_postings p ON p.id = a.job_posting_id
WHERE a.stage = 'applied'
  AND a.is_stale = true
ORDER BY a.stage_updated_at;
