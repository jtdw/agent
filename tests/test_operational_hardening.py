from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.commercial.service import CommercialService
from core.ops_config import validate_production_config


class OperationalHardeningTests(unittest.TestCase):
    def test_production_config_requires_strong_runtime_settings(self):
        with patch.dict(
            os.environ,
            {
                "GIS_AGENT_ENV": "production",
                "APP_SECRET_KEY": "",
                "GIS_AGENT_ADMIN_TOKEN": "",
                "GIS_AGENT_COOKIE_SECURE": "0",
            },
            clear=False,
        ):
            result = validate_production_config()

        self.assertFalse(result["ok"])
        self.assertIn("APP_SECRET_KEY", result["missing"])
        self.assertIn("GIS_AGENT_ADMIN_TOKEN", result["missing"])
        self.assertIn("GIS_AGENT_COOKIE_SECURE=1", result["missing"])

    def test_development_config_does_not_require_production_secrets(self):
        with patch.dict(os.environ, {"GIS_AGENT_ENV": "development"}, clear=False):
            result = validate_production_config()

        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])

    def test_audit_events_are_written_and_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = CommercialService(Path(tmp))
            event = service.write_audit_event(
                user_id="u_1",
                action="download.submit",
                status="ok",
                resource_type="download_job",
                resource_id="job_1",
                detail={"source": "gscloud"},
            )

            events = service.list_audit_events(user_id="u_1", limit=5)

        self.assertEqual(event["action"], "download.submit")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["detail"]["source"], "gscloud")

    def test_recover_stale_running_jobs_marks_them_waiting_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = CommercialService(Path(tmp))
            service.register_user("user@example.com", "password1", user_id="u_1")
            job = service.submit_job(user_id="u_1", source_key="gscloud", resource_type="dem", account_mode="own")
            service._update_job(job["job_id"], status="running", stage="auto_downloading")

            recovered = service.recover_interrupted_jobs()
            updated = service.get_job(job["job_id"])

        self.assertEqual(recovered["count"], 1)
        self.assertEqual(updated["status"], "waiting_manual")
        self.assertIn("service_restart", updated["stage"])


if __name__ == "__main__":
    unittest.main()
