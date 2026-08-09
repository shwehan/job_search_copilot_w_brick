-- 14_verify_phase2_schema.sql
-- Run after 11-13, and again after syncing/embedding, to inspect Lakebase
-- by hand.

-- 1. pgvector is enabled and job_posting_embeddings/profiles have the
--    right column types.
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

SELECT table_name, column_name, udt_name
FROM information_schema.columns
WHERE (table_name = 'job_posting_embeddings' AND column_name = 'embedding')
   OR (table_name = 'profiles' AND column_name = 'resume_embedding');
-- Expect: vector in both rows.

-- 2. Coverage: how many postings have been embedded vs synced.
SELECT
    (SELECT count(*) FROM job_postings) AS total_postings,
    (SELECT count(DISTINCT job_posting_id) FROM job_posting_embeddings) AS embedded_postings,
    (SELECT count(*) FROM job_posting_embeddings) AS total_chunks,
    (SELECT count(*) FROM profiles WHERE resume_embedding IS NOT NULL) AS embedded_profiles;

-- 3. Anything synced but not yet embedded (should be empty after a full
--    embed run).
SELECT p.id, p.source, p.title
FROM job_postings p
WHERE NOT EXISTS (
    SELECT 1 FROM job_posting_embeddings e
    WHERE e.job_posting_id = p.id
      AND e.content_hash = p.content_hash
)
LIMIT 20;

-- 4. Sample chunks, with how many each posting produced.
SELECT e.job_posting_id,
       count(*) AS chunk_count,
       min(length(e.chunk_text)) AS shortest_chunk,
       max(length(e.chunk_text)) AS longest_chunk,
       max(e.model_name) AS model_name
FROM job_posting_embeddings e
GROUP BY e.job_posting_id
ORDER BY chunk_count DESC
LIMIT 10;

-- 5. Confirm the HNSW index exists.
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'job_posting_embeddings';

-- 6. Manually sanity-check a search. Replace the vector literal with any
-- real one first:
--   SELECT embedding FROM job_posting_embeddings LIMIT 1;
--
-- EXPLAIN ANALYZE
-- SELECT d.title, 1 - (e.embedding <=> '[...]'::vector) AS similarity
-- FROM job_posting_embeddings e
-- JOIN job_postings d ON d.id = e.job_posting_id
-- ORDER BY e.embedding <=> '[...]'::vector
-- LIMIT 5;
