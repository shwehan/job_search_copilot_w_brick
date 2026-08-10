import unittest
import sys
import types
from unittest.mock import patch

fake_lakebase = types.ModuleType("lakebase")
fake_lakebase.query = lambda *args, **kwargs: []
fake_lakebase.write_returning = lambda *args, **kwargs: {}
sys.modules["lakebase"] = fake_lakebase

fake_embedding = types.ModuleType("embedding_client")
fake_embedding.embed_query = lambda text: "[0]"
sys.modules["embedding_client"] = fake_embedding

fake_model = types.ModuleType("model_client")
fake_model.generate = lambda *args, **kwargs: "Grounded draft"
sys.modules["model_client"] = fake_model

fake_requests = types.ModuleType("requests")
fake_requests.get = lambda *args, **kwargs: None
sys.modules["requests"] = fake_requests

import job_adapter


class AdapterValidationTests(unittest.TestCase):
    def test_invalid_stage_does_not_call_database(self):
        with patch.object(job_adapter.lakebase, "query") as query:
            with self.assertRaisesRegex(ValueError, "stage must be"):
                job_adapter.update_pipeline_stage("user@example.com", "job:1", "waiting")
            query.assert_not_called()

    def test_invalid_follow_up_date_is_clean_validation_error(self):
        with patch.object(job_adapter, "user_by_email", return_value={"id": "u"}):
            with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
                job_adapter.log_interview_note(
                    "user@example.com", "job:1", "Follow up", "tomorrow"
                )

    def test_unknown_user_has_no_default_fallback(self):
        with patch.object(job_adapter.lakebase, "query", return_value=[]):
            with self.assertRaisesRegex(ValueError, "No user exists"):
                job_adapter.user_by_email("missing@example.com")

    def test_invalid_feedback_is_clean_validation_error(self):
        with patch.object(job_adapter, "user_by_email", return_value={"id": "u"}):
            with self.assertRaisesRegex(ValueError, "good, bad, or skip"):
                job_adapter.record_feedback("user@example.com", "job:1", "maybe")


if __name__ == "__main__":
    unittest.main()
