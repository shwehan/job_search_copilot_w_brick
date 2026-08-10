"""Grounded text generation through a Databricks-hosted chat endpoint."""

from functools import lru_cache

from databricks.sdk import WorkspaceClient

import config


@lru_cache(maxsize=1)
def _workspace():
    return WorkspaceClient()


def generate(system: str, user: str, max_tokens: int = 350) -> str:
    response = _workspace().api_client.do(
        "POST", f"/api/2.0/serving-endpoints/{config.CHAT_MODEL}/invocations",
        body={"messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}],
              "max_tokens": max_tokens, "temperature": 0.2},
    )
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("Chat model returned no choices.")
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        raise RuntimeError("Chat model returned empty content.")
    return str(content).strip()
