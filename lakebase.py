"""
Lakebase (Databricks-managed Postgres) connection helper.

Uses **pg8000**, a pure-Python PostgreSQL driver, not psycopg2. psycopg2's
compiled C extension reliably crashes the whole Python kernel on Databricks
serverless compute -- including Databricks Free Edition, which is
serverless-only -- with a SIGABRT the moment it's imported. pg8000 speaks the
Postgres wire protocol directly in Python, so there's no compiled extension
to conflict with. This was learned the hard way on the weather-app homework;
here it's the starting point, not a later fix.

The connection string is a standard Postgres URL:

    postgresql://role:password@host.database.cloud.databricks.com:5432/databricks_postgres?sslmode=require

Resolved in this order:

1. The ``LAKEBASE_URL`` environment variable, for local development.
2. A base64-encoded Databricks secret (scope ``database``, key
   ``lakebase-url`` by default) -- how the deployed Databricks App and any
   notebook get their credentials.

Every write in this project goes through pg8000. There is no Spark JDBC
anywhere in the pipeline, because JDBC cannot write to pgvector's ``VECTOR``
type (added in Phase 2) or use ``ON CONFLICT`` for idempotent upserts.
"""

import base64
import os
import ssl
from contextlib import contextmanager
from functools import lru_cache
from urllib.parse import urlparse

import pg8000.dbapi as pg8000

_SCOPE = os.environ.get("LAKEBASE_SECRET_SCOPE", "database")
_KEY = os.environ.get("LAKEBASE_SECRET_KEY", "lakebase-url")

# pg8000's DB-API paramstyle is "format" (%s), same as psycopg2's.
DatabaseError = pg8000.DatabaseError


def _unwrap_if_double_encoded(value: str) -> str:
    """Undo an accidental extra layer of base64, if and only if it's provably safe.

    Guards against the same misconfiguration secrets_helper.py guards
    against: if LAKEBASE_URL is wired up as an "environment variable from a
    secret" in the Databricks Apps UI rather than left for this module's
    own WorkspaceClient call to resolve, the env var ends up holding the
    raw base64-encoded bytes this project's setup_secrets.py stored --  not
    a valid postgresql:// URL. urlparse() on that blob silently returns
    empty components rather than raising, so the failure doesn't surface
    until pg8000.connect(user=None, ...) rejects it.

    The decode is only trusted if it produces valid, printable UTF-8 text
    *and* re-encoding that text reproduces the original string exactly --
    a real Lakebase URL (colons, slashes, an '@', a '?') will never
    accidentally pass that round-trip check, so this is safe to run
    unconditionally.
    """
    try:
        decoded = base64.b64decode(value, validate=True)
        text = decoded.decode("utf-8")
    except Exception:
        return value
    if not text.isprintable():
        return value
    if base64.b64encode(text.encode("utf-8")).decode("ascii") != value:
        return value
    return text


@lru_cache(maxsize=1)
def lakebase_url() -> str:
    """Resolve the Lakebase connection URL from the environment or a secret."""
    env_url = os.environ.get("LAKEBASE_URL", "").strip()
    if env_url:
        return _unwrap_if_double_encoded(env_url)

    from databricks.sdk import WorkspaceClient

    secret = WorkspaceClient().secrets.get_secret(scope=_SCOPE, key=_KEY)
    return base64.b64decode(secret.value).decode("utf-8")


def connection_parts() -> dict:
    """Split the Lakebase URL into pg8000 connect() keyword arguments."""
    parsed = urlparse(lakebase_url())
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") or "databricks_postgres",
        "user": parsed.username,
        "password": parsed.password,
        "sslmode": "require",
    }


@contextmanager
def get_connection():
    """Yield a pg8000 DB-API connection."""
    parts = connection_parts()
    conn = pg8000.connect(
        user=parts["user"],
        password=parts["password"],
        host=parts["host"],
        port=parts["port"],
        database=parts["dbname"],
        ssl_context=ssl.create_default_context(),
        timeout=15,
    )
    try:
        yield conn
    finally:
        conn.close()


def _rows_as_dicts(cursor) -> list[dict]:
    """Turn a pg8000 cursor's result into a list of dicts, keyed by column name."""
    if cursor.description is None:
        return []
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def run_query(sql: str, params: tuple | None = None) -> list[dict]:
    """Run a read query and return the rows as a list of dicts."""
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            return _rows_as_dicts(cursor)
        finally:
            cursor.close()


def run_write(sql: str, params: tuple | None = None) -> int:
    """Run an INSERT/UPDATE/DELETE/DDL statement and return the row count."""
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
        finally:
            cursor.close()


def execute_values(
    cursor,
    sql: str,
    argslist: list[tuple],
    template: str | None = None,
    page_size: int = 100,
) -> None:
    """Batch-insert many rows in one round trip per page.

    A minimal, pg8000-compatible replacement for
    ``psycopg2.extras.execute_values``. ``sql`` must contain the literal
    marker ``VALUES %s`` showing where the batch of row tuples goes;
    everything before it becomes the INSERT prefix and everything after it
    (an ``ON CONFLICT`` clause, typically) is kept as a suffix. ``template``
    describes one row -- e.g. ``"(%s, %s, %s::vector)"`` -- exactly as
    psycopg2's own ``template`` argument does.
    """
    if not argslist:
        return
    if "VALUES %s" not in sql:
        raise ValueError('sql must contain a literal "VALUES %s" placeholder')
    prefix, _, suffix = sql.partition("VALUES %s")

    if template is None:
        template = "(" + ", ".join(["%s"] * len(argslist[0])) + ")"

    for start in range(0, len(argslist), page_size):
        batch = argslist[start : start + page_size]
        row_sql = ", ".join([template] * len(batch))
        flat_params = [value for row in batch for value in row]
        cursor.execute(f"{prefix}VALUES {row_sql}{suffix}", flat_params)


def sqlstate(error: Exception) -> str | None:
    """Extract the PostgreSQL SQLSTATE code from a pg8000 DatabaseError.

    Used to detect e.g. undefined-table (``42P01``) without depending on
    psycopg2's exception subclasses.
    """
    if error.args and isinstance(error.args[0], dict):
        return error.args[0].get("C")
    return None


def table_exists(table_name: str) -> bool:
    """Check whether a table is present in the current search path."""
    rows = run_query(
        "SELECT to_regclass(%s) IS NOT NULL AS present", (table_name,)
    )
    return bool(rows and rows[0]["present"])


def ping() -> dict:
    """Return a small health payload describing the Lakebase connection."""
    parts = connection_parts()
    rows = run_query("SELECT version() AS version, current_database() AS database")
    return {
        "host": parts["host"],
        "database": parts["dbname"],
        "user": parts["user"],
        "server_version": rows[0]["version"].split(",")[0] if rows else None,
    }
