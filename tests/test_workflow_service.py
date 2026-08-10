import unittest
from unittest.mock import patch

import workflow_service


class WorkflowValidationTests(unittest.TestCase):
    def test_clean_required_and_limit(self):
        with self.assertRaisesRegex(ValueError, "required"):
            workflow_service._clean("  ", "title", required=True)
        with self.assertRaisesRegex(ValueError, "characters"):
            workflow_service._clean("abcd", "title", maximum=3)

    def test_invalid_stage_is_rejected_before_database_call(self):
        with patch.object(workflow_service, "_write_returning") as write:
            with self.assertRaisesRegex(ValueError, "stage must be"):
                workflow_service.update_application_stage("user", "app", "waiting")
            write.assert_not_called()

    def test_user_email_validation(self):
        with self.assertRaisesRegex(ValueError, "valid email"):
            workflow_service.get_or_create_user("not-an-email")


if __name__ == "__main__":
    unittest.main()
