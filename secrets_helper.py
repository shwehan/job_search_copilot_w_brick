"""
Resolves a credential from an environment variable (local dev) or a
Databricks secret (deployed App / notebook), the same
two-step pattern ``lakebase.lakebase_url()`` uses for the connection URL.

Every credential in this project follows this resolution order so that
local development never needs Databricks auth configured, as long as the
plain values are set in the environment (see ``.env.example``).
"""

import os
from functools import lru_cache


@lru_cache(maxsize=None)
def get_secret(env_var: str, scope: str, key: str) -> str:
    """Return a credential, preferring the environment over a Databricks secret.

    Databricks secrets in this project are stored as plain text (encrypted
    by Databricks), so the value fetched is returned directly. Environment
    variables are also used as-is.
    """
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        return _unwrap_if_double_encoded(env_val)

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
