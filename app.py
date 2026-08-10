"""
AI Job Hunting Copilot -- Phases 1-3: ingestion, retrieval, and workflow.

Harvests postings from Adzuna, USAJobs, and RemoteOK, normalizes them to one
schema, and stores them in Lakebase. Phase 2 adds hosted GTE embeddings and
configurable top-K pgvector search.

Routes
    GET  /healthz        Liveness + Lakebase reachability + table presence
    GET  /jobs/stats      Row counts and coverage by source
    POST /jobs/sync        Harvest postings for a list of search queries
    GET  /jobs             Browse synced postings
    GET  /jobs/embeddings/status  Embedding coverage
    POST /jobs/embed       Embed new/changed postings
    POST /jobs/search      Semantic top-K retrieval

Run locally:
    python app.py
"""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, render_template, request

import config
import ingestion
import lakebase
import secrets_helper
import job_embeddings
import workflow_service
from job_client import AdzunaClient, JobSearchClient, RemoteOKClient, USAJobsClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job-hunting-copilot")

app = Flask(__name__)

_SETUP_HINT = (
    "Run the scripts in sql/ against your Lakebase database to create the "
    "schema before using this endpoint."
)

# Undefined-table is SQLSTATE 42P01.
_UNDEFINED_TABLE = "42P01"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@app.errorhandler(Exception)
def handle_exception(err):
    """Always answer with JSON so a fetch().json() caller never sees HTML."""
    status = 400 if isinstance(err, ValueError) else getattr(err, "code", 500)
    if isinstance(err, LookupError):
        status = 404
    if not isinstance(status, int):
        status = 500

    if isinstance(err, lakebase.DatabaseError) and lakebase.sqlstate(err) == _UNDEFINED_TABLE:
        return jsonify({"error": "Table not found. " + _SETUP_HINT}), 503

    logger.exception("Unhandled error while processing %s", request.path)
    return jsonify({"error": str(err)}), status


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


def _user_id(body: dict | None = None) -> str:
    value = ((body or {}).get("user_id") or request.args.get("user_id") or "").strip()
    if not value:
        raise ValueError("user_id is required. Select your workspace identity first.")
    return value


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def _build_job_search_client() -> JobSearchClient:
    """Build clients for whichever sources have credentials configured.

    Credentials are resolved via ``secrets_helper``, which checks the
    environment first (local dev) and falls back to a base64-encoded
    Databricks secret in the ``database`` scope (deployed App). A source
    with no key set is simply omitted -- e.g. running without a USAJobs key
    yet still works, it just skips that source.
    """
    adzuna = None
    adzuna_app_id = secrets_helper.get_secret_or_empty(
        "ADZUNA_APP_ID", "database", "adzuna-app-id"
    )
    adzuna_app_key = secrets_helper.get_secret_or_empty(
        "ADZUNA_APP_KEY", "database", "adzuna-app-key"
    )
    if adzuna_app_id and adzuna_app_key:
        adzuna = AdzunaClient(
            adzuna_app_id, adzuna_app_key, country=config.DEFAULT_ADZUNA_COUNTRY
        )

    usajobs = None
    usajobs_key = secrets_helper.get_secret_or_empty(
        "USAJOBS_API_KEY", "database", "usajobs-api-key"
    )
    usajobs_email = secrets_helper.get_secret_or_empty(
        "USAJOBS_EMAIL", "database", "usajobs-email"
    )
    if usajobs_key and usajobs_email:
        usajobs = USAJobsClient(usajobs_key, usajobs_email)

    # RemoteOK needs no key -- always available.
    remoteok = RemoteOKClient(contact=usajobs_email or "not set")

    return JobSearchClient(adzuna=adzuna, usajobs=usajobs, remoteok=remoteok)


# ---------------------------------------------------------------------------
# Pages and health
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    payload = {"status": "ok"}
    try:
        payload["lakebase"] = lakebase.ping()
        payload["tables"] = {
            table: lakebase.table_exists(table)
            for table in (
                config.USERS_TABLE,
                config.PROFILES_TABLE,
                config.SKILLS_TABLE,
                config.JOB_POSTINGS_TABLE,
                config.APPLICATIONS_TABLE,
                config.SAVED_JOBS_TABLE,
                config.INTERVIEW_NOTES_TABLE,
                config.CONTACTS_TABLE,
            )
        }
        payload["sources_configured"] = {
            "adzuna": bool(
                secrets_helper.get_secret_or_empty("ADZUNA_APP_ID", "database", "adzuna-app-id")
                and secrets_helper.get_secret_or_empty("ADZUNA_APP_KEY", "database", "adzuna-app-key")
            ),
            "usajobs": bool(
                secrets_helper.get_secret_or_empty("USAJOBS_API_KEY", "database", "usajobs-api-key")
                and secrets_helper.get_secret_or_empty("USAJOBS_EMAIL", "database", "usajobs-email")
            ),
            "remoteok": True,
        }
    except Exception as exc:
        payload["status"] = "degraded"
        payload["error"] = str(exc)
        return jsonify(payload), 503
    return jsonify(payload)


@app.route("/jobs/stats")
def jobs_stats():
    return jsonify(ingestion.stats())


# ---------------------------------------------------------------------------
# Harvest
# ---------------------------------------------------------------------------


@app.route("/jobs/sync", methods=["POST"])
def jobs_sync():
    """Harvest postings for a list of search queries into Lakebase.

    Body: {"queries": [{"keyword": "data engineer", "location": "Austin, TX"}],
           "limit_per_source": 50}

    ``queries`` may also be a flat list of keyword strings, in which case
    every keyword is searched with no location filter.
    """
    body = _json_body()

    raw_queries = body.get("queries") or [
        {"keyword": kw, "location": config.DEFAULT_LOCATION}
        for kw in config.DEFAULT_SEARCH_QUERIES
    ]
    queries = []
    for entry in raw_queries:
        if isinstance(entry, str):
            queries.append({"keyword": entry, "location": config.DEFAULT_LOCATION})
        elif isinstance(entry, dict) and entry.get("keyword"):
            queries.append(
                {"keyword": entry["keyword"], "location": entry.get("location", "")}
            )
    if not queries:
        return jsonify({"error": "Provide at least one query keyword."}), 400
    if len(queries) > 15:
        return jsonify({"error": "Sync at most 15 queries per request."}), 400

    try:
        limit_per_source = max(
            1, min(int(body.get("limit_per_source", config.DEFAULT_SYNC_LIMIT)), 200)
        )
    except (TypeError, ValueError):
        return jsonify({"error": "limit_per_source must be an integer."}), 400

    client = _build_job_search_client()
    if not (client.adzuna or client.usajobs or client.remoteok):
        return jsonify(
            {"error": "No job sources configured. Set at least Adzuna or USAJobs credentials."}
        ), 503

    documents, errors = client.fetch_all(queries, limit_per_source=limit_per_source)
    synced = ingestion.upsert_job_postings(documents)

    by_source: dict[str, int] = {}
    for doc in documents:
        by_source[doc["source"]] = by_source.get(doc["source"], 0) + 1

    return jsonify(
        {
            "synced": synced,
            "by_source": by_source,
            "queries": queries,
            "errors": errors,
        }
    )


@app.route("/jobs")
def jobs_browse():
    """Browse synced postings, newest first."""
    limit = max(1, min(int(request.args.get("limit", 25)), 200))
    source = request.args.get("source", "").strip().lower()
    remote_only = request.args.get("remote_only", "").lower() in ("1", "true", "yes")
    relevant_only = request.args.get("relevant_only", "").lower() in ("1", "true", "yes")
    user_id = request.args.get("user_id", "").strip()  # Optional: specify user

    clauses = []
    params: list = []
    
    # If relevant_only is enabled, join with profiles table and filter
    if relevant_only:
        # Get the default profile for the user (or first available profile)
        profile_query = f"""
            SELECT target_roles, remote_preference, salary_min, 
                   salary_currency, locations_preferred
            FROM {config.PROFILES_TABLE}
        """
        if user_id:
            profile_query += " WHERE user_id = %s AND is_default = true LIMIT 1"
            profile_params = (user_id,)
        else:
            profile_query += " WHERE is_default = true LIMIT 1"
            profile_params = ()
        
        profile_rows = lakebase.run_query(profile_query, profile_params)
        if not profile_rows:
            # No profile found, return empty result
            return jsonify({"postings": [], "count": 0, "message": "No profile found. Please create a profile first."})
        
        profile = profile_rows[0]
        
        # Build relevance filters based on profile
        # 1. Match target roles (case-insensitive search in title)
        if profile.get("target_roles"):
            role_conditions = []
            for role in profile["target_roles"]:
                role_conditions.append("LOWER(title) LIKE %s")
                params.append(f"%{role.lower()}%")
            if role_conditions:
                clauses.append(f"({' OR '.join(role_conditions)})")
        
        # 2. Match remote preference
        remote_pref = profile.get("remote_preference", "any")
        if remote_pref == "remote_only":
            clauses.append("remote = true")
        elif remote_pref == "onsite":
            clauses.append("remote = false")
        # 'hybrid' and 'any' don't add constraints
        
        # 3. Match minimum salary (if job specifies salary)
        if profile.get("salary_min"):
            # Only filter if job has salary info and it's >= user's minimum
            clauses.append("(salary_max IS NULL OR salary_max >= %s)")
            params.append(profile["salary_min"])
        
        # 4. Match preferred locations (if specified)
        if profile.get("locations_preferred") and len(profile["locations_preferred"]) > 0:
            location_conditions = []
            for loc in profile["locations_preferred"]:
                if loc.strip():
                    location_conditions.append("LOWER(location) LIKE %s")
                    params.append(f"%{loc.lower()}%")
            if location_conditions:
                # Jobs with no location or matching location, or remote jobs
                clauses.append(f"(remote = true OR location IS NULL OR {' OR '.join(location_conditions)})")
    
    # Apply legacy filters
    if source:
        clauses.append("source = %s")
        params.append(source)
    if remote_only:
        clauses.append("remote = true")
    
    # Build final query
    sql = f"""
        SELECT id, source, title, company, location, remote,
               salary_min, salary_max, salary_currency, employment_type,
               category, left(description_text, 300) AS description_preview,
               apply_url, posted_at, synced_at
        FROM {config.JOB_POSTINGS_TABLE}
    """
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY posted_at DESC NULLS LAST, synced_at DESC LIMIT %s"
    params.append(limit)

    rows = lakebase.run_query(sql, tuple(params))
    for row in rows:
        for key in ("posted_at", "synced_at"):
            if row.get(key) is not None:
                row[key] = row[key].isoformat()
    return jsonify({"postings": rows, "count": len(rows)})


# ---------------------------------------------------------------------------
# Phase 2: hosted embeddings and top-K retrieval
# ---------------------------------------------------------------------------


@app.route("/jobs/embeddings/status")
def jobs_embedding_status():
    if not lakebase.table_exists(config.JOB_EMBEDDINGS_TABLE):
        return jsonify({"error": "Run SQL 11-14 before embedding jobs."}), 503
    return jsonify(job_embeddings.embedding_status())


@app.route("/jobs/embed", methods=["POST"])
def jobs_embed():
    """Embed new or content-changed postings with the hosted GTE endpoint."""
    body = _json_body()
    try:
        limit = max(1, min(int(body.get("limit", 100)), 500))
        batch_size = max(1, min(int(body.get("batch_size", config.EMBEDDING_BATCH_SIZE)), 32))
    except (TypeError, ValueError):
        return jsonify({"error": "limit and batch_size must be integers."}), 400
    return jsonify(job_embeddings.embed_pending_postings(limit, batch_size))


@app.route("/jobs/search", methods=["POST"])
def jobs_semantic_search():
    """Return the top-K distinct jobs closest to a natural-language query."""
    body = _json_body()
    search_text = str(body.get("query") or "").strip()
    if not search_text:
        return jsonify({"error": "Provide a non-empty query."}), 400
    if len(search_text) > 2000:
        return jsonify({"error": "Query must be 2,000 characters or fewer."}), 400
    try:
        rows = job_embeddings.semantic_search(
            search_text,
            body.get("top_k", 5),
            sources=body.get("sources") or [],
            remote_only=bool(body.get("remote_only", False)),
            minimum_salary=body.get("minimum_salary"),
            location=body.get("location"),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"query": search_text, "top_k": len(rows), "postings": rows})


# ---------------------------------------------------------------------------
# Phase 3: profiles, resume, bookmarks, and application pipeline
# ---------------------------------------------------------------------------


@app.route("/api/users/session", methods=["POST"])
def create_user_session():
    """Get or create the selected development user (this is not authentication)."""
    body = _json_body()
    return jsonify(workflow_service.get_or_create_user(body.get("email"), body.get("display_name")))


@app.route("/api/profiles")
def profiles_list():
    return jsonify({"profiles": workflow_service.list_profiles(_user_id())})


@app.route("/api/profiles", methods=["POST"])
def profiles_create():
    body = _json_body()
    return jsonify(workflow_service.create_profile(_user_id(body), body)), 201


@app.route("/api/profiles/<profile_id>/resume", methods=["POST"])
def profiles_upload_resume(profile_id):
    """Accept a UTF-8 .txt/.md resume and store its text in Lakebase."""
    user_id = _user_id()
    upload = request.files.get("resume")
    if not upload or not upload.filename:
        return jsonify({"error": "Choose a .txt or .md resume file."}), 400
    suffix = os.path.splitext(upload.filename)[1].lower()
    if suffix not in (".txt", ".md"):
        return jsonify({"error": "Phase 3 accepts UTF-8 .txt or .md resumes."}), 400
    raw = upload.read(250001)
    if len(raw) > 250000:
        return jsonify({"error": "Resume file must be 250 KB or smaller."}), 400
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"error": "Resume must be UTF-8 text."}), 400
    row = workflow_service.upload_resume(user_id, profile_id, upload.filename, text)
    if not row:
        return jsonify({"error": "Profile not found for this user."}), 404
    return jsonify(row)


@app.route("/api/saved-jobs", methods=["POST"])
def saved_jobs_create():
    body = _json_body()
    return jsonify(workflow_service.save_job(
        _user_id(body), body.get("job_posting_id"), body.get("note")
    )), 201


@app.route("/api/saved-jobs/<job_posting_id>", methods=["DELETE"])
def saved_jobs_delete(job_posting_id):
    return jsonify({"deleted": workflow_service.unsave_job(_user_id(), job_posting_id)})


@app.route("/api/applications", methods=["POST"])
def applications_create():
    body = _json_body()
    return jsonify(workflow_service.track_application(
        _user_id(body), body.get("job_posting_id"), body.get("profile_id")
    )), 201


@app.route("/api/applications/<application_id>/stage", methods=["PATCH"])
def applications_update_stage(application_id):
    body = _json_body()
    return jsonify(workflow_service.update_application_stage(
        _user_id(body), application_id, str(body.get("stage") or "")
    ))


@app.route("/api/pipeline")
def pipeline_list():
    return jsonify(workflow_service.list_pipeline(_user_id()))


@app.route("/api/applications/<application_id>/notes", methods=["POST"])
def interview_notes_create(application_id):
    body = _json_body()
    row = workflow_service.add_interview_note(_user_id(body), application_id, body)
    if not row:
        return jsonify({"error": "Application not found for this user."}), 404
    return jsonify(row), 201


@app.route("/api/contacts", methods=["POST"])
def contacts_create():
    body = _json_body()
    return jsonify(workflow_service.add_contact(_user_id(body), body)), 201


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_RUN_PORT", "8000"))
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", host=host, port=port
    )
