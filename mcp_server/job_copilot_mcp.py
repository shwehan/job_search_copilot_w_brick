"""FastMCP server exposing Job Hunting Copilot read and write tools."""

import logging
import os
from typing import Callable

from fastmcp import FastMCP

import job_adapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job-copilot-mcp")
mcp = FastMCP("job-hunting-copilot")


def _safe(action: str, fn: Callable, *args, **kwargs) -> dict:
    try:
        return {"ok": True, "action": action, "result": fn(*args, **kwargs)}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "action": action, "error": str(exc), "error_type": "validation"}
    except Exception as exc:
        logger.exception("MCP action %s failed", action)
        return {"ok": False, "action": action, "error": str(exc), "error_type": "service"}


@mcp.tool
def health() -> dict:
    """Check that the Job Hunting Copilot MCP process is responsive.

    Returns:
        A status payload. This does not make a database write.
    """
    return {"ok": True, "service": "job-hunting-copilot", "transport": "streamable-http"}


@mcp.tool
def get_profile(user_email: str) -> dict:
    """Retrieve the user's default job-search and resume context.

    Args:
        user_email: Email of a user already created in the dashboard.
    Returns:
        Target roles, constraints, and resume text for later reasoning.
    """
    return _safe("get_profile", job_adapter.get_profile_context, user_email)


@mcp.tool
def search_jobs(user_email: str, request: str, top_k: int = 5,
                remote_only: bool = False, location: str = "",
                minimum_salary: float | None = None) -> dict:
    """Semantically retrieve real Lakebase postings for a user's request.

    Args:
        user_email: Email of a user already created in the dashboard.
        request: Natural-language job request, skills, or constraints.
        top_k: Number of distinct jobs to return, clamped to 1-20.
        remote_only: Require remote postings when true.
        location: Optional location substring filter.
        minimum_salary: Optional minimum advertised maximum salary.
    Returns:
        Ranked postings with stable IDs, descriptions, URLs, and similarity.
    """
    return _safe("search_jobs", job_adapter.search_jobs, user_email, request,
                 top_k, remote_only, location, minimum_salary)


@mcp.tool
def get_job_match_context(user_email: str, job_posting_id: str) -> dict:
    """Load a real job and profile together so the agent can explain fit.

    Args:
        user_email: Email of a user already created in the dashboard.
        job_posting_id: Stable ID returned by search_jobs.
    Returns:
        The stored posting description and the user's profile/resume context.
    """
    return _safe("get_job_match_context", job_adapter.get_job_match_context,
                 user_email, job_posting_id)


@mcp.tool
def save_job(user_email: str, job_posting_id: str, note: str = "") -> dict:
    """Bookmark a real job posting in Lakebase.

    Args:
        user_email: Email of a user already created in the dashboard.
        job_posting_id: Stable ID returned by search_jobs.
        note: Optional reason for saving the posting.
    Returns:
        The persisted bookmark. Repeated calls do not create duplicates.
    """
    return _safe("save_job", job_adapter.save_job, user_email, job_posting_id, note)


@mcp.tool
def update_pipeline_stage(user_email: str, job_posting_id: str, stage: str) -> dict:
    """Create or move a real job application to a pipeline stage.

    Args:
        user_email: Email of a user already created in the dashboard.
        job_posting_id: Stable ID returned by search_jobs or get_pipeline.
        stage: One of saved, applied, interviewing, rejected, or offer.
    Returns:
        The persisted application stage and timestamps.
    """
    return _safe("update_pipeline_stage", job_adapter.update_pipeline_stage,
                 user_email, job_posting_id, stage)


@mcp.tool
def log_interview_note(user_email: str, job_posting_id: str, note: str,
                       follow_up_date: str = "", interview_type: str = "other") -> dict:
    """Add an interview note and optional ISO follow-up date to an application.

    Args:
        user_email: Email of a user already created in the dashboard.
        job_posting_id: Stable ID for a job already tracked as an application.
        note: Interview outcome, recruiter detail, or next action.
        follow_up_date: Optional date formatted YYYY-MM-DD.
        interview_type: phone_screen, technical, onsite, behavioral, or other.
    Returns:
        The persisted Lakebase note and follow-up date.
    """
    return _safe("log_interview_note", job_adapter.log_interview_note,
                 user_email, job_posting_id, note, follow_up_date, interview_type)


@mcp.tool
def get_pipeline(user_email: str) -> dict:
    """Read all tracked applications and their current stages.

    Args:
        user_email: Email of a user already created in the dashboard.
    Returns:
        Applications, stages, timestamps, stale flags, and note counts.
    """
    return _safe("get_pipeline", job_adapter.get_pipeline, user_email)


@mcp.tool
def check_stale_applications(user_email: str, stale_days: int = 14) -> dict:
    """Find applied jobs that have not been updated recently.

    Args:
        user_email: Email of a user already created in the dashboard.
        stale_days: Inactivity threshold, clamped to 1-365 days.
    Returns:
        Stale applications with job IDs, companies, and days without updates.
    """
    return _safe("check_stale_applications", job_adapter.stale_applications,
                 user_email, stale_days)


@mcp.tool
def record_feedback(user_email: str, job_posting_id: str, feedback: str,
                    reason: str = "") -> dict:
    """Store an explicit preference that influences the user's future ranking.

    Args:
        user_email: Email of a user already created in the dashboard.
        job_posting_id: Stable ID returned by search_jobs.
        feedback: One of good, bad, or skip.
        reason: Optional explanation supplied by the user.
    Returns:
        The persisted feedback row. Never infer feedback without user confirmation.
    """
    return _safe("record_feedback", job_adapter.record_feedback, user_email,
                 job_posting_id, feedback, reason)


@mcp.tool
def check_listing_legitimacy(job_posting_id: str) -> dict:
    """Screen a stored listing for common risk signals and URL availability.

    Args:
        job_posting_id: Stable ID returned by search_jobs.
    Returns:
        A heuristic risk score, verdict, and evidence flags. This is not a
        guarantee that an employer or posting is legitimate.
    """
    return _safe("check_listing_legitimacy", job_adapter.check_listing_legitimacy,
                 job_posting_id)


@mcp.tool
def get_skill_gap_report(user_email: str, job_posting_ids: list[str]) -> dict:
    """Compare resume evidence with recurring skills in selected real postings.

    Args:
        user_email: Email of a user already created in the dashboard.
        job_posting_ids: One to ten stable IDs returned by search_jobs.
    Returns:
        Skills found in the job texts, divided into present and missing groups.
    """
    return _safe("get_skill_gap_report", job_adapter.skill_gap_report,
                 user_email, job_posting_ids)


@mcp.tool
def draft_application_snippet(user_email: str, job_posting_id: str,
                              format: str = "cover_letter") -> dict:
    """Draft grounded application text from a stored resume and job description.

    Args:
        user_email: Email of a user already created in the dashboard.
        job_posting_id: Stable ID returned by search_jobs.
        format: cover_letter for a short paragraph or resume_bullet for one bullet.
    Returns:
        Model-generated text constrained to facts in the resume and posting.
    """
    return _safe("draft_application_snippet", job_adapter.draft_application_snippet,
                 user_email, job_posting_id, format)


def main():
    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", "8000")))
    mcp.run(transport="http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
