"""
The vectorization and retrieval core of the AI Job Hunting Copilot.

Mirrors the weather-app homework's embedding_pipeline.py, adapted for two
kinds of embeddable content instead of one:

    job_postings   -- chunked (descriptions vary wildly in length across
                       the three sources), stored in job_posting_embeddings
    profiles       -- single embedding per profile (one resume, matched as
                       a whole against postings), stored directly on the
                       profiles row

Both use the same embedding endpoint and the same content-hash trick to
avoid re-embedding text that hasn't changed.

Write path
    text -> chunks -> vectors -> job_posting_embeddings (pg8000 +
    lakebase.execute_values, cast to pgvector's VECTOR type with
    %s::vector)

Read path
    query (text or a profile's resume) -> vector -> cosine distance with
    pgvector's <=> operator, joined back to job_postings for display
    fields.
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from typing import Any, Sequence

import config
import lakebase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding client
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _workspace_client():
    """A single, lazily-created WorkspaceClient, reused across calls.

    databricks-sdk is pure Python, so creating this client never risks the
    native-extension crash a local embedding model would.
    """
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def embed_texts(
    texts: Sequence[str],
    model_name: str = config.EMBEDDING_MODEL_NAME,
    batch_size: int = 32,
) -> list[list[float]]:
    """Embed a list of strings via the Databricks embedding endpoint.

    Batches requests so embedding a few hundred chunks is a handful of HTTP
    calls, not one per chunk. Results are sorted by the response's own
    ``index`` rather than trusted to arrive in order -- cheap insurance
    against a provider that batches or retries out of order.
    """
    if not texts:
        return []

    client = _workspace_client()
    vectors: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        response = client.serving_endpoints.query(name=model_name, input=batch)
        items = sorted(response.data, key=lambda item: item.index)
        vectors.extend([float(v) for v in item.embedding] for item in items)

    return vectors


def to_vector_literal(vector: Sequence[float]) -> str:
    """Render a vector in the text form pgvector accepts: ``[1,2,3]``."""
    return "[" + ",".join(f"{float(value):.7f}" for value in vector) + "]"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    chunk_size: int = config.CHUNK_SIZE,
    chunk_overlap: int = config.CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping windows.

    Most RemoteOK/short Adzuna postings fit in a single chunk; this mainly
    matters for long federal qualification summaries and combined
    description+requirements text from Adzuna/USAJobs.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]

    step = max(1, chunk_size - chunk_overlap)
    chunks: list[str] = []
    for start in range(0, len(cleaned), step):
        window = cleaned[start : start + chunk_size].strip()
        if window:
            chunks.append(window)
        if start + chunk_size >= len(cleaned):
            break
    return chunks


# ---------------------------------------------------------------------------
# Job posting embeddings (chunked)
# ---------------------------------------------------------------------------


def fetch_pending_job_postings(
    limit: int | None = None,
    model_name: str = config.EMBEDDING_MODEL_NAME,
) -> list[dict]:
    """Postings with no current embedding for this model + this exact text.

    Comparing content_hash means an edited posting gets re-embedded while
    an unchanged one is skipped, so a re-sync-then-embed cycle only pays
    for what actually changed.
    """
    sql = f"""
        SELECT p.id, p.title, p.description_text, p.content_hash
        FROM {config.JOB_POSTINGS_TABLE} p
        WHERE p.description_text IS NOT NULL
          AND length(trim(p.description_text)) > 0
          AND NOT EXISTS (
              SELECT 1
              FROM {config.JOB_POSTING_EMBEDDINGS_TABLE} e
              WHERE e.job_posting_id = p.id
                AND e.model_name = %s
                AND e.content_hash = p.content_hash
          )
        ORDER BY p.synced_at DESC
    """
    params: list[Any] = [model_name]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))
    return lakebase.run_query(sql, tuple(params))


def write_job_posting_embeddings(rows: Sequence[dict], page_size: int = 100) -> int:
    """Batch-write chunk embeddings for job postings.

    Each row is a dict with job_posting_id, chunk_index, chunk_text,
    embedding, model_name, content_hash. Cast to pgvector's VECTOR type
    with an explicit %s::vector in SQL -- no Spark JDBC, no float8[]
    staging column.
    """
    if not rows:
        return 0

    values = [
        (
            f"{row['job_posting_id']}#{row['chunk_index']}",
            row["job_posting_id"],
            int(row["chunk_index"]),
            row["chunk_text"],
            to_vector_literal(row["embedding"]),
            row.get("model_name", config.EMBEDDING_MODEL_NAME),
            row.get("content_hash"),
        )
        for row in rows
    ]

    sql = f"""
        INSERT INTO {config.JOB_POSTING_EMBEDDINGS_TABLE} (
            id, job_posting_id, chunk_index, chunk_text, embedding,
            model_name, content_hash, created_at
        )
        VALUES %s
        ON CONFLICT (id) DO UPDATE
            SET chunk_text = EXCLUDED.chunk_text,
                embedding = EXCLUDED.embedding,
                model_name = EXCLUDED.model_name,
                content_hash = EXCLUDED.content_hash,
                created_at = now()
    """
    template = "(%s, %s, %s, %s, %s::vector, %s, %s, now())"

    with lakebase.get_connection() as conn:
        cursor = conn.cursor()
        try:
            lakebase.execute_values(
                cursor, sql, values, template=template, page_size=page_size
            )
            conn.commit()
        finally:
            cursor.close()
    return len(values)


def embed_pending_job_postings(
    limit: int | None = None,
    model_name: str = config.EMBEDDING_MODEL_NAME,
    chunk_size: int = config.CHUNK_SIZE,
    chunk_overlap: int = config.CHUNK_OVERLAP,
    batch_size: int = 32,
) -> dict:
    """Chunk, embed, and store every job posting that needs it."""
    postings = fetch_pending_job_postings(limit=limit, model_name=model_name)
    if not postings:
        return {"postings_processed": 0, "chunks_written": 0, "model_name": model_name}

    chunk_rows: list[dict] = []
    for posting in postings:
        for index, chunk in enumerate(
            chunk_text(posting["description_text"], chunk_size, chunk_overlap)
        ):
            chunk_rows.append(
                {
                    "job_posting_id": posting["id"],
                    "chunk_index": index,
                    "chunk_text": chunk,
                    "content_hash": posting["content_hash"],
                    "model_name": model_name,
                }
            )

    if not chunk_rows:
        return {
            "postings_processed": len(postings),
            "chunks_written": 0,
            "model_name": model_name,
        }

    written = 0
    for start in range(0, len(chunk_rows), batch_size):
        batch = chunk_rows[start : start + batch_size]
        vectors = embed_texts(
            [row["chunk_text"] for row in batch], model_name=model_name, batch_size=batch_size
        )
        for row, vector in zip(batch, vectors):
            row["embedding"] = vector
        written += write_job_posting_embeddings(batch)

    return {
        "postings_processed": len(postings),
        "chunks_written": written,
        "model_name": model_name,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }


# ---------------------------------------------------------------------------
# Profile embeddings (single vector per profile)
# ---------------------------------------------------------------------------


def _profile_summary_text(profile: dict) -> str:
    """Build the text a profile's resume_embedding actually represents.

    Not just resume_text alone -- folding in target_roles and top skills
    means a thin resume paired with clear stated preferences still
    produces a meaningful match vector, rather than depending entirely on
    resume quality.
    """
    parts = [profile.get("resume_text") or ""]
    target_roles = profile.get("target_roles") or []
    if target_roles:
        parts.append("Target roles: " + ", ".join(target_roles))
    return "\n\n".join(p for p in parts if p.strip())


def embed_profile(profile_id: str, model_name: str = config.EMBEDDING_MODEL_NAME) -> dict:
    """Embed one profile's resume (+ target roles) and store the vector.

    Unlike job postings, this always re-embeds when called rather than
    checking content_hash first -- profile edits are infrequent, deliberate,
    user-initiated actions, not a bulk re-sync, so the content-hash-skip
    optimization that matters for thousands of postings isn't worth the
    extra round trip for a single row.
    """
    rows = lakebase.run_query(
        f"SELECT id, resume_text, target_roles FROM {config.PROFILES_TABLE} WHERE id = %s",
        (profile_id,),
    )
    if not rows:
        raise ValueError(f"No profile with id {profile_id!r}")
    profile = rows[0]

    summary = _profile_summary_text(profile)
    if not summary.strip():
        raise ValueError("Profile has no resume_text or target_roles to embed.")

    vector = embed_texts([summary], model_name=model_name)[0]
    content_hash = hashlib.sha256(summary.encode("utf-8")).hexdigest()

    lakebase.run_write(
        f"""
        UPDATE {config.PROFILES_TABLE}
        SET resume_embedding = %s::vector,
            resume_content_hash = %s,
            resume_embedded_at = now()
        WHERE id = %s
        """,
        (to_vector_literal(vector), content_hash, profile_id),
    )
    return {"profile_id": profile_id, "model_name": model_name, "embedded": True}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def search(
    query: str | None = None,
    profile_id: str | None = None,
    top_k: int = config.DEFAULT_TOP_K,
    source: str | None = None,
    remote_only: bool = False,
    salary_min: float | None = None,
    model_name: str = config.EMBEDDING_MODEL_NAME,
) -> list[dict]:
    """Semantic search over job postings.

    Exactly one of ``query`` (free text, embedded on the fly) or
    ``profile_id`` (uses that profile's already-computed resume_embedding
    as the query vector) must be provided. Structural filters -- source,
    remote, salary floor -- are applied as a plain SQL WHERE clause before
    the vector distance ordering, so an LLM or the embedding endpoint is
    never invoked to answer something a filter already answers directly.
    """
    if bool(query) == bool(profile_id):
        raise ValueError("Provide exactly one of query or profile_id.")

    top_k = max(config.MIN_TOP_K, min(int(top_k), config.MAX_TOP_K))

    if query:
        vector = to_vector_literal(embed_texts([query], model_name=model_name)[0])
    else:
        rows = lakebase.run_query(
            f"SELECT resume_embedding FROM {config.PROFILES_TABLE} WHERE id = %s",
            (profile_id,),
        )
        if not rows or rows[0]["resume_embedding"] is None:
            raise ValueError(
                f"Profile {profile_id!r} has no resume_embedding yet -- call "
                "embed_profile() first."
            )
        # pg8000 has no built-in codec for pgvector's OID (it's a
        # third-party extension type, dynamically assigned per database),
        # so it falls back to returning the raw text -- already in
        # pgvector's own "[0.1,0.2,...]" literal form, usable as-is. Handle
        # both that and a parsed list defensively in case a future pg8000
        # version adds a codec for it.
        raw = rows[0]["resume_embedding"]
        vector = raw if isinstance(raw, str) else to_vector_literal(raw)

    filters = ["1 = 1"]
    params: list[Any] = [vector]
    if source:
        filters.append("d.source = %s")
        params.append(source)
    if remote_only:
        filters.append("d.remote = true")
    if salary_min is not None:
        filters.append("(d.salary_max IS NULL OR d.salary_max >= %s)")
        params.append(salary_min)

    params.extend([vector, top_k])

    sql = f"""
        SELECT d.id, d.source, d.title, d.company, d.location, d.remote,
               d.salary_min, d.salary_max, d.salary_currency,
               d.employment_type, d.apply_url, d.posted_at,
               e.chunk_index, e.chunk_text,
               1 - (e.embedding <=> %s::vector) AS similarity
        FROM {config.JOB_POSTING_EMBEDDINGS_TABLE} e
        JOIN {config.JOB_POSTINGS_TABLE} d ON d.id = e.job_posting_id
        WHERE {' AND '.join(filters)}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """

    rows = lakebase.run_query(sql, tuple(params))
    for row in rows:
        row["similarity"] = round(float(row["similarity"]), 4)
        if row.get("posted_at") is not None:
            row["posted_at"] = row["posted_at"].isoformat()
    return rows


def stats() -> dict:
    """Embedding coverage, used by /healthz and the web UI."""
    postings = lakebase.run_query(
        f"""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE description_text IS NOT NULL
                                 AND length(trim(description_text)) > 0) AS embeddable
        FROM {config.JOB_POSTINGS_TABLE}
        """
    )[0]
    embeddings = lakebase.run_query(
        f"""
        SELECT count(*) AS chunks,
               count(DISTINCT job_posting_id) AS embedded_postings,
               max(created_at) AS last_embedded_at
        FROM {config.JOB_POSTING_EMBEDDINGS_TABLE}
        """
    )[0]
    profiles = lakebase.run_query(
        f"""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE resume_embedding IS NOT NULL) AS embedded
        FROM {config.PROFILES_TABLE}
        """
    )[0]

    def _iso(value):
        return value.isoformat() if value is not None else None

    return {
        "job_postings": int(postings["total"] or 0),
        "embeddable_postings": int(postings["embeddable"] or 0),
        "embedded_postings": int(embeddings["embedded_postings"] or 0),
        "chunks": int(embeddings["chunks"] or 0),
        "last_embedded_at": _iso(embeddings["last_embedded_at"]),
        "profiles": int(profiles["total"] or 0),
        "embedded_profiles": int(profiles["embedded"] or 0),
        "model_name": config.EMBEDDING_MODEL_NAME,
        "embedding_dim": config.EMBEDDING_DIM,
    }
