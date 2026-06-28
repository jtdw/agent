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

    def test_coordinator_payload_includes_planned_tool_card_when_context_cards_miss_it(self) -> None:
        service = self.make_service()
        service.manager.put_table("points", __import__("pandas").DataFrame({"x": [1], "y": [2]}))
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
        captured_payloads: list[dict] = []
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
                    "reason": "done",
                    "user_question": "",
                    "confidence": 0.9,
                },
            ]
        )

        def coordinator_client(payload):
            captured_payloads.append(payload)
            return json.dumps(next(decisions))

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": []},
            "describe points",
            coordinator_client=coordinator_client,
        )

        self.assertEqual(result["status"], "succeeded")
        tool_names = {
            str(card.get("tool_name") or card.get("name") or "")
            for card in captured_payloads[0]["tool_cards"]
        }
        self.assertIn("describe_dataset", tool_names)

    def test_continue_without_remaining_step_after_success_is_treated_as_stop_success(self) -> None:
        service = self.make_service()
        service.manager.put_table("points", __import__("pandas").DataFrame({"x": [1], "y": [2]}))
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
                    "decision": "continue",
                    "next_step_id": "",
                    "selected_next_action": "summarize result",
                    "required_tool": "",
                    "required_inputs": {},
                    "reason": "dataset was described successfully",
                    "user_question": "",
                    "confidence": 0.9,
                },
            ]
        )

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": []},
            "describe points",
            coordinator_client=lambda payload: json.dumps(next(decisions)),
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["executed_tools"], ["describe_dataset"])
        self.assertEqual(result["final_decision"]["decision"], "stop_success")

    def test_continue_with_step_id_and_blank_required_tool_uses_planned_step_tool(self) -> None:
        service = self.make_service()
        service.manager.put_table("points", __import__("pandas").DataFrame({"x": [1], "y": [2]}))
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
                    "selected_next_action": "describe the uploaded dataset",
                    "required_tool": "",
                    "required_inputs": {"dataset_name": "points"},
                    "reason": "the selected step has all required arguments",
                    "user_question": "",
                    "confidence": 0.9,
                },
                {
                    "decision": "stop_success",
                    "next_step_id": "",
                    "selected_next_action": "",
                    "required_tool": "",
                    "required_inputs": {},
                    "reason": "done",
                    "user_question": "",
                    "confidence": 0.9,
                },
            ]
        )

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": []},
            "describe points",
            coordinator_client=lambda payload: json.dumps(next(decisions)),
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["executed_tools"], ["describe_dataset"])
        self.assertEqual(result["final_decision"]["decision"], "stop_success")

    def test_continue_with_blank_step_id_uses_single_remaining_matching_tool(self) -> None:
        service = self.make_service()
        service.manager.put_table("points", __import__("pandas").DataFrame({"x": [1], "y": [2]}))
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
                    "next_step_id": "",
                    "selected_next_action": "describe the uploaded dataset",
                    "required_tool": "describe_dataset",
                    "required_inputs": {"dataset_name": "points"},
                    "reason": "the selected tool matches the only remaining planned step",
                    "user_question": "",
                    "confidence": 0.9,
                },
                {
                    "decision": "stop_success",
                    "next_step_id": "",
                    "selected_next_action": "",
                    "required_tool": "",
                    "required_inputs": {},
                    "reason": "done",
                    "user_question": "",
                    "confidence": 0.9,
                },
            ]
        )

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": []},
            "describe points",
            coordinator_client=lambda payload: json.dumps(next(decisions)),
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["executed_tools"], ["describe_dataset"])
        self.assertEqual(result["execution_trace"]["results"][0]["step_id"], "describe")

    def test_tool_plan_without_step_ids_uses_execution_step_names_for_references(self) -> None:
        service = self.make_service()
        service.manager.put_table(
            "stations.csv",
            __import__("pandas").DataFrame(
                {
                    "lon": [104.1, 104.2],
                    "lat": [30.1, 30.2],
                    "pop_density": [120, 150],
                }
            ),
        )
        plan = {
            "selected_tools": ["table_to_points", "plot_dataset"],
            "candidate_tools": ["table_to_points", "plot_dataset"],
            "requested_downloads": [],
            "execution_steps": ["make_points", "generate_map"],
            "workflow_plan": [],
            "tool_plan": [
                {
                    "tool_name": "table_to_points",
                    "args": {
                        "dataset_name": "stations.csv",
                        "x_col": "lon",
                        "y_col": "lat",
                        "crs": "EPSG:4326",
                        "output_name": "stations_csv_points",
                    },
                },
                {
                    "tool_name": "plot_dataset",
                    "args": {
                        "dataset_name": "$steps.make_points.outputs.result_dataset",
                        "column": "pop_density",
                        "title": "Population Density",
                        "output_name": "stations_csv_points_map.png",
                    },
                },
            ],
            "validated_tool_args": {},
        }
        decisions = iter(
            [
                {
                    "decision": "continue",
                    "next_step_id": "make_points",
                    "selected_next_action": "convert table to points",
                    "required_tool": "table_to_points",
                    "required_inputs": {"dataset_name": "stations.csv"},
                    "reason": "make points",
                    "user_question": "",
                    "confidence": 0.9,
                },
                {
                    "decision": "continue",
                    "next_step_id": "generate_map",
                    "selected_next_action": "map generated points",
                    "required_tool": "plot_dataset",
                    "required_inputs": {"dataset_name": "$steps.make_points.outputs.result_dataset"},
                    "reason": "plot points",
                    "user_question": "",
                    "confidence": 0.9,
                },
                {
                    "decision": "stop_success",
                    "next_step_id": "",
                    "selected_next_action": "",
                    "required_tool": "",
                    "required_inputs": {},
                    "reason": "done",
                    "user_question": "",
                    "confidence": 0.9,
                },
            ]
        )

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": []},
            "plot population density map from the station table",
            coordinator_client=lambda payload: json.dumps(next(decisions)),
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["executed_tools"], ["table_to_points", "plot_dataset"])
        self.assertEqual([item["step_id"] for item in result["execution_trace"]["results"]], ["make_points", "generate_map"])

    def test_unavailable_coordinator_after_all_steps_succeed_is_treated_as_stop_success(self) -> None:
        service = self.make_service()
        service.manager.put_table("points", __import__("pandas").DataFrame({"x": [1], "y": [2]}))
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
                    "selected_next_action": "describe the uploaded dataset",
                    "required_tool": "describe_dataset",
                    "required_inputs": {"dataset_name": "points"},
                    "reason": "run planned describe step",
                    "user_question": "",
                    "confidence": 0.9,
                },
                {
                    "answer": "The dataset has been described successfully.",
                },
            ]
        )

        result = run_coordinated_execution(
            service.manager,
            plan,
            {"candidate_tool_cards": []},
            "describe points",
            coordinator_client=lambda payload: json.dumps(next(decisions)),
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["executed_tools"], ["describe_dataset"])
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
