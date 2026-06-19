from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import Settings
from core.llm_task_planner import build_llm_task_plan
from core.presentation_result import build_presentation_bundle, format_presentation_reply
from core.service import GISWorkspaceService


class ResponseLanguageTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_chinese_prompt_unavailable_planner_returns_chinese_clarification(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "unavailable", "plan": {}}):
                result = service.ask("下载成都市30m的DEM数据")

        self.assertEqual(result["mode"], "clarification")
        self.assertIn("无法", result["reply"])
        self.assertIn("规划", result["reply"])
        self.assertNotIn("LLM planner", result["reply"])
        self.assertNotIn("Please", result["reply"])

    def test_english_prompt_unavailable_planner_returns_english_clarification(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "unavailable", "plan": {}}):
                result = service.ask("Download a 30m DEM for Chengdu.")

        self.assertEqual(result["mode"], "clarification")
        self.assertIn("planner", result["reply"].lower())
        self.assertNotIn("无法", result["reply"])

    def test_chinese_prompt_replaces_english_llm_clarification(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch(
                "core.service.build_llm_task_plan",
                return_value={
                    "status": "ready",
                    "plan": {
                        "task_type": "data_download",
                        "should_ask_clarification": True,
                        "clarification_question": "Please confirm the specific area boundary for Chengdu and verify that 30m resolution is available.",
                        "workflow_plan": [],
                        "tool_plan": [],
                        "validated_tool_args": {},
                        "response_language": "zh-CN",
                    },
                },
            ):
                result = service.ask("下载成都市30m的DEM数据")

        self.assertEqual(result["mode"], "clarification")
        self.assertNotIn("Please confirm", result["reply"])
        self.assertIn("请", result["reply"])

    def test_chinese_low_confidence_llm_plan_uses_chinese_question(self) -> None:
        with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client") as client_factory:
            client = mock.Mock()
            client.invoke.return_value = {
                "primary_goal": "download_dem",
                "intent": "data_download",
                "operation": "download",
                "input_assets": [],
                "asset_roles": {},
                "requested_downloads": [],
                "study_area": "成都",
                "time_range": {},
                "spatial_resolution": "30m",
                "candidate_tools": [],
                "selected_tools": [],
                "workflow_steps": [],
                "expected_outputs": [],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.2,
                "source_attribution": {},
                "explicit_history_references": [],
            }
            client_factory.return_value = client

            result = build_llm_task_plan("下载成都市30m的DEM数据", {"candidate_tool_cards": []})

        self.assertEqual(result["status"], "low_confidence")
        question = result["plan"]["clarification_question"]
        self.assertIn("请", question)
        self.assertNotIn("Please", question)

    def test_presentation_bundle_formats_chinese_status_text(self) -> None:
        bundle = build_presentation_bundle(
            task_goal="下载成都市30m的DEM数据",
            task_plan_summary={"primary_goal": "下载DEM", "response_language": "zh-CN"},
            coordinator_status="awaiting_confirmation",
            normalized_results=[
                {
                    "status": "awaiting_confirmation",
                    "step_id": "download",
                    "tool_name": "download_gscloud_dem",
                    "outputs": {},
                    "artifacts": [],
                    "map_layers": [],
                    "tables": [],
                    "images": [],
                    "warnings": [],
                    "errors": [],
                    "next_actions": ["请确认下载区域边界和30米分辨率。"],
                    "input_asset_ids": [],
                }
            ],
        )

        presentation = bundle["presentation_result"]
        reply = format_presentation_reply(presentation)
        self.assertEqual(presentation["response_language"], "zh-CN")
        self.assertIn("等待确认", presentation["concise_summary"])
        self.assertIn("需要确认", reply)
        self.assertNotIn("awaiting user confirmation", reply)
        self.assertNotIn("Next actions", reply)


if __name__ == "__main__":
    unittest.main()
