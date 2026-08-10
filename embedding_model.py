"""Databricks-hosted GTE embedding helper.

No sentence-transformers or Torch are loaded locally. Databricks identity is
used by WorkspaceClient, so no model-serving token is committed or stored.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable

import config


class EmbeddingError(RuntimeError):
    """A clean error raised when hosted embedding inference fails."""


@lru_cache(maxsize=1)
def _workspace_client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def clean_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        raise EmbeddingError("Text to embed cannot be empty.")
    return value


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    prepared = [clean_text(text) for text in texts]
    if not prepared:
        return []
    try:
        response = _workspace_client().serving_endpoints.query(
            name=config.EMBEDDING_MODEL,
            input=prepared,
        )
        vectors = [list(item.embedding) for item in (response.data or [])]
    except Exception as exc:
        raise EmbeddingError(
            f"Could not query {config.EMBEDDING_MODEL}. Confirm the endpoint name and CAN QUERY permission."
        ) from exc

    if len(vectors) != len(prepared):
        raise EmbeddingError(
            f"Expected {len(prepared)} embeddings but received {len(vectors)}."
        )
    for vector in vectors:
        if len(vector) != config.EMBEDDING_DIMENSION:
            raise EmbeddingError(
                f"Expected {config.EMBEDDING_DIMENSION} dimensions but received {len(vector)}."
            )
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def vector_literal(vector: Iterable[float]) -> str:
    values = [float(value) for value in vector]
    if len(values) != config.EMBEDDING_DIMENSION:
        raise EmbeddingError(
            f"Vector must contain {config.EMBEDDING_DIMENSION} values."
        )
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"

