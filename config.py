"""
Central configuration for the AI Job Hunting Copilot.

Phase 1 only: table names and harvest defaults. Embedding model/dimension
and chunking parameters get added here in Phase 2, following the same
pattern as the weather-app homework's config.py.
"""

import os

# --------------------------------------------------------------------------
# Lakebase tables
# --------------------------------------------------------------------------

JOB_POSTINGS_TABLE = os.environ.get("JOB_POSTINGS_TABLE", "job_postings")
USERS_TABLE = os.environ.get("USERS_TABLE", "users")
PROFILES_TABLE = os.environ.get("PROFILES_TABLE", "profiles")
SKILLS_TABLE = os.environ.get("SKILLS_TABLE", "skills")
APPLICATIONS_TABLE = os.environ.get("APPLICATIONS_TABLE", "applications")
SAVED_JOBS_TABLE = os.environ.get("SAVED_JOBS_TABLE", "saved_jobs")
INTERVIEW_NOTES_TABLE = os.environ.get("INTERVIEW_NOTES_TABLE", "interview_notes")
CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "contacts")

# --------------------------------------------------------------------------
# Harvest defaults
# --------------------------------------------------------------------------

# Adzuna is scoped by country in the URL path (gb, us, de, ...). Search
# terms and locations are supplied per-request; this just sets the default
# market when a request doesn't specify one.
DEFAULT_ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "us")

# USAJobs asks every client to identify itself with the email registered
# for the API key, sent as the User-Agent header on every request.
USAJOBS_EMAIL = os.environ.get("USAJOBS_EMAIL", "").strip()

# Upper bound on postings written per source per sync call.
DEFAULT_SYNC_LIMIT = int(os.environ.get("JOB_SYNC_LIMIT", "50"))

DEFAULT_SEARCH_QUERIES = [
    q.strip()
    for q in os.environ.get(
        "JOB_SEARCH_QUERIES",
        "software engineer;data engineer;machine learning engineer",
    ).split(";")
    if q.strip()
]

DEFAULT_LOCATION = os.environ.get("JOB_SEARCH_LOCATION", "")
