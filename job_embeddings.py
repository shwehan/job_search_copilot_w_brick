"""Chunk, embed, persist, and retrieve job postings with pgvector."""

from __future__ import annotations

from typing import Any

import config
import lakebase
from embedding_model import embed_query, embed_texts, vector_literal


def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split text with a character sliding window and deterministic overlap."""
    size = chunk_size or config.CHUNK_SIZE
    shared = config.CHUNK_OVERLAP if overlap is None else overlap
    if size <= 0 or shared < 0 or shared >= size:
        raise ValueError("Chunk size must be positive and overlap must be between 0 and chunk_size - 1.")
    clean = " ".join(str(text or "").split())
    if not clean:
        return []
    chunks, start = [], 0
    while start < len(clean):
        end = min(start + size, len(clean))
        chunks.append(clean[start:end])
        if end == len(clean):
            break
        start = end - shared
    return chunks


def embedding_status() -> dict[str, Any]:
    rows = lakebase.run_query(
        f"""
        SELECT
          (SELECT count(*) FROM {config.JOB_POSTINGS_TABLE}) AS total_postings,
          (SELECT count(DISTINCT job_posting_id) FROM {config.JOB_EMBEDDINGS_TABLE}) AS embedded_postings,
          (SELECT count(*) FROM {config.JOB_EMBEDDINGS_TABLE}) AS total_chunks,
          (SELECT count(*) FROM {config.JOB_POSTINGS_TABLE} p
             WHERE NOT EXISTS (
               SELECT 1 FROM {config.JOB_EMBEDDINGS_TABLE} e
               WHERE e.job_posting_id=p.id
                 AND e.content_hash=p.content_hash
                 AND e.model_name=%s
             )) AS pending_postings
        """,
        (config.EMBEDDING_MODEL,),
    )
    return rows[0]


def fetch_pending_postings(limit: int = 100) -> list[dict]:
    return lakebase.run_query(
        f"""
        SELECT p.id, p.description_text, p.content_hash
        FROM {config.JOB_POSTINGS_TABLE} p
        WHERE NOT EXISTS (
          SELECT 1 FROM {config.JOB_EMBEDDINGS_TABLE} e
          WHERE e.job_posting_id=p.id
            AND e.content_hash=p.content_hash
            AND e.model_name=%s
        )
        ORDER BY p.synced_at DESC
        LIMIT %s
        """,
        (config.EMBEDDING_MODEL, max(1, min(int(limit), 500))),
    )


def _replace_posting_chunks(posting: dict, chunks: list[str], vectors: list[list[float]]) -> int:
    rows = [
        (
            f"{posting['id']}#{index}", posting["id"], index, chunk,
            vector_literal(vector), config.EMBEDDING_MODEL, posting["content_hash"],
        )
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    with lakebase.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"DELETE FROM {config.JOB_EMBEDDINGS_TABLE} WHERE job_posting_id=%s",
                (posting["id"],),
            )
            lakebase.execute_values(
                cursor,
                f"""
                INSERT INTO {config.JOB_EMBEDDINGS_TABLE}
                  (id, job_posting_id, chunk_index, chunk_text, embedding,
                   model_name, content_hash, created_at)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                  chunk_text=EXCLUDED.chunk_text,
                  embedding=EXCLUDED.embedding,
                  model_name=EXCLUDED.model_name,
                  content_hash=EXCLUDED.content_hash,
                  created_at=now()
                """,
                rows,
                template="(%s,%s,%s,%s,%s::vector,%s,%s,now())",
                page_size=100,
            )
            conn.commit()
        finally:
            cursor.close()
    return len(rows)


def embed_pending_postings(limit: int = 100, batch_size: int | None = None) -> dict[str, Any]:
    pending = fetch_pending_postings(limit)
    size = max(1, min(int(batch_size or config.EMBEDDING_BATCH_SIZE), 32))
    posting_count = chunk_count = 0
    for posting in pending:
        chunks = chunk_text(posting["description_text"])
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), size):
            vectors.extend(embed_texts(chunks[start : start + size]))
        chunk_count += _replace_posting_chunks(posting, chunks, vectors)
        posting_count += 1
    return {
        "selected_postings": len(pending),
        "embedded_postings": posting_count,
        "written_chunks": chunk_count,
        "model_name": config.EMBEDDING_MODEL,
        "status": embedding_status(),
    }


def build_search_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    sources = [str(value).lower() for value in filters.get("sources") or [] if value]
    if sources:
        clauses.append("p.source IN (" + ",".join(["%s"] * len(sources)) + ")")
        params.extend(sources)
    if filters.get("remote_only"):
        clauses.append("p.remote = true")
    if filters.get("minimum_salary") is not None:
        clauses.append("p.salary_max IS NOT NULL AND p.salary_max >= %s")
        params.append(float(filters["minimum_salary"]))
    if filters.get("location"):
        clauses.append("p.location ILIKE %s")
        params.append("%" + str(filters["location"]).strip() + "%")
    where_sql = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
      WITH candidate_chunks AS (
        SELECT p.id, p.source, p.title, p.company, p.location, p.remote,
               p.salary_min, p.salary_max, p.salary_currency,
               p.employment_type, p.category, p.description_text, p.apply_url,
               p.posted_at, e.chunk_text,
               e.embedding <=> %s::vector AS distance
        FROM {config.JOB_EMBEDDINGS_TABLE} e
        JOIN {config.JOB_POSTINGS_TABLE} p ON p.id=e.job_posting_id
        WHERE e.model_name=%s {where_sql}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
      ), best_per_job AS (
        SELECT DISTINCT ON (id)
               id, source, title, company, location, remote,
               salary_min, salary_max, salary_currency, employment_type,
               category, description_text, apply_url, posted_at, chunk_text,
               1 - distance AS similarity
        FROM candidate_chunks
        ORDER BY id, distance
      )
      SELECT id, source, title, company, location, remote,
             salary_min, salary_max, salary_currency, employment_type,
             category, left(description_text, 500) AS description_preview,
             apply_url, posted_at, chunk_text, similarity
      FROM best_per_job
      ORDER BY similarity DESC
      LIMIT %s
    """
    return sql, params


def semantic_search(search_text: str, top_k: int = 5, **filters: Any) -> list[dict]:
    clean = " ".join(str(search_text or "").split())
    if not clean:
        raise ValueError("Search query cannot be empty.")
    top_k = max(1, min(int(top_k), 25))
    candidate_limit = min(max(top_k * 10, 50), 250)
    literal = vector_literal(embed_query(clean))
    sql, filter_params = build_search_sql(filters)
    # First vector drives the distance expression; model/filter parameters
    # appear in WHERE; second vector drives the HNSW ORDER BY candidate scan.
    rows = lakebase.run_query(
        sql,
        tuple(
            [literal, config.EMBEDDING_MODEL]
            + filter_params
            + [literal, candidate_limit, top_k]
        ),
    )
    for row in rows:
        row["similarity"] = round(float(row["similarity"]), 6)
        if row.get("posted_at") is not None:
            row["posted_at"] = row["posted_at"].isoformat()
    return rows
