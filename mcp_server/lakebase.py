"""Small pg8000 Lakebase helper for the isolated MCP App deployment."""

import base64
import os
import ssl
from contextlib import contextmanager
from functools import lru_cache
from urllib.parse import urlparse

import pg8000.dbapi as pg8000


@lru_cache(maxsize=1)
def lakebase_url() -> str:
    value = os.environ.get("LAKEBASE_URL", "").strip()
    if value:
        return value
    from databricks.sdk import WorkspaceClient
    secret = WorkspaceClient().secrets.get_secret(
        scope=os.environ.get("LAKEBASE_SECRET_SCOPE", "database"),
        key=os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url"),
    )
    return base64.b64decode(secret.value).decode("utf-8")


@contextmanager
def get_connection():
    parsed = urlparse(lakebase_url())
    conn = pg8000.connect(
        user=parsed.username, password=parsed.password, host=parsed.hostname,
        port=parsed.port or 5432, database=parsed.path.lstrip("/") or "databricks_postgres",
        ssl_context=ssl.create_default_context(), timeout=15,
    )
    try:
        yield conn
    finally:
        conn.close()


def _dicts(cursor):
    columns = [item[0] for item in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()] if columns else []


def query(sql: str, params: tuple = ()) -> list[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            return _dicts(cursor)
        finally:
            cursor.close()


def write_returning(sql: str, params: tuple = ()) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            rows = _dicts(cursor)
            conn.commit()
            return rows[0] if rows else {}
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

