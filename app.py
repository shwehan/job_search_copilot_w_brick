"""
AI Job Hunting Copilot -- Phase 1: data foundation.

Harvests postings from Adzuna, USAJobs, and RemoteOK, normalizes them to one
schema, and stores them in Lakebase. This is deliberately the whole scope of
Phase 1 -- no embeddings, no search, no agent yet. See CAPSTONE_PLAN.md for
what Phases 2+ add on top of this.

Routes
    GET  /healthz        Liveness + Lakebase reachability + table presence
    GET  /jobs/stats      Row counts and coverage by source
    POST /jobs/sync        Harvest postings for a list of search queries
    GET  /jobs             Browse synced postings

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
    status = getattr(err, "code", 500)
    if not isinstance(status, int):
        status = 500

    if isinstance(err, lakebase.DatabaseError) and lakebase.sqlstate(err) == _UNDEFINED_TABLE:
        return jsonify({"error": "Table not found. " + _SETUP_HINT}), 503

    logger.exception("Unhandled error while processing %s", request.path)
    return jsonify({"error": str(err)}), status


def _json_body() -> dict:
    return request.get_json(silent=True) or {}


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

    sql = f"""
        SELECT id, source, title, company, location, remote,
               salary_min, salary_max, salary_currency, employment_type,
               category, left(description_text, 300) AS description_preview,
               apply_url, posted_at, synced_at
        FROM {config.JOB_POSTINGS_TABLE}
    """
    clauses = []
    params: list = []
    if source:
        clauses.append("source = %s")
        params.append(source)
    if remote_only:
        clauses.append("remote = true")
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


if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_RUN_PORT", "8000"))
    app.run(
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", host=host, port=port
    )
