"""Phase 4 scheduled Spark pipeline for job harvesting and vector refresh.

HTTP calls run on the driver because the APIs are paginated external services.
Spark performs the data-engineering work: schema enforcement, text cleanup,
quality filtering, deduplication, and SHA-256 content hashing. The small,
normalized result is then upserted into operational Lakebase with pg8000.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import config
import ingestion
import job_embeddings
import lakebase
import secrets_helper
from job_client import AdzunaClient, JobSearchClient, RemoteOKClient, USAJobsClient


def build_source_client() -> JobSearchClient:
    adzuna_id = secrets_helper.get_secret_or_empty("ADZUNA_APP_ID", "database", "adzuna-app-id")
    adzuna_key = secrets_helper.get_secret_or_empty("ADZUNA_APP_KEY", "database", "adzuna-app-key")
    usa_key = secrets_helper.get_secret_or_empty("USAJOBS_API_KEY", "database", "usajobs-api-key")
    usa_email = secrets_helper.get_secret_or_empty("USAJOBS_EMAIL", "database", "usajobs-email")
    return JobSearchClient(
        adzuna=AdzunaClient(adzuna_id, adzuna_key, country=config.DEFAULT_ADZUNA_COUNTRY)
        if adzuna_id and adzuna_key else None,
        usajobs=USAJobsClient(usa_key, usa_email) if usa_key and usa_email else None,
        remoteok=RemoteOKClient(contact=usa_email or "job-copilot")
    )


def prepare_with_spark(spark, documents: list[dict]) -> tuple[list[dict], dict]:
    """Normalize unstructured job documents using Spark DataFrame operations."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import (BooleanType, DoubleType, StringType,
                                   StructField, StructType)

    fields = [
        ("id", StringType()), ("source", StringType()), ("external_id", StringType()),
        ("title", StringType()), ("company", StringType()), ("location", StringType()),
        ("remote", BooleanType()), ("salary_min", DoubleType()), ("salary_max", DoubleType()),
        ("salary_currency", StringType()), ("employment_type", StringType()),
        ("category", StringType()), ("description_text", StringType()),
        ("apply_url", StringType()), ("posted_at", StringType()), ("payload_json", StringType()),
    ]
    schema = StructType([StructField(name, kind, True) for name, kind in fields])
    rows = []
    for doc in documents:
        rows.append(tuple(
            json.dumps(doc.get("payload"), default=str) if name == "payload_json"
            else (float(doc[name]) if name in ("salary_min", "salary_max") and doc.get(name) is not None
                  else doc.get(name))
            for name, _ in fields
        ))
    frame = spark.createDataFrame(rows, schema=schema)
    input_rows = frame.count()
    clean_space = lambda name: F.trim(F.regexp_replace(F.col(name), r"\s+", " "))
    prepared = (
        frame
        .withColumn("title", clean_space("title"))
        .withColumn("company", clean_space("company"))
        .withColumn("location", clean_space("location"))
        .withColumn("description_text", clean_space("description_text"))
        .filter(F.col("id").isNotNull() & (F.length("title") > 0) & (F.length("description_text") >= 40))
        .withColumn("content_hash", F.sha2(F.col("description_text"), 256))
        .dropDuplicates(["id"])
    )
    output_rows = prepared.count()
    source_counts = {
        row["source"]: int(row["count"])
        for row in prepared.groupBy("source").count().collect()
    }
    result = []
    for row in prepared.collect():
        item = row.asDict()
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        result.append(item)
    return result, {
        "spark_input_rows": input_rows,
        "spark_output_rows": output_rows,
        "spark_rejected_or_duplicate_rows": input_rows - output_rows,
        "rows_by_source": source_counts,
    }


def _stale_applications(days: int) -> list[dict]:
    return lakebase.run_query(
        f"""SELECT a.id, a.user_id, a.job_posting_id, p.title, p.company,
                   a.stage, a.stage_updated_at
            FROM {config.APPLICATIONS_TABLE} a
            JOIN {config.JOB_POSTINGS_TABLE} p ON p.id = a.job_posting_id
            WHERE a.stage = 'applied'
              AND a.stage_updated_at < now() - (%s * interval '1 day')
            ORDER BY a.stage_updated_at""",
        (days,),
    )


def _refresh_stale_flags(days: int) -> list[dict]:
    """Persist the current stale/non-stale state for cheap agent retrieval."""
    with lakebase.get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"""UPDATE {config.APPLICATIONS_TABLE}
                    SET is_stale = false, stale_flagged_at = NULL
                    WHERE is_stale = true AND (
                        stage <> 'applied' OR
                        stage_updated_at >= now() - (%s * interval '1 day')
                    )""",
                (days,),
            )
            cursor.execute(
                f"""UPDATE {config.APPLICATIONS_TABLE}
                    SET is_stale = true,
                        stale_flagged_at = COALESCE(stale_flagged_at, now())
                    WHERE stage = 'applied'
                      AND stage_updated_at < now() - (%s * interval '1 day')""",
                (days,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    return _stale_applications(days)


def run_pipeline(spark, queries: list[dict], limit_per_source: int = 50,
                 embed_limit: int = 500, stale_days: int = 14) -> dict:
    """Execute harvest -> Spark transform -> Lakebase -> embed -> stale scan."""
    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    lakebase.run_write(
        f"""INSERT INTO {config.PIPELINE_RUNS_TABLE} (id, status, started_at, query_count)
           VALUES (%s, 'running', %s, %s)""",
        (run_id, started, len(queries)),
    )
    try:
        raw, source_errors = build_source_client().fetch_all(
            queries, limit_per_source=max(1, min(int(limit_per_source), 200))
        )
        prepared, spark_stats = prepare_with_spark(spark, raw)
        synced = ingestion.upsert_job_postings(prepared)
        embedding = job_embeddings.embed_pending_postings(
            limit=max(1, min(int(embed_limit), 500)), batch_size=config.EMBEDDING_BATCH_SIZE
        )
        stale = _refresh_stale_flags(max(1, int(stale_days)))
        finished = datetime.now(timezone.utc)
        summary = {
            "run_id": run_id, "status": "completed", "started_at": started.isoformat(),
            "finished_at": finished.isoformat(), "synced_postings": synced,
            "embedded_postings": embedding["embedded_postings"],
            "written_chunks": embedding["written_chunks"],
            "stale_applications": len(stale), "source_errors": source_errors,
            **spark_stats,
        }
        lakebase.run_write(
            f"""UPDATE {config.PIPELINE_RUNS_TABLE} SET status='completed', finished_at=%s,
               fetched_rows=%s, prepared_rows=%s, synced_rows=%s,
               embedded_postings=%s, written_chunks=%s, stale_applications=%s,
               source_errors=%s::jsonb, metrics=%s::jsonb WHERE id=%s""",
            (finished, len(raw), spark_stats["spark_output_rows"], synced,
             embedding["embedded_postings"], embedding["written_chunks"], len(stale),
             json.dumps(source_errors), json.dumps(summary), run_id),
        )
        return summary
    except Exception as exc:
        lakebase.run_write(
            f"""UPDATE {config.PIPELINE_RUNS_TABLE} SET status='failed', finished_at=now(),
               error_message=%s WHERE id=%s""", (str(exc)[:10000], run_id)
        )
        raise
