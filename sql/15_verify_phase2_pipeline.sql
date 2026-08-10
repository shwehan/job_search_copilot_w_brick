-- Run after the embedding notebook. SQL 01-14 remain unchanged.
SELECT
  (SELECT count(*) FROM job_postings) AS total_postings,
  (SELECT count(DISTINCT job_posting_id) FROM job_posting_embeddings) AS embedded_postings,
  (SELECT count(*) FROM job_posting_embeddings) AS total_chunks;

SELECT model_name, count(*) AS chunks, count(DISTINCT job_posting_id) AS postings
FROM job_posting_embeddings
GROUP BY model_name
ORDER BY model_name;

SELECT p.id, p.source, p.title
FROM job_postings p
WHERE NOT EXISTS (
  SELECT 1 FROM job_posting_embeddings e
  WHERE e.job_posting_id=p.id AND e.content_hash=p.content_hash
)
LIMIT 20;

SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename='job_posting_embeddings'
  AND indexdef ILIKE '%vector_cosine_ops%';
