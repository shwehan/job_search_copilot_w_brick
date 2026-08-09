"""
Resolves a credential from an environment variable (local dev) or a
base64-encoded Databricks secret (deployed App / notebook), the same
two-step pattern ``lakebase.lakebase_url()`` uses for the connection URL.

Every credential in this project follows this resolution order so that
local development never needs Databricks auth configured, as long as the
plain values are set in the environment (see ``.env.example``).
"""

import base64
import os
from functools import lru_cache


@lru_cache(maxsize=None)
def get_secret(env_var: str, scope: str, key: str) -> str:
    """Return a credential, preferring the environment over a Databricks secret.

    Databricks secrets in this project are stored base64-encoded (matching
    ``setup_secrets.py`` and the Lakebase URL secret's own convention), so
    the value fetched from Databricks is decoded before being returned. A
    plain environment variable is used as-is, with no decoding, since it
    was typed in directly rather than base64-encoded by ``setup_secrets.py``.
    """
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        return env_val

    from databricks.sdk import WorkspaceClient

    secret = WorkspaceClient().secrets.get_secret(scope=scope, key=key)
    return base64.b64decode(secret.value).decode("utf-8")


def get_secret_or_empty(env_var: str, scope: str, key: str) -> str:
    """Same as ``get_secret``, but returns "" instead of raising when unset.

    Used for optional credentials (e.g. USAJobs, if you haven't registered
    for a key yet) so a missing one just disables that source rather than
    crashing the app.
    """
    try:
        return get_secret(env_var, scope, key)
    except Exception:
        return ""
