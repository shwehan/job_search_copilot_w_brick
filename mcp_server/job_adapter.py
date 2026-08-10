"""Lakebase adapter used by thin MCP tool functions."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import config
import lakebase
from embedding_client import embed_query

STAGES = ("saved", "applied", "interviewing", "rejected", "offer")


def _json(value: Any) -> Any:
    if isinstance(value, (datetime, date)): return value.isoformat()
    if isinstance(value, Decimal): return float(value)
    return str(value) if value.__class__.__name__ == "UUID" else value


def _row(row: dict) -> dict:
    return {key: _json(value) for key, value in row.items()}


def _text(value: Any, name: str, *, required: bool = True, maximum: int = 10000) -> str:
    clean = " ".join(str(value or "").split())
    if required and not clean: raise ValueError(f"{name} is required.")
    if len(clean) > maximum: raise ValueError(f"{name} is too long.")
    return clean


def user_by_email(email: str) -> dict:
    clean = _text(email, "user_email", maximum=320).lower()
    rows = lakebase.query(
        "SELECT id, email, display_name FROM users WHERE lower(email)=lower(%s)", (clean,)
    )
    if not rows:
        raise ValueError("No user exists for that email. Create the user in the dashboard first.")
    return _row(rows[0])


def get_profile_context(user_email: str) -> dict:
    user = user_by_email(user_email)
    rows = lakebase.query(
        """SELECT id, label, target_roles, seniority, salary_min, salary_currency,
                  remote_preference, locations_preferred, deal_breakers,
                  resume_filename, left(resume_text, 8000) AS resume_text
           FROM profiles WHERE user_id=%s
           ORDER BY is_default DESC, created_at LIMIT 1""", (user["id"],)
    )
    if not rows:
        raise ValueError("This user has no profile. Create a profile in the dashboard first.")
    return {"user": user, "profile": _row(rows[0])}


def search_jobs(user_email: str, request: str, top_k: int = 5,
                remote_only: bool = False, location: str = "",
                minimum_salary: float | None = None) -> dict:
    context = get_profile_context(user_email)
    profile = context["profile"]
    clean = _text(request, "request", maximum=2000)
    role_context = ", ".join(profile.get("target_roles") or [])
    semantic_text = clean + (f". Target roles: {role_context}" if role_context else "")
    vector = embed_query(semantic_text)
    clauses = ["e.model_name=%s"]
    params: list[Any] = [config.EMBEDDING_MODEL]
    if remote_only or profile.get("remote_preference") == "remote_only": clauses.append("p.remote=true")
    if location:
        clauses.append("p.location ILIKE %s"); params.append("%" + location.strip() + "%")
    if minimum_salary is not None:
        clauses.append("p.salary_max IS NOT NULL AND p.salary_max >= %s"); params.append(float(minimum_salary))
    limit = max(1, min(int(top_k), config.MAX_TOP_K))
    sql = f"""
      WITH candidates AS (
        SELECT p.id, p.source, p.title, p.company, p.location, p.remote,
               p.salary_min, p.salary_max, p.salary_currency, p.apply_url,
               left(p.description_text, 1200) AS description,
               e.chunk_text, e.embedding <=> %s::vector AS distance
        FROM job_posting_embeddings e JOIN job_postings p ON p.id=e.job_posting_id
        WHERE {' AND '.join(clauses)}
        ORDER BY e.embedding <=> %s::vector LIMIT %s
      ), distinct_jobs AS (
        SELECT DISTINCT ON (id) *, 1-distance AS similarity
        FROM candidates ORDER BY id, distance
      )
      SELECT * FROM distinct_jobs ORDER BY similarity DESC LIMIT %s
    """
    query_params = tuple([vector] + params + [vector, max(50, limit * 10), limit])
    results = [_row(item) for item in lakebase.query(sql, query_params)]
    return {"query": clean, "profile_label": profile["label"], "count": len(results), "jobs": results}


def get_job_match_context(user_email: str, job_posting_id: str) -> dict:
    context = get_profile_context(user_email)
    rows = lakebase.query(
        """SELECT id, title, company, location, remote, salary_min, salary_max,
                  description_text, apply_url FROM job_postings WHERE id=%s""",
        (_text(job_posting_id, "job_posting_id", maximum=500),),
    )
    if not rows: raise ValueError("Job posting not found.")
    return {"profile": context["profile"], "job": _row(rows[0])}


def save_job(user_email: str, job_posting_id: str, note: str = "") -> dict:
    user = user_by_email(user_email)
    row = lakebase.write_returning(
        """INSERT INTO saved_jobs (user_id, job_posting_id, note) VALUES (%s,%s,%s)
           ON CONFLICT (user_id, job_posting_id) DO UPDATE
             SET note=COALESCE(NULLIF(EXCLUDED.note,''), saved_jobs.note)
           RETURNING id, job_posting_id, note, saved_at""",
        (user["id"], _text(job_posting_id, "job_posting_id", maximum=500),
         _text(note, "note", required=False, maximum=5000)),
    )
    return _row(row)


def update_pipeline_stage(user_email: str, job_posting_id: str, stage: str) -> dict:
    stage = _text(stage, "stage").lower()
    if stage not in STAGES: raise ValueError("stage must be one of: " + ", ".join(STAGES))
    user = user_by_email(user_email)
    profile = lakebase.query(
        "SELECT id FROM profiles WHERE user_id=%s ORDER BY is_default DESC, created_at LIMIT 1",
        (user["id"],),
    )
    row = lakebase.write_returning(
        """INSERT INTO applications (user_id, profile_id, job_posting_id, stage, applied_at)
           VALUES (%s,%s,%s,%s,CASE WHEN %s='applied' THEN now() END)
           ON CONFLICT (user_id, job_posting_id) DO UPDATE SET
             stage=EXCLUDED.stage, stage_updated_at=now(), is_stale=false,
             stale_flagged_at=NULL,
             applied_at=CASE WHEN EXCLUDED.stage='applied' AND applications.applied_at IS NULL
                             THEN now() ELSE applications.applied_at END
           RETURNING id, job_posting_id, stage, stage_updated_at, applied_at""",
        (user["id"], profile[0]["id"] if profile else None,
         _text(job_posting_id, "job_posting_id", maximum=500), stage, stage),
    )
    return _row(row)


def log_interview_note(user_email: str, job_posting_id: str, note: str,
                       follow_up_date: str = "", interview_type: str = "other") -> dict:
    user = user_by_email(user_email)
    if interview_type not in ("phone_screen", "technical", "onsite", "behavioral", "other"):
        raise ValueError("Invalid interview_type.")
    if follow_up_date:
        try:
            date.fromisoformat(follow_up_date)
        except ValueError as exc:
            raise ValueError("follow_up_date must use YYYY-MM-DD.") from exc
    rows = lakebase.query(
        "SELECT id FROM applications WHERE user_id=%s AND job_posting_id=%s",
        (user["id"], job_posting_id),
    )
    if not rows: raise ValueError("Track this job as an application before adding a note.")
    row = lakebase.write_returning(
        """INSERT INTO interview_notes (application_id,note,interview_type,follow_up_date)
           VALUES (%s,%s,%s,%s) RETURNING id, application_id, note,
           interview_type, follow_up_date, created_at""",
        (rows[0]["id"], _text(note, "note", maximum=10000), interview_type,
         follow_up_date.strip() or None),
    )
    return _row(row)


def get_pipeline(user_email: str) -> dict:
    user = user_by_email(user_email)
    rows = lakebase.query(
        """SELECT a.id, a.job_posting_id, p.title, p.company, a.stage,
                  a.stage_updated_at, a.applied_at, a.is_stale, a.stale_flagged_at,
                  count(n.id) AS note_count
           FROM applications a JOIN job_postings p ON p.id=a.job_posting_id
           LEFT JOIN interview_notes n ON n.application_id=a.id
           WHERE a.user_id=%s GROUP BY a.id,p.title,p.company
           ORDER BY a.stage_updated_at DESC""", (user["id"],)
    )
    return {"user_email": user["email"], "applications": [_row(item) for item in rows]}


def stale_applications(user_email: str, stale_days: int = 14) -> dict:
    user = user_by_email(user_email)
    days = max(1, min(int(stale_days), 365))
    rows = lakebase.query(
        """SELECT a.id, a.job_posting_id, p.title, p.company, a.stage_updated_at,
                  current_date-a.stage_updated_at::date AS days_without_update,
                  a.is_stale, a.stale_flagged_at
           FROM applications a JOIN job_postings p ON p.id=a.job_posting_id
           WHERE a.user_id=%s AND a.stage='applied'
             AND a.stage_updated_at < now()-(%s*interval '1 day')
           ORDER BY a.stage_updated_at""", (user["id"], days)
    )
    return {"threshold_days": days, "count": len(rows), "applications": [_row(item) for item in rows]}
