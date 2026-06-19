from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.llm_planner_eval import evaluate_llm_planner_cases, load_llm_planner_cases


class LLMPlannerEvalTests(unittest.TestCase):
    def test_loads_jsonl_cases_with_required_fields(self) -> None:
        cases = load_llm_planner_cases(Path("tests/fixtures/llm_planner_cases.jsonl"))

        self.assertGreaterEqual(len(cases), 5)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertIn("user_prompt", case)
                self.assertIn("context", case)
                self.assertIn("deterministic_plan", case)
                self.assertIn("model_output", case)
                self.assertIn("expected", case)

    def test_evaluates_fixture_cases_and_reports_accuracy(self) -> None:
        result = evaluate_llm_planner_cases(Path("tests/fixtures/llm_planner_cases.jsonl"))

        self.assertEqual(result["case_count"], 6)
        self.assertEqual(result["passed"], 6)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["failures"], [])

    def test_reports_expected_failures_for_forbidden_tool_use(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            fixture = Path(tmp) / "cases.jsonl"
            fixture.write_text(
                '{"id":"bad_download","user_prompt":"解释当前表格","context":{"active_dataset":{"name":"stations","type":"table"},"available_fields":["value"],"candidate_tool_cards":[{"tool_name":"download_backend_status"}]},"deterministic_plan":{"task_type":"result_analysis"},"model_output":{"task_type":"data_download","goal":"download","selected_assets":[],"tools_read":["download_backend_status"],"planned_steps":[{"step_id":"download","tool_name":"download_backend_status","args":{}}],"requires_confirmation":false,"clarification_question":"","assumptions":[],"expected_outputs":[],"forbidden_tools":[],"explanation":""},"expected":{"status":"ready","forbidden_tools_not_used":["download_backend_status"]}}\n',
                encoding="utf-8",
            )

            result = evaluate_llm_planner_cases(fixture)

            self.assertEqual(result["case_count"], 1)
            self.assertEqual(result["passed"], 0)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["failures"][0]["case_id"], "bad_download")
            self.assertIn("FORBIDDEN_TOOL_USED", {item["code"] for item in result["failures"][0]["errors"]})


if __name__ == "__main__":
    unittest.main()
