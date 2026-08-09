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


def _unwrap_if_double_encoded(value: str) -> str:
    """Undo an accidental extra layer of base64, if and only if it's provably safe.

    This project's convention is: values from a plain environment variable
    are used as-is (a human typed them in), values from a Databricks secret
    are base64-decoded (that's how setup_secrets.py stores them). That
    breaks if the *environment variable itself* ends up holding the raw
    stored secret bytes -- which happens if a credential is wired up as an
    "environment variable from a secret" in the Databricks Apps UI, rather
    than left for this module's own WorkspaceClient call to resolve. In
    that case the env var holds the still-base64-encoded value, and it gets
    used un-decoded: an Adzuna app_id like "37602e02" is sent to the API as
    the literal string "Mzc2MDJlMDI=" instead, and a Lakebase URL becomes an
    unparseable blob (no scheme, no host, no username).

    Rather than trying to prevent that misconfiguration, this detects and
    undoes it safely: a decode is only trusted if it produces valid,
    printable UTF-8 text *and* re-encoding that text reproduces the
    original string exactly. That round-trip check is what makes this safe
    to run unconditionally -- a genuinely plain value (an API key that
    happens to use only base64-alphabet characters, for instance) will not
    round-trip through an unrelated decode-then-re-encode, so it's left
    untouched. Only a value that really is base64 survives the check.
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
