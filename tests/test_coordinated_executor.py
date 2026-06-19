from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from core.coordinated_executor import run_coordinated_execution
from core.config import Settings
from core.service import GISWorkspaceService


class CoordinatedExecutorTests(unittest.TestCase):
    def make_service(self) -> GISWorkspaceService:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        settings = Settings(api_key="", workdir=Path(self.tmp.name) / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def tearDown(self) -> None:
        tmp = getattr(self, "tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_successful_multistep_plan_executes_only_planned_steps(self) -> None:
        service = self.make_service()
        service.manager.put_table("points", __import__("pandas").DataFrame({"x": [1, 2], "y": [3, 4]}))
        plan = {
            "selected_tools": ["describe_dataset"],
            "candidate_tools": ["describe_dataset"],
            "requested_downloads": [],
            "workflow_plan": [
                {"step_id": "describe", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "points"}},
            ],
            "tool_plan": [],
            "validated_tool_args": {},
        }
        decisions = iter(
            [
                {
                    "decision": "continue",
                    "next_step_id": "describe",
                    "selected_next_action": "",
                    "required_tool": "describe_dataset",
                    "required_inputs": {"dataset_name": "points"},
                    "reason": "run planned describe step",
                    "user_question": "",
                    "confidence": 0.9,
                },
                {
                    "decision": "stop_success",
                    "next_step_id": "",
                    "selected_next_action": "",
                    "required_tool": "",
                    "required_inputs": {},
                    "reason": "describe completed",
                    "user_question": "",
                    "confidence": 0.9,
                },
            ]
        )

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": [{"tool_name": "describe_dataset"}]},
            "describe points",
            coordinator_client=lambda payload: json.dumps(next(decisions)),
        )

        self.assertTrue(result["executed"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["executed_tools"], ["describe_dataset"])
        self.assertEqual(result["execution_trace"]["results"][0]["step_id"], "describe")
        self.assertEqual(result["final_decision"]["decision"], "stop_success")

    def test_download_step_is_blocked_when_requested_downloads_empty(self) -> None:
        service = self.make_service()
        plan = {
            "selected_tools": ["run_gscloud_dem_capture_job"],
            "candidate_tools": ["run_gscloud_dem_capture_job"],
            "requested_downloads": [],
            "workflow_plan": [
                {"step_id": "download", "tool_name": "run_gscloud_dem_capture_job", "validated_tool_args": {"job_id": "job_1"}},
            ],
            "tool_plan": [],
            "validated_tool_args": {},
        }

        with mock.patch("core.coordinated_executor.execute_single_workflow_step") as step_mock:
            result = run_coordinated_execution(
                service.manager,
                plan,
                {"candidate_tool_cards": [{"tool_name": "run_gscloud_dem_capture_job"}]},
                "run plan",
                coordinator_client=lambda payload: json.dumps(
                    {
                        "decision": "continue",
                        "next_step_id": "download",
                        "selected_next_action": "download",
                        "required_tool": "run_gscloud_dem_capture_job",
                        "required_inputs": {"job_id": "job_1"},
                        "reason": "try download",
                        "user_question": "",
                        "confidence": 0.9,
                    }
                ),
            )

        self.assertFalse(step_mock.called)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "DOWNLOAD_STEP_WITHOUT_REQUESTED_DOWNLOADS")
        self.assertEqual(result["executed_tools"], [])

    def test_loop_retry_limit_blocks_repeated_failed_step(self) -> None:
        service = self.make_service()
        plan = {
            "selected_tools": ["describe_dataset"],
            "candidate_tools": ["describe_dataset"],
            "requested_downloads": [],
            "workflow_plan": [
                {"step_id": "describe", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "missing"}},
            ],
            "tool_plan": [],
            "validated_tool_args": {},
        }

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": [{"tool_name": "describe_dataset"}]},
            "describe missing",
            coordinator_client=lambda payload: json.dumps(
                {
                    "decision": "continue",
                    "next_step_id": "describe",
                    "selected_next_action": "retry",
                    "required_tool": "describe_dataset",
                    "required_inputs": {"dataset_name": "missing"},
                    "reason": "retry",
                    "user_question": "",
                    "confidence": 0.9,
                }
            ),
            max_tool_retries=1,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["blocked_reason"], "STEP_RETRY_LIMIT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
