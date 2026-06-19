from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from core.config import Settings
from core.llm_planner_observability import summarize_shadow_plan, summarize_shadow_planner_messages
from core.service import GISWorkspaceService
from core.workspace_db import WorkspaceDatabase


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "summarize_llm_planner_shadow.py"


class LLMPlannerObservabilityTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_summarize_shadow_plan_extracts_status_errors_tools_and_confirmation(self) -> None:
        summary = summarize_shadow_plan(
            {
                "status": "invalid_plan",
                "mode": "shadow",
                "planner_source": "real_llm",
                "executes_tools": False,
                "errors": [{"code": "FIELD_NOT_IN_CONTEXT"}, {"code": "TOOL_CARD_NOT_READ"}],
                "fallback_plan": {"should_ask_clarification": True},
            }
        )

        self.assertEqual(summary["llm_planner_status"], "invalid_plan")
        self.assertEqual(summary["llm_planner_source"], "real_llm")
        self.assertEqual(summary["llm_planner_error_codes"], ["FIELD_NOT_IN_CONTEXT", "TOOL_CARD_NOT_READ"])
        self.assertFalse(summary["llm_planner_executes_tools"])
        self.assertTrue(summary["llm_planner_should_ask_clarification"])

    def test_service_meta_includes_flat_shadow_observability_fields(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"lon": [1.0], "lat": [2.0], "soil_moisture": [0.1]}))
            service.current_session_id = service.create_new_session()
            shadow = {
                "status": "ready",
                "mode": "shadow",
                "planner_source": "test_client",
                "executes_tools": False,
                "plan": {
                    "task_type": "map_generation",
                    "requires_confirmation": False,
                    "should_ask_clarification": False,
                    "tool_plan": [{"tool_name": "plot_dataset", "args": {"dataset_name": "stations"}}],
                    "validated_tool_args": {"plot_dataset": {"dataset_name": "stations"}},
                },
            }

            with mock.patch.dict("os.environ", {"GIS_AGENT_ENABLE_LLM_PLANNER_SHADOW": "1"}, clear=False):
                with mock.patch("core.service.build_shadow_llm_task_plan", return_value=shadow):
                    service.ask("画一张地图")

            assistant_messages = [item for item in service.manager.database.list_messages(service.current_session_id) if item["role"] == "assistant"]
            meta = assistant_messages[-1]["meta"]
            self.assertEqual(meta["llm_shadow_plan"], shadow)
            self.assertEqual(meta["llm_planner_status"], "ready")
            self.assertEqual(meta["llm_planner_source"], "test_client")
            self.assertEqual(meta["llm_planner_tool_names"], ["plot_dataset"])

    def test_summarize_shadow_planner_messages_counts_statuses_and_error_codes(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = WorkspaceDatabase(Path(tmp) / "workspace.db")
            db.create_conversation("session_1", "Eval")
            db.add_message("session_1", "assistant", "ok", meta={"llm_planner_status": "ready", "llm_planner_error_codes": []})
            db.add_message(
                "session_1",
                "assistant",
                "bad",
                meta={"llm_planner_status": "invalid_plan", "llm_planner_error_codes": ["FIELD_NOT_IN_CONTEXT"]},
            )
            db.add_message("session_1", "user", "ignore", meta={"llm_planner_status": "ready"})

            result = summarize_shadow_planner_messages(db.db_path)

        self.assertEqual(result["assistant_shadow_message_count"], 2)
        self.assertEqual(result["status_counts"], {"invalid_plan": 1, "ready": 1})
        self.assertEqual(result["error_code_counts"], {"FIELD_NOT_IN_CONTEXT": 1})

    def test_summary_script_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp) / "workspace"
            db = WorkspaceDatabase(workdir / "workspace.db")
            db.create_conversation("session_1", "Eval")
            db.add_message("session_1", "assistant", "ok", meta={"llm_planner_status": "ready", "llm_planner_error_codes": []})

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--workdir", str(workdir), "--format", "json"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["assistant_shadow_message_count"], 1)
        self.assertEqual(payload["status_counts"], {"ready": 1})


if __name__ == "__main__":
    unittest.main()
