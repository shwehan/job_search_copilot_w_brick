"""
Writes normalized job-posting documents into Lakebase.

Mirrors the weather-app homework's ``upsert_documents`` pattern: batched
``execute_values`` with an ``ON CONFLICT`` clause keyed on a stable id, so
re-running a sync is always safe -- an unchanged posting just overwrites
itself with identical values, and a re-fetched posting with edited text
updates in place rather than duplicating.
"""

from __future__ import annotations

import json
from typing import Iterable

import config
import lakebase

_COLUMNS = (
    "id",
    "source",
    "external_id",
    "title",
    "company",
    "location",
    "remote",
    "salary_min",
    "salary_max",
    "salary_currency",
    "employment_type",
    "category",
    "description_text",
    "apply_url",
    "posted_at",
    "content_hash",
    "payload",
)


def upsert_job_postings(documents: Iterable[dict], page_size: int = 100) -> int:
    """Insert or update job postings, keyed on the stable ``id``."""
    rows = []
    for doc in documents:
        rows.append(
            tuple(
                json.dumps(doc.get(column)) if column == "payload" else doc.get(column)
                for column in _COLUMNS
            )
        )

    if not rows:
        return 0

    column_list = ", ".join(_COLUMNS)
    updates = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in _COLUMNS if column != "id"
    )
    sql = f"""
        INSERT INTO {config.JOB_POSTINGS_TABLE} ({column_list}, synced_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE
            SET {updates},
                synced_at = now()
    """
    template = "(" + ", ".join(["%s"] * len(_COLUMNS)) + ", now())"

    with lakebase.get_connection() as conn:
        cursor = conn.cursor()
        try:
            lakebase.execute_values(
                cursor, sql, rows, template=template, page_size=page_size
            )
            conn.commit()
        finally:
            cursor.close()
    return len(rows)


def stats() -> dict:
    """Row counts and coverage across the harvested postings."""
    rows = lakebase.run_query(
        f"""
        SELECT source, count(*) AS postings,
               count(*) FILTER (WHERE remote) AS remote_postings,
               max(synced_at) AS last_synced_at
        FROM {config.JOB_POSTINGS_TABLE}
        GROUP BY source
        ORDER BY source
        """
    )
    total = lakebase.run_query(
        f"SELECT count(*) AS total, max(synced_at) AS last_synced_at FROM {config.JOB_POSTINGS_TABLE}"
    )[0]

    def _iso(value):
        return value.isoformat() if value is not None else None

    return {
        "total_postings": int(total["total"] or 0),
        "last_synced_at": _iso(total["last_synced_at"]),
        "by_source": [
            {
                "source": row["source"],
                "postings": int(row["postings"] or 0),
                "remote_postings": int(row["remote_postings"] or 0),
                "last_synced_at": _iso(row["last_synced_at"]),
            }
            for row in rows
        ],
    }
