"""Hosted Databricks GTE query embeddings; no local Torch model."""

from functools import lru_cache

from databricks.sdk import WorkspaceClient

import config


@lru_cache(maxsize=1)
def _client():
    return WorkspaceClient()


def embed_query(text: str) -> str:
    response = _client().serving_endpoints.query(
        name=config.EMBEDDING_MODEL, input=[text]
    )
    data = response.data or []
    vector = getattr(data[0], "embedding", None) if data else None
    if vector is None and data and isinstance(data[0], dict):
        vector = data[0].get("embedding")
    if not vector or len(vector) != config.EMBEDDING_DIMENSION:
        raise RuntimeError("Embedding endpoint returned an unexpected vector dimension.")
    return "[" + ",".join(str(float(value)) for value in vector) + "]"

