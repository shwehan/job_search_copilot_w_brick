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
JOB_POSTING_EMBEDDINGS_TABLE = os.environ.get(
    "JOB_POSTING_EMBEDDINGS_TABLE", "job_posting_embeddings"
)
USERS_TABLE = os.environ.get("USERS_TABLE", "users")
PROFILES_TABLE = os.environ.get("PROFILES_TABLE", "profiles")
SKILLS_TABLE = os.environ.get("SKILLS_TABLE", "skills")
APPLICATIONS_TABLE = os.environ.get("APPLICATIONS_TABLE", "applications")
SAVED_JOBS_TABLE = os.environ.get("SAVED_JOBS_TABLE", "saved_jobs")
INTERVIEW_NOTES_TABLE = os.environ.get("INTERVIEW_NOTES_TABLE", "interview_notes")
CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "contacts")

# --------------------------------------------------------------------------
# Embedding model (Phase 2)
# --------------------------------------------------------------------------
#
# A Databricks Model Serving Foundation Model API endpoint, called over
# REST via databricks-sdk -- not a local sentence-transformers model. This
# is deliberate: a local model pulls in torch, and torch's compiled
# extensions crash the Python kernel on Databricks serverless compute
# (SIGABRT, no catchable exception) -- including Free Edition, which is
# serverless-only. Learned the hard way on the weather-app homework;
# applied here from the start rather than as a later fix.

EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "databricks-gte-large-en")

# VECTOR(N) columns must match the model's output width exactly. Rather
# than hardcoding 1024 in every SQL file and every call site, look the
# dimension up from the model name so swapping models means changing this
# map plus the two VECTOR(N) declarations in sql/12 and sql/13.
_MODEL_DIMENSIONS = {
    "databricks-gte-large-en": 1024,
    "databricks-bge-large-en": 1024,
    # Local sentence-transformers models -- only usable on classic
    # (non-serverless) compute, where the torch crash above doesn't apply.
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "BAAI/bge-large-en-v1.5": 1024,
}


def embedding_dimension(model_name: str = EMBEDDING_MODEL_NAME) -> int:
    """Return the vector width for a supported embedding model."""
    try:
        return _MODEL_DIMENSIONS[model_name]
    except KeyError:
        raise ValueError(
            f"Unknown embedding model {model_name!r}. Add its output dimension "
            "to _MODEL_DIMENSIONS in config.py, then update the VECTOR(N) "
            "columns in sql/12_create_job_posting_embeddings.sql and "
            "sql/13_add_profile_resume_embedding.sql to match."
        ) from None


EMBEDDING_DIM = embedding_dimension()

# --------------------------------------------------------------------------
# Chunking (Phase 2)
# --------------------------------------------------------------------------
# Job descriptions range from a two-line RemoteOK blurb to a multi-page
# federal qualification summary. 800 characters / 100 overlap is the same
# setting proven on the weather-app homework's similarly prose-length
# narratives -- a no-op for short postings, meaningful for long ones.

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "100"))

# Retrieval guardrails for POST /jobs/search.
MIN_TOP_K = 1
MAX_TOP_K = 20
DEFAULT_TOP_K = 10

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
