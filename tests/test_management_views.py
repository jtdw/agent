from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from pydantic import ValidationError

import api_server
from core.commercial.service import CommercialService
from core.management_views import DownloadManagementView, download_job_to_management_view
from core.task_outcome_advisor import build_task_outcome
from core.tool_contracts import download_job_to_tool_result


class ManagementViewTests(unittest.TestCase):
    def test_download_management_view_schema_rejects_raw_sensitive_fields(self) -> None:
        with self.assertRaises(ValidationError):
            DownloadManagementView.model_validate(
                {
                    "task_id": "job_1",
                    "status": "running",
                    "progress": 10,
                    "display_title": "DEM",
                    "source_name": "gscloud",
                    "artifact_refs": [],
                    "map_layer_refs": [],
                    "warnings": [],
                    "error_code": "",
                    "error_title": "",
                    "user_message": "",
                    "available_actions": ["cancel"],
                    "action_state": {},
                    "updated_at": "",
                    "user_id": "u_1",
                }
            )

    def test_download_job_bridge_outputs_safe_management_view(self) -> None:
        job = {
            "job_id": "job_1",
            "user_id": "u_1",
            "session_id": "s_1",
            "source_key": "gscloud",
            "resource_type": "dem",
            "region": "chengdu",
            "output_name": "chengdu_dem",
            "status": "waiting_login",
            "progress": 5,
            "stage": "needs_login",
            "storage_state_path": r"E:\\secret\\storage_state.json",
            "error_message": "Traceback: raw stack",
            "updated_at": "2026-06-21T10:00:00",
        }
        tool_result = download_job_to_tool_result(job)

        view = download_job_to_management_view(job, tool_result=tool_result)
        rendered = json.dumps(view, ensure_ascii=False)

        self.assertEqual(view["task_id"], "job_1")
        self.assertEqual(view["status"], "awaiting_confirmation")
        self.assertIn("login_required", view["available_actions"])
        self.assertIn("cancel", view["available_actions"])
        self.assertEqual(view["action_state"]["stage"], "needs_login")
        self.assertNotIn("user_id", rendered)
        self.assertNotIn("session_id", rendered)
        self.assertNotIn("storage_state", rendered)
        self.assertNotIn("Traceback", rendered)

    def test_completed_download_view_exposes_artifact_action_not_raw_path(self) -> None:
        job = {
            "job_id": "job_2",
            "source_key": "gscloud",
            "resource_type": "dem",
            "region": "chengdu",
            "output_name": "chengdu_dem",
            "status": "completed",
            "progress": 100,
            "download_url": "/api/downloads/artifact?job_id=job_2",
        }
        tool_result = {
            "status": "succeeded",
            "tool_name": "download_job",
            "artifacts": [{"artifact_id": "a_dem", "title": "dem.zip", "type": "archive"}],
            "map_layers": [{"layer_id": "layer_dem", "name": "DEM"}],
            "warnings": [],
            "errors": [],
            "next_actions": [],
        }

        view = download_job_to_management_view(job, tool_result=tool_result)

        self.assertEqual(view["status"], "succeeded")
        self.assertEqual(view["artifact_refs"][0]["artifact_id"], "a_dem")
        self.assertEqual(view["map_layer_refs"][0]["layer_id"], "layer_dem")
        self.assertIn("view_artifacts", view["available_actions"])
        self.assertIn("add_to_map", view["available_actions"])
        self.assertNotIn("download_url", json.dumps(view, ensure_ascii=False))

    def test_task_outcome_uses_management_view_without_raw_job(self) -> None:
        result = {
            "management_view": {
                "task_id": "job_3",
                "status": "failed",
                "progress": 20,
                "display_title": "DEM",
                "source_name": "gscloud",
                "artifact_refs": [],
                "map_layer_refs": [],
                "warnings": ["warning"],
                "error_code": "DOWNLOAD_FAILED",
                "error_title": "Download failed",
                "user_message": "Download failed safely.",
                "available_actions": ["retry"],
                "action_state": {},
                "updated_at": "",
            }
        }

        outcome = build_task_outcome("download", result)

        self.assertEqual(outcome["status"], "failed")
        self.assertTrue(outcome["has_results"])
        self.assertIn("job_3", outcome["summary"])
        self.assertEqual(outcome["result_paths"], [])

    def test_task_outcome_prefers_presentation_result_over_legacy_user_facing(self) -> None:
        outcome = build_task_outcome(
            "workflow",
            {
                "presentation_result": {
                    "status": "succeeded",
                    "concise_summary": "Canonical summary.",
                    "artifact_refs": [{"artifact_id": "a_1", "title": "canonical.tif"}],
                    "map_layer_refs": [],
                    "table_refs": [],
                    "image_refs": [],
                    "next_action_suggestions": ["Review canonical output."],
                },
                "user_facing_result": {
                    "summary": "Legacy summary.",
                    "primary_artifacts": [{"path": r"E:\\internal\\legacy.tif"}],
                },
            },
        )

        self.assertEqual(outcome["summary"], "Canonical summary.")
        self.assertEqual(outcome["result_paths"], ["canonical.tif"])
        self.assertEqual(outcome["recommendations"], ["Review canonical output."])

    def test_download_jobs_api_defaults_to_management_views_without_raw_jobs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = CommercialService(Path(tmp))
            with mock.patch.object(api_server, "commercial_service", service):
                client = TestClient(api_server.app)
                user = client.post(
                    "/api/auth/register",
                    json={"email": "raw-default@example.com", "password": "password1"},
                ).json()["user"]
                service.submit_job(
                    user_id=user["user_id"],
                    source_key="gscloud",
                    resource_type="dem",
                    region="chengdu",
                    account_mode="own",
                )
                response = client.get("/api/downloads/jobs", params={"user_id": user["user_id"]})
                payload = response.json()

                self.assertEqual(response.status_code, 200)
                self.assertIn("management_views", payload)
                self.assertNotIn("jobs", payload)
                self.assertFalse(payload.get("deprecated_raw_job_api"))

                raw_response = client.get(
                    "/api/downloads/jobs",
                    params={"user_id": user["user_id"], "include_raw": "true"},
                )
                raw_payload = raw_response.json()
                self.assertEqual(raw_response.status_code, 200)
                self.assertIn("jobs", raw_payload)
                self.assertTrue(raw_payload.get("deprecated_raw_job_api"))

    def test_download_job_log_api_defaults_to_diagnostic_views_without_raw_logs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = CommercialService(Path(tmp))
            with mock.patch.object(api_server, "commercial_service", service):
                client = TestClient(api_server.app)
                user = client.post(
                    "/api/auth/register",
                    json={"email": "raw-log@example.com", "password": "password1"},
                ).json()["user"]
                job = service.submit_job(
                    user_id=user["user_id"],
                    source_key="gscloud",
                    resource_type="dem",
                    region="chengdu",
                    account_mode="own",
                )
                service.write_audit_event(
                    user_id=user["user_id"],
                    action="submitted",
                    resource_type="download_job",
                    resource_id=job["job_id"],
                    detail={"path": r"E:\secret\raw.log"},
                )
                response = client.get(
                    "/api/downloads/jobs/log",
                    params={"user_id": user["user_id"], "job_id": job["job_id"]},
                )
                payload = response.json()

                self.assertEqual(response.status_code, 200)
                self.assertIn("management_view", payload)
                self.assertIn("diagnostic_event_views", payload)
                self.assertNotIn("job", payload)
                self.assertNotIn("scene_jobs", payload)
                self.assertNotIn("tile_jobs", payload)
                self.assertNotIn("audit_events", payload)
                self.assertFalse(payload.get("deprecated_raw_job_api"))
                self.assertNotIn("E:\\secret", json.dumps(payload, ensure_ascii=False))

                raw_response = client.get(
                    "/api/downloads/jobs/log",
                    params={"user_id": user["user_id"], "job_id": job["job_id"], "include_raw": "true"},
                )
                raw_payload = raw_response.json()
                self.assertEqual(raw_response.status_code, 200)
                self.assertIn("job", raw_payload)
                self.assertIn("audit_events", raw_payload)
                self.assertTrue(raw_payload.get("deprecated_raw_job_api"))


if __name__ == "__main__":
    unittest.main()
