"""Reusable Phase 3 workflow operations for the UI and future MCP tools.

All user-facing workflow writes live here. Flask routes only validate HTTP
shape and call these functions; Phase 5 MCP tools can call the same functions
without duplicating SQL or business rules.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import config
import lakebase

STAGES = ("saved", "applied", "interviewing", "rejected", "offer")
INTERVIEW_TYPES = ("phone_screen", "technical", "onsite", "behavioral", "other")


def _clean(value: Any, field: str, *, required: bool = False, maximum: int = 10000) -> str | None:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required.")
    if len(text) > maximum:
        raise ValueError(f"{field} must be {maximum:,} characters or fewer.")
    return text or None


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _serialize(row: dict | None) -> dict | None:
    return {key: _json_value(value) for key, value in row.items()} if row else None


def _write_returning(sql: str, params: tuple = ()) -> dict:
    with lakebase.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            rows = lakebase._rows_as_dicts(cursor)
            conn.commit()
            return _serialize(rows[0]) if rows else {}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def get_or_create_user(email: str, display_name: str | None = None) -> dict:
    email = (_clean(email, "email", required=True, maximum=320) or "").lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Enter a valid email address.")
    name = _clean(display_name, "display_name", maximum=200)
    return _write_returning(
        f"""
        INSERT INTO {config.USERS_TABLE} (email, display_name)
        VALUES (%s, %s)
        ON CONFLICT (email) DO UPDATE SET
            display_name = COALESCE(EXCLUDED.display_name, {config.USERS_TABLE}.display_name)
        RETURNING id, email, display_name, created_at
        """,
        (email, name),
    )


def list_profiles(user_id: str) -> list[dict]:
    rows = lakebase.run_query(
        f"""SELECT id, user_id, label, target_roles, seniority, salary_min,
                   salary_currency, remote_preference, locations_preferred,
                   deal_breakers, resume_filename, resume_text IS NOT NULL AS has_resume,
                   is_default, created_at, updated_at
            FROM {config.PROFILES_TABLE}
            WHERE user_id = %s ORDER BY is_default DESC, created_at""",
        (user_id,),
    )
    return [_serialize(row) for row in rows]


def create_profile(user_id: str, data: dict) -> dict:
    label = _clean(data.get("label"), "label", required=True, maximum=100)
    roles = [x.strip() for x in data.get("target_roles", []) if str(x).strip()][:20]
    locations = [x.strip() for x in data.get("locations_preferred", []) if str(x).strip()][:20]
    remote = str(data.get("remote_preference") or "any")
    if remote not in ("remote_only", "hybrid", "onsite", "any"):
        raise ValueError("Invalid remote preference.")
    salary = data.get("salary_min") or None
    if salary is not None and float(salary) < 0:
        raise ValueError("salary_min cannot be negative.")
    make_default = bool(data.get("is_default", False))
    with lakebase.get_connection() as conn:
        cursor = conn.cursor()
        try:
            if make_default:
                cursor.execute(
                    f"UPDATE {config.PROFILES_TABLE} SET is_default = false, updated_at = now() WHERE user_id = %s",
                    (user_id,),
                )
            cursor.execute(
                f"""INSERT INTO {config.PROFILES_TABLE}
                    (user_id, label, target_roles, seniority, salary_min,
                     remote_preference, locations_preferred, is_default)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, user_id, label, target_roles, seniority, salary_min,
                              remote_preference, locations_preferred, is_default, created_at""",
                (user_id, label, roles, _clean(data.get("seniority"), "seniority", maximum=100),
                 salary, remote, locations, make_default),
            )
            row = lakebase._rows_as_dicts(cursor)[0]
            conn.commit()
            return _serialize(row)
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def upload_resume(user_id: str, profile_id: str, filename: str, resume_text: str) -> dict:
    filename = _clean(filename, "filename", required=True, maximum=255)
    text = _clean(resume_text, "resume_text", required=True, maximum=250000)
    return _write_returning(
        f"""UPDATE {config.PROFILES_TABLE}
            SET resume_filename = %s, resume_text = %s,
                resume_embedding = NULL, resume_content_hash = NULL,
                resume_embedded_at = NULL, updated_at = now()
            WHERE id = %s AND user_id = %s
            RETURNING id, label, resume_filename, length(resume_text) AS resume_characters,
                      updated_at""",
        (filename, text, profile_id, user_id),
    )


def save_job(user_id: str, job_posting_id: str, note: str | None = None) -> dict:
    return _write_returning(
        f"""INSERT INTO {config.SAVED_JOBS_TABLE} (user_id, job_posting_id, note)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, job_posting_id) DO UPDATE
            SET note = COALESCE(EXCLUDED.note, {config.SAVED_JOBS_TABLE}.note)
            RETURNING id, user_id, job_posting_id, note, saved_at""",
        (user_id, _clean(job_posting_id, "job_posting_id", required=True, maximum=500),
         _clean(note, "note", maximum=5000)),
    )


def unsave_job(user_id: str, job_posting_id: str) -> bool:
    return bool(lakebase.run_write(
        f"DELETE FROM {config.SAVED_JOBS_TABLE} WHERE user_id = %s AND job_posting_id = %s",
        (user_id, job_posting_id),
    ))


def track_application(user_id: str, job_posting_id: str, profile_id: str | None = None) -> dict:
    return _write_returning(
        f"""INSERT INTO {config.APPLICATIONS_TABLE}
                (user_id, profile_id, job_posting_id, stage)
            VALUES (%s, %s, %s, 'saved')
            ON CONFLICT (user_id, job_posting_id) DO UPDATE
            SET profile_id = COALESCE(EXCLUDED.profile_id, {config.APPLICATIONS_TABLE}.profile_id)
            RETURNING id, user_id, profile_id, job_posting_id, stage,
                      stage_updated_at, applied_at, notes, created_at""",
        (user_id, profile_id or None, job_posting_id),
    )


def update_application_stage(user_id: str, application_id: str, stage: str) -> dict:
    if stage not in STAGES:
        raise ValueError("stage must be one of: " + ", ".join(STAGES))
    row = _write_returning(
        f"""UPDATE {config.APPLICATIONS_TABLE}
            SET stage = %s, stage_updated_at = now(),
                is_stale = false, stale_flagged_at = NULL,
                applied_at = CASE WHEN %s = 'applied' AND applied_at IS NULL THEN now() ELSE applied_at END
            WHERE id = %s AND user_id = %s
            RETURNING id, job_posting_id, stage, stage_updated_at, applied_at""",
        (stage, stage, application_id, user_id),
    )
    if not row:
        raise LookupError("Application not found for this user.")
    return row


def list_pipeline(user_id: str) -> dict:
    applications = lakebase.run_query(
        f"""SELECT a.id, a.profile_id, a.job_posting_id, a.stage,
                   a.stage_updated_at, a.applied_at, a.notes, a.is_stale,
                   p.title, p.company, p.location, p.remote, p.apply_url,
                   COALESCE(n.note_count, 0) AS note_count,
                   n.next_follow_up
            FROM {config.APPLICATIONS_TABLE} a
            JOIN {config.JOB_POSTINGS_TABLE} p ON p.id = a.job_posting_id
            LEFT JOIN (
                SELECT application_id, count(*) AS note_count,
                       min(follow_up_date) FILTER (WHERE follow_up_date >= current_date) AS next_follow_up
                FROM {config.INTERVIEW_NOTES_TABLE} GROUP BY application_id
            ) n ON n.application_id = a.id
            WHERE a.user_id = %s
            ORDER BY a.stage_updated_at DESC""",
        (user_id,),
    )
    saved = lakebase.run_query(
        f"""SELECT s.id, s.job_posting_id, s.note, s.saved_at,
                   p.title, p.company, p.location, p.remote, p.apply_url
            FROM {config.SAVED_JOBS_TABLE} s
            JOIN {config.JOB_POSTINGS_TABLE} p ON p.id = s.job_posting_id
            WHERE s.user_id = %s ORDER BY s.saved_at DESC""",
        (user_id,),
    )
    grouped = {stage: [] for stage in STAGES}
    for row in applications:
        grouped[row["stage"]].append(_serialize(row))
    return {"stages": grouped, "saved_jobs": [_serialize(row) for row in saved],
            "application_count": len(applications), "saved_count": len(saved)}


def add_interview_note(user_id: str, application_id: str, data: dict) -> dict:
    interview_type = data.get("interview_type") or None
    if interview_type and interview_type not in INTERVIEW_TYPES:
        raise ValueError("Invalid interview_type.")
    return _write_returning(
        f"""INSERT INTO {config.INTERVIEW_NOTES_TABLE}
                (application_id, note, interview_type, interview_date, follow_up_date)
            SELECT a.id, %s, %s, %s, %s FROM {config.APPLICATIONS_TABLE} a
            WHERE a.id = %s AND a.user_id = %s
            RETURNING id, application_id, note, interview_type,
                      interview_date, follow_up_date, created_at""",
        (_clean(data.get("note"), "note", required=True, maximum=10000), interview_type,
         data.get("interview_date") or None, data.get("follow_up_date") or None,
         application_id, user_id),
    )


def add_contact(user_id: str, data: dict) -> dict:
    return _write_returning(
        f"""INSERT INTO {config.CONTACTS_TABLE}
                (user_id, application_id, name, role, company, email, phone, linkedin_url, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, user_id, application_id, name, role, company, email,
                      phone, linkedin_url, notes, created_at""",
        (user_id, data.get("application_id") or None,
         _clean(data.get("name"), "name", required=True, maximum=200),
         _clean(data.get("role"), "role", maximum=200),
         _clean(data.get("company"), "company", maximum=300),
         _clean(data.get("email"), "email", maximum=320),
         _clean(data.get("phone"), "phone", maximum=100),
         _clean(data.get("linkedin_url"), "linkedin_url", maximum=2000),
         _clean(data.get("notes"), "notes", maximum=5000)),
    )


def record_feedback(user_id: str, job_posting_id: str, feedback: str,
                    reason: str | None = None) -> dict:
    feedback = str(feedback or "").lower().strip()
    if feedback not in ("good", "bad", "skip"):
        raise ValueError("feedback must be good, bad, or skip.")
    return _write_returning(
        f"""INSERT INTO {config.JOB_FEEDBACK_TABLE}
                (user_id, job_posting_id, feedback, reason)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (user_id, job_posting_id) DO UPDATE SET
                feedback=EXCLUDED.feedback, reason=EXCLUDED.reason, updated_at=now()
            RETURNING id, user_id, job_posting_id, feedback, reason, updated_at""",
        (user_id, _clean(job_posting_id, "job_posting_id", required=True, maximum=500),
         feedback, _clean(reason, "reason", maximum=2000)),
    )


def apply_feedback_reranking(user_id: str, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    placeholders = ",".join(["%s"] * len(rows))
    feedback_rows = lakebase.run_query(
        f"""SELECT job_posting_id, feedback FROM {config.JOB_FEEDBACK_TABLE}
            WHERE user_id=%s AND job_posting_id IN ({placeholders})""",
        tuple([user_id] + [row["id"] for row in rows]),
    )
    signals = {row["job_posting_id"]: row["feedback"] for row in feedback_rows}
    adjustments = {"good": 0.05, "bad": -0.10, "skip": -0.04}
    for row in rows:
        signal = signals.get(row["id"])
        row["base_similarity"] = row.get("similarity")
        row["feedback"] = signal
        row["feedback_adjustment"] = adjustments.get(signal, 0.0)
        row["similarity"] = round(max(-1.0, min(1.0,
            float(row.get("similarity") or 0) + row["feedback_adjustment"])), 6)
    return sorted(rows, key=lambda item: item["similarity"], reverse=True)
