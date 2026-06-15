from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from core.commercial.service import CommercialService


class DownloadStatusMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp.name)
        self.service = CommercialService(self.workdir)
        self.service.register_user("user@example.com", "password1", user_id="u_test")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_failed_job_includes_failure_diagnostic(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="sentinel2_msi")

        failed = self.service.fail_job(job["job_id"], "download timeout")

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["state"], "failed")
        self.assertIn("message", failed)
        self.assertEqual(set(failed["failure_diagnostic"]).issuperset({"code", "title", "user_message", "next_action"}), True)

    def test_completed_job_records_artifact_quality(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="sentinel2_msi")
        result_path = self.workdir / "downloads" / "scene.zip"
        result_path.parent.mkdir()
        with zipfile.ZipFile(result_path, "w") as archive:
            archive.writestr("scene.txt", "ok")

        done = self.service.run_job_with_result(job["job_id"], {"zip_path": str(result_path)})

        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["state"], "success")
        self.assertEqual(done["artifact_quality"][0]["ok"], True)

    def test_invalid_download_result_fails_instead_of_completing(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="sentinel2_msi")
        empty = self.workdir / "downloads" / "empty.zip"
        empty.parent.mkdir()
        empty.write_bytes(b"")

        failed = self.service.run_job_with_result(job["job_id"], {"zip_path": str(empty)})

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["artifact_quality"][0]["ok"], False)
        self.assertIn("failure_diagnostic", failed)

    def test_waiting_parameters_is_preserved_and_not_running(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="dem")
        self.service._update_job(job["job_id"], status="waiting_parameters", stage="needs_region")

        waiting = self.service.get_job(job["job_id"])

        self.assertEqual(waiting["status"], "waiting_parameters")
        self.assertEqual(waiting["state"], "waiting_parameters")
        self.assertNotEqual(waiting["state"], "running")


if __name__ == "__main__":
    unittest.main()
