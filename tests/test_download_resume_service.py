from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.commercial.service import CommercialService
from services.downloads.resume import DownloadResumeService


class DownloadResumeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.commercial = CommercialService(Path(self.tmp.name))
        self.commercial.register_user("user@example.com", "password1", user_id="u_1")
        self.accounts = MagicMock()
        self.start_download = MagicMock(return_value={"auto_supported": True, "auto_started": True, "reason": "started"})
        self.service = DownloadResumeService(self.commercial, self.accounts, self.start_download)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_region_returns_clarification_without_starting_worker(self) -> None:
        job = self.commercial.submit_job(user_id="u_1", source_key="gscloud", resource_type="dem")
        self.commercial._update_job(job["job_id"], status="waiting_parameters")

        result = self.service.resume("u_1", job["job_id"])

        self.assertEqual(result["reason"], "clarification_required")
        self.assertNotIn("job", result)
        self.assertEqual(result["management_view"]["task_id"], job["job_id"])
        self.assertEqual(result["action_required"]["missing_parameters"], ["region"])
        self.start_download.assert_not_called()

    def test_missing_login_returns_structured_login_action(self) -> None:
        job = self.commercial.submit_job(user_id="u_1", source_key="gscloud", resource_type="dem", region="成都")
        self.commercial._update_job(job["job_id"], status="waiting_login")
        self.accounts.status.return_value = {"logged_in": False}

        result = self.service.resume("u_1", job["job_id"])

        self.assertEqual(result["reason"], "login_required")
        self.assertNotIn("job", result)
        self.assertEqual(result["management_view"]["task_id"], job["job_id"])
        self.assertEqual(result["action_required"]["job_id"], job["job_id"])
        self.start_download.assert_not_called()

    def test_ready_job_starts_existing_job(self) -> None:
        job = self.commercial.submit_job(user_id="u_1", source_key="gscloud", resource_type="dem", region="成都")
        self.commercial._update_job(job["job_id"], status="waiting_login")
        self.accounts.status.return_value = {"logged_in": True}

        result = self.service.resume("u_1", job["job_id"])

        self.assertTrue(result["auto_started"])
        self.assertNotIn("job", result)
        self.assertEqual(result["management_view"]["task_id"], job["job_id"])
        self.start_download.assert_called_once()
        self.assertEqual(self.start_download.call_args.args[0]["job_id"], job["job_id"])

    def test_platform_job_resume_does_not_require_customer_login(self) -> None:
        self.commercial.grant_plan("u_1", plan="pro")
        self.commercial.add_platform_account("gscloud", label="pool", daily_limit=10, monthly_limit=10)
        job = self.commercial.submit_job(
            user_id="u_1",
            source_key="gscloud",
            resource_type="dem",
            region="Chengdu",
            account_mode="platform",
        )
        self.commercial._update_job(job["job_id"], status="waiting_login")
        self.accounts.status.return_value = {"logged_in": False}

        result = self.service.resume("u_1", job["job_id"])

        self.assertTrue(result["auto_started"])
        self.accounts.status.assert_not_called()
        self.start_download.assert_called_once()
        self.assertEqual(self.start_download.call_args.args[0]["job_id"], job["job_id"])


if __name__ == "__main__":
    unittest.main()
