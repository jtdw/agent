from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.tool_contracts import download_job_to_tool_result


class DownloadJobToolResultBridgeTests(unittest.TestCase):
    def test_running_download_job_maps_to_running_tool_result(self) -> None:
        result = download_job_to_tool_result({"job_id": "job_1", "status": "queued", "resource_type": "dem"})

        self.assertEqual(result["status"], "running")
        self.assertFalse(result["success"])
        self.assertEqual(result["tool_name"], "download_job")
        self.assertEqual(result["outputs"]["job_id"], "job_1")

    def test_waiting_login_maps_to_awaiting_confirmation(self) -> None:
        result = download_job_to_tool_result(
            {"job_id": "job_2", "status": "waiting_login", "stage": "needs_gscloud_login_state"},
            scene_job={"scene_job_id": "scene_1", "state": "SCANNING", "message": "running"},
        )

        self.assertEqual(result["status"], "awaiting_confirmation")
        self.assertEqual(result["error_code"], "LOGIN_REQUIRED")
        self.assertEqual(result["diagnostics"]["scene_job"]["scene_job_id"], "scene_1")
        self.assertNotIn("log_path", str(result))

    def test_waiting_manual_maps_to_blocked(self) -> None:
        result = download_job_to_tool_result({"job_id": "job_3", "status": "waiting_manual", "error_message": "manual adapter required"})

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["error_code"], "DOWNLOAD_BLOCKED")
        self.assertIn("manual", result["user_message"])

    def test_completed_job_includes_only_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            existing = Path(tmp) / "result.zip"
            existing.write_text("zip", encoding="utf-8")
            missing = Path(tmp) / "missing.tif"

            result = download_job_to_tool_result(
                {
                    "job_id": "job_4",
                    "status": "completed",
                    "zip_path": str(existing),
                    "output_path": str(missing),
                    "resource_type": "dem",
                    "source_key": "gscloud",
                }
            )

            self.assertEqual(result["status"], "succeeded")
            self.assertTrue(result["success"])
            self.assertEqual(len(result["artifacts"]), 1)
            self.assertEqual(result["artifacts"][0]["path"], str(existing))

    def test_failed_job_uses_stable_error_and_safe_diagnostics(self) -> None:
        result = download_job_to_tool_result(
            {
                "job_id": "job_5",
                "status": "failed",
                "error_message": r"Traceback at E:\\secret\\workspace\\users\\u1\\storage_state.json",
                "failure_diagnostic": {"code": "login_required", "title": "Login state required", "user_message": "cookie expired"},
            },
            tile_job={"tile_job_id": "tile_1", "state": "FAILED", "log_path": r"E:\\secret\\tile.log", "error": "raw stack"},
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "LOGIN_REQUIRED")
        self.assertIn("expired", result["user_message"])
        self.assertNotIn("cookie", result["user_message"].lower())
        self.assertNotIn("storage_state", str(result))
        self.assertNotIn("tile.log", str(result))


if __name__ == "__main__":
    unittest.main()
