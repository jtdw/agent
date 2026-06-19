from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from core.config import Settings
from core.service import GISWorkspaceService


class BuiltinWorkspacePromptTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def seed_table(self, service: GISWorkspaceService) -> None:
        service.manager.put_table(
            "soil_station",
            pd.DataFrame(
                {
                    "station_id": ["S1", "S2", "S3"],
                    "longitude": [115.1, 115.2, 115.3],
                    "latitude": [41.1, 41.2, 41.3],
                    "time": ["2024-01-01", "2024-01-02", "2024-01-03"],
                    "soil_moisture": [0.12, None, 0.18],
                }
            ),
        )

    def ask_with_unavailable_planner(self, service: GISWorkspaceService, prompt: str) -> dict:
        with mock.patch("core.service.execute_workflow_plan") as workflow_mock:
            with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                with mock.patch(
                    "core.service.build_llm_task_plan",
                    return_value={
                        "status": "unavailable",
                        "plan": {"clarification_question": "需要 LLM Planner 生成计划。"},
                    },
                ):
                    result = service.ask(prompt)
        workflow_mock.assert_not_called()
        tool_mock.assert_not_called()
        return result

    def assert_zero_tool_clarification(self, result: dict) -> None:
        self.assertEqual(result["model"], "conversation-coordinator")
        self.assertEqual(result["mode"], "clarification")
        self.assertEqual(result["reason"], "unavailable")
        self.assertIn("LLM Planner", result["reply"])

    def test_workspace_summary_prompt_does_not_fallback_without_llm_plan(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)

            result = self.ask_with_unavailable_planner(
                service,
                "概括当前工作区数据，并判断哪些数据可直接用于制图、建模或结果分析。",
            )

            self.assert_zero_tool_clarification(result)

    def test_field_check_prompt_does_not_execute_tool_without_llm_plan(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)

            result = self.ask_with_unavailable_planner(
                service,
                "检查当前上传数据的字段、坐标、时间和缺失值，给出下一步处理计划。",
            )

            self.assert_zero_tool_clarification(result)

    def test_download_readiness_prompt_does_not_trigger_keyword_download_without_llm_plan(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)

            result = self.ask_with_unavailable_planner(
                service,
                "根据当前工作区数据，检查是否可以下载 DEM、Sentinel-2 或土壤水分相关数据。",
            )

            self.assert_zero_tool_clarification(result)

    def test_capability_prompt_does_not_bypass_planner(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            result = self.ask_with_unavailable_planner(service, "你能做什么？")

            self.assert_zero_tool_clarification(result)


if __name__ == "__main__":
    unittest.main()
