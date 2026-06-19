from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_llm_planner.py"
FIXTURE = ROOT / "tests" / "fixtures" / "llm_planner_cases.jsonl"


class LLMPlannerEvalScriptTests(unittest.TestCase):
    def test_script_outputs_json_summary(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--cases", str(FIXTURE), "--format", "json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["case_count"], 6)
        self.assertEqual(payload["passed"], 6)
        self.assertEqual(payload["accuracy"], 1.0)

    def test_script_outputs_markdown_report(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--cases", str(FIXTURE), "--format", "markdown"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("# LLM Planner Evaluation", completed.stdout)
        self.assertIn("| Case | Status | Result |", completed.stdout)
        self.assertIn("complete_xgboost_station_request", completed.stdout)

    def test_script_threshold_returns_nonzero_when_accuracy_is_too_low(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            fixture = Path(tmp) / "bad.jsonl"
            fixture.write_text(
                '{"id":"bad","user_prompt":"解释当前表格","context":{"active_dataset":{"name":"stations","type":"table"},"available_fields":["value"],"candidate_tool_cards":[{"tool_name":"download_backend_status"}]},"deterministic_plan":{"task_type":"result_analysis"},"model_output":{"task_type":"data_download","goal":"download","selected_assets":[],"tools_read":["download_backend_status"],"planned_steps":[{"step_id":"download","tool_name":"download_backend_status","args":{}}],"requires_confirmation":false,"clarification_question":"","assumptions":[],"expected_outputs":[],"forbidden_tools":[],"explanation":""},"expected":{"status":"ready","forbidden_tools_not_used":["download_backend_status"]}}\n',
                encoding="utf-8",
            )

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--cases", str(fixture), "--min-accuracy", "1.0"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["failed"], 1)

    def test_script_help_exposes_real_llm_shadow_option(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("--use-real-llm", completed.stdout)


if __name__ == "__main__":
    unittest.main()
