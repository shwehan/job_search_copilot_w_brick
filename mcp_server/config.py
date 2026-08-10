"""Configuration for the independently deployed MCP Databricks App."""

import os

EMBEDDING_MODEL = os.environ.get("DATABRICKS_EMBEDDING_MODEL", "databricks-gte-large-en")
EMBEDDING_DIMENSION = 1024
MAX_TOP_K = 20
CHAT_MODEL = os.environ.get("DATABRICKS_CHAT_MODEL", "databricks-claude-sonnet-4-5")
