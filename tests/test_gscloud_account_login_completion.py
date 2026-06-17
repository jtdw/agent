from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.commercial.login_jobs import gscloud_login_jobs_dir
from core.commercial.service import CommercialService
from services.data_sources.gscloud_accounts import GSCloudAccountService


class GSCloudAccountLoginCompletionTests(unittest.TestCase):
    def test_complete_login_accepts_valid_cookie_before_worker_finishes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            commercial = CommercialService(Path(tmp))
            user = commercial.create_user("user@example.com", plan="basic", user_id="u_login")
            service = GSCloudAccountService(commercial)
            state_path = service.state_path(user["user_id"])
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "cookies": [
                            {
                                "name": "SESSION",
                                "value": "ok",
                                "domain": ".gscloud.cn",
                                "path": "/",
                                "expires": -1,
                            }
                        ],
                        "origins": [],
                    }
                ),
                encoding="utf-8",
            )
            login_id = "login_test"
            status_path = gscloud_login_jobs_dir(commercial.workdir) / f"{login_id}.json"
            status_path.write_text(
                json.dumps(
                    {
                        "login_job_id": login_id,
                        "subject_type": "customer",
                        "subject_id": user["user_id"],
                        "state": "BROWSER_OPEN",
                        "state_path": str(state_path),
                    }
                ),
                encoding="utf-8",
            )

            result = service.complete_login(user["user_id"], login_id)

            self.assertTrue(result["logged_in"])
            self.assertFalse(result["pending"])
            self.assertEqual(result["login_state"], "COMPLETED")
            updated_job = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertTrue(updated_job["close_requested"])
            self.assertEqual(updated_job["close_reason"], "login_completed")


if __name__ == "__main__":
    unittest.main()
