from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.commercial.service import CommercialService
from services.data_sources.gscloud_accounts import GSCloudAccountService


class GSCloudAccountServiceTests(unittest.TestCase):
    def test_active_login_session_does_not_trust_prelogin_cookie_file(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            workdir = Path(temp_dir)
            commercial = CommercialService(workdir)
            commercial.register_user("user@example.com", "password1", user_id="u_1")
            service = GSCloudAccountService(commercial)
            state_path = service.state_path("u_1")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"cookies": [{"name": "prelogin", "value": "secret", "domain": ".gscloud.cn", "expires": 4102444800}]}),
                encoding="utf-8",
            )

            with patch(
                "services.data_sources.gscloud_accounts.read_gscloud_login_job",
                return_value={"subject_type": "customer", "subject_id": "u_1", "state": "BROWSER_OPEN"},
            ):
                result = service.complete_login("u_1", "login_1")

        self.assertTrue(result["pending"])
        self.assertFalse(result["logged_in"])
        self.assertNotIn("storage_state_path", result)
        self.assertNotIn("secret", json.dumps(result))

    def test_completed_login_registers_state_and_returns_waiting_jobs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            workdir = Path(temp_dir)
            commercial = CommercialService(workdir)
            commercial.register_user("user@example.com", "password1", user_id="u_1")
            job = commercial.submit_job(user_id="u_1", source_key="gscloud", resource_type="dem", region="成都")
            commercial._update_job(job["job_id"], status="waiting_login")
            service = GSCloudAccountService(commercial)
            state_path = service.state_path("u_1")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"cookies": [{"name": "session", "value": "secret", "domain": ".gscloud.cn", "expires": 4102444800}]}),
                encoding="utf-8",
            )

            with patch(
                "services.data_sources.gscloud_accounts.read_gscloud_login_job",
                return_value={"subject_type": "customer", "subject_id": "u_1", "state": "COMPLETED"},
            ):
                result = service.complete_login("u_1", "login_1")

            registered_path = commercial.get_user_storage_state_path("u_1", "gscloud")

            self.assertTrue(result["logged_in"])
            self.assertEqual(result["waiting_jobs"][0]["job_id"], job["job_id"])
            self.assertEqual(registered_path, str(state_path))


if __name__ == "__main__":
    unittest.main()
