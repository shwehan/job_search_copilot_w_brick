import unittest
import sys
import types
from unittest.mock import MagicMock, patch

# Mock config before importing embedding_client
fake_config = types.ModuleType("config")
fake_config.EMBEDDING_MODEL = "databricks-gte-large-en"
fake_config.EMBEDDING_DIMENSION = 1024
sys.modules["config"] = fake_config

# Mock databricks.sdk.WorkspaceClient before importing embedding_client
fake_databricks = types.ModuleType("databricks")
fake_sdk = types.ModuleType("databricks.sdk")
fake_sdk.WorkspaceClient = MagicMock
fake_databricks.sdk = fake_sdk
sys.modules["databricks"] = fake_databricks
sys.modules["databricks.sdk"] = fake_sdk

import embedding_client


class EmbeddingClientTests(unittest.TestCase):
    def test_embed_query_uses_input_parameter(self):
        """Verify that embed_query calls serving_endpoints.query with input=[text], not inputs=[text]."""
        # Create a mock response with proper structure
        mock_embedding_data = MagicMock()
        mock_embedding_data.embedding = [0.1] * 1024  # 1024-dimensional vector
        
        mock_response = MagicMock()
        mock_response.data = [mock_embedding_data]
        
        # Create mock client with serving_endpoints
        mock_client = MagicMock()
        mock_client.serving_endpoints.query = MagicMock(return_value=mock_response)
        
        # Patch the _client function to return our mock
        with patch.object(embedding_client, "_client", return_value=mock_client):
            result = embedding_client.embed_query("test query")
            
            # Verify the query method was called with the correct parameter name
            mock_client.serving_endpoints.query.assert_called_once_with(
                name="databricks-gte-large-en",
                input=["test query"]  # Should be 'input', not 'inputs'
            )
            
            # Verify result is a properly formatted pgvector string
            self.assertIsInstance(result, str)
            self.assertTrue(result.startswith("["))
            self.assertTrue(result.endswith("]"))
            self.assertIn(",", result)
    
    def test_embed_query_validates_dimension(self):
        """Verify that embed_query raises error for incorrect vector dimension."""
        # Create a mock response with wrong dimension
        mock_embedding_data = MagicMock()
        mock_embedding_data.embedding = [0.1] * 512  # Wrong dimension (should be 1024)
        
        mock_response = MagicMock()
        mock_response.data = [mock_embedding_data]
        
        mock_client = MagicMock()
        mock_client.serving_endpoints.query = MagicMock(return_value=mock_response)
        
        with patch.object(embedding_client, "_client", return_value=mock_client):
            with self.assertRaisesRegex(RuntimeError, "unexpected vector dimension"):
                embedding_client.embed_query("test query")
    
    def test_embed_query_handles_dict_response(self):
        """Verify that embed_query can parse embedding from dict response."""
        # Create a mock response with dict structure
        mock_response = MagicMock()
        mock_response.data = [{"embedding": [0.2] * 1024}]
        
        mock_client = MagicMock()
        mock_client.serving_endpoints.query = MagicMock(return_value=mock_response)
        
        with patch.object(embedding_client, "_client", return_value=mock_client):
            result = embedding_client.embed_query("test query")
            
            # Verify it still calls with 'input' parameter
            mock_client.serving_endpoints.query.assert_called_once_with(
                name="databricks-gte-large-en",
                input=["test query"]
            )
            
            # Verify result is valid
            self.assertIsInstance(result, str)
            self.assertTrue(result.startswith("["))


if __name__ == "__main__":
    unittest.main()
