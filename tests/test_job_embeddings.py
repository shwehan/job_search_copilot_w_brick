import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

fake_lakebase = types.ModuleType("lakebase")
fake_lakebase.run_query = lambda *args, **kwargs: []
fake_lakebase.get_connection = lambda: None
fake_lakebase.execute_values = lambda *args, **kwargs: None
sys.modules.setdefault("lakebase", fake_lakebase)

import embedding_model
from job_embeddings import build_search_sql, chunk_text


class ChunkingTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_text("short description", 100, 10), ["short description"])

    def test_long_text_has_overlap(self):
        chunks = chunk_text("abcdefghijklmnopqrstuvwxyz", 10, 2)
        self.assertEqual(chunks[0][-2:], chunks[1][:2])
        self.assertGreater(len(chunks), 1)

    def test_invalid_overlap(self):
        with self.assertRaises(ValueError):
            chunk_text("text", 10, 10)


class SearchSQLTests(unittest.TestCase):
    def test_filters_are_parameterized_and_jobs_are_deduplicated(self):
        sql, params = build_search_sql({
            "sources": ["adzuna", "remoteok"],
            "remote_only": True,
            "minimum_salary": 100000,
            "location": "New York",
        })
        self.assertIn("SELECT DISTINCT ON (id)", sql)
        self.assertIn("ORDER BY e.embedding <=> %s::vector", sql)
        self.assertIn("p.source IN (%s,%s)", sql)
        self.assertIn("p.remote = true", sql)
        self.assertNotIn("New York", sql)
        self.assertIn("%New York%", params)


class HostedEmbeddingTests(unittest.TestCase):
    def test_batch_response_dimension(self):
        item = types.SimpleNamespace(embedding=[0.1] * 1024)
        client = Mock()
        client.serving_endpoints.query.return_value = types.SimpleNamespace(data=[item])
        with patch.object(embedding_model, "_workspace_client", return_value=client):
            vectors = embedding_model.embed_texts(["data engineering role"])
        self.assertEqual(len(vectors[0]), 1024)

    def test_wrong_dimension_is_rejected(self):
        item = types.SimpleNamespace(embedding=[0.1] * 10)
        client = Mock()
        client.serving_endpoints.query.return_value = types.SimpleNamespace(data=[item])
        with patch.object(embedding_model, "_workspace_client", return_value=client):
            with self.assertRaises(embedding_model.EmbeddingError):
                embedding_model.embed_texts(["data engineering role"])


if __name__ == "__main__":
    unittest.main()
