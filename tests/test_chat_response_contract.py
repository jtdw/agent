from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from unittest import mock

from core.chat_response import build_chat_response
from core.config import Settings
from core.service import GISWorkspaceService


class ChatResponseContractTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_build_chat_response_persists_exchange_and_returns_authoritative_state(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            response = build_chat_response(
                service,
                user_prompt="检查下载任务状态",
                result={"reply": "没有正在运行的下载任务。", "model": "direct-router", "reason": "download_status", "job": {"job_id": "job_1"}},
                meta_keys=("model", "reason", "job"),
            )

            self.assertEqual(response["reply"], "没有正在运行的下载任务。")
            self.assertEqual(response["model"], "direct-router")
            self.assertEqual(response["reason"], "download_status")
            self.assertEqual(response["current_session_id"], service.current_session_id)
            self.assertGreaterEqual(len(response["sessions"]), 1)
            self.assertEqual([item["role"] for item in response["messages"]], ["user", "assistant"])
            self.assertEqual(response["messages"][0]["content"], "检查下载任务状态")
            self.assertEqual(response["messages"][1]["content"], "没有正在运行的下载任务。")
            self.assertEqual(response["messages"][1]["meta"]["job"]["job_id"], "job_1")

    def test_build_chat_response_does_not_swallow_persistence_errors(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.database.add_message = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down"))  # type: ignore[method-assign]

            with self.assertRaises(RuntimeError):
                build_chat_response(
                    service,
                    user_prompt="检查下载任务状态",
                    result={"reply": "ok", "model": "direct-router"},
                    meta_keys=("model",),
                )

    def test_download_requires_login_reply_is_regular_chat_result(self) -> None:
        from core.api_helpers import _download_requires_login_result

        result = _download_requires_login_result("下载成都市 DEM")

        self.assertEqual(result["model"], "direct-router")
        self.assertEqual(result["reason"], "download_requires_login")
        self.assertIn("登录", result["reply"])
        self.assertIn("DEM", result["reply"])

    def test_clarification_reply_does_not_append_stale_dashboard_analysis(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.dashboard = lambda: {  # type: ignore[method-assign]
                "model_results": [{"model": "XGBoost", "metrics": {"R": 0.9999}}]
            }

            response = build_chat_response(
                service,
                user_prompt="帮我下载 DEM 数据",
                result={
                    "reply": "请确认下载区域或范围。",
                    "model": "direct-router",
                    "reason": "gscloud_intent_clarification",
                    "action_required": {
                        "type": "clarification_required",
                        "missing_parameters": ["region"],
                    },
                },
            )

            self.assertEqual(response["reply"], "请确认下载区域或范围。")
            self.assertNotIn("XGBoost", response["reply"])
            self.assertNotIn("任务结果分析", response["reply"])

    def test_tool_result_artifacts_are_persisted_on_assistant_message(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("table_result", pd.DataFrame({"a": [1, 2]}))
            artifact_path = service.manager.derived_dir / "table_result.csv"
            service.manager.register_artifact(
                artifact_id="artifact_table_result",
                path=str(artifact_path),
                type="csv",
                title="table_result.csv",
                meta={"tool_name": "export_dataset", "workflow_id": "workflow_chat"},
            )

            response = build_chat_response(
                service,
                user_prompt="导出表格",
                result={
                    "reply": "已导出表格。",
                    "model": "conversation-coordinator",
                    "reason": "validated_tool_args",
                    "artifacts": [{"artifact_id": "artifact_table_result", "path": str(artifact_path), "type": "csv", "title": "table_result.csv"}],
                    "tool_results": [{"tool_name": "export_dataset", "ok": True}],
                    "workflow_summary": {"workflow_id": "workflow_chat", "ok": True},
                },
            )

            assistant = response["messages"][-1]
            self.assertEqual(assistant["role"], "assistant")
            self.assertEqual(assistant["meta"]["message_format"], "markdown")
            self.assertEqual(assistant["meta"]["artifacts"][0]["artifact_id"], "artifact_table_result")
            self.assertEqual(assistant["meta"]["artifacts"][0]["filename"], "table_result.csv")
            self.assertIn("/api/artifacts/artifact_table_result/download", assistant["meta"]["artifacts"][0]["download_url"])
            self.assertEqual(assistant["meta"]["tool_results"][0]["tool_name"], "export_dataset")
            self.assertEqual(assistant["meta"]["workflow_summary"]["workflow_id"], "workflow_chat")

    def test_chat_response_deduplicates_repeated_result_sections(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            repeated = "\n".join(
                [
                    "已完成操作：XGBoost 土壤水分模型训练完成。",
                    "关键结果：R=0.99",
                    "输出文件：xgb.csv",
                    "下一步建议：检查特征重要性。",
                    "已完成操作：XGBoost 土壤水分模型训练完成。",
                    "关键结果：R=0.99",
                    "输出文件：xgb.csv",
                    "下一步建议：检查特征重要性。",
                ]
            )

            response = build_chat_response(
                service,
                user_prompt="解释模型结果",
                result={"reply": repeated, "model": "conversation-coordinator", "reason": "analysis"},
            )

            self.assertEqual(response["reply"].count("已完成操作："), 1)
            self.assertEqual(response["reply"].count("关键结果：R=0.99"), 1)
            self.assertEqual(response["messages"][-1]["content"].count("输出文件：xgb.csv"), 1)

    def test_model_tool_generated_geojson_is_registered_and_returned(self) -> None:
        class FileGeneratingAgent:
            def __init__(self, service: GISWorkspaceService) -> None:
                self.service = service

            def ask(self, *args, **kwargs):
                path = self.service.manager.derived_dir / "agent_points.geojson"
                path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
                return "已生成 GeoJSON。", []

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            agent = FileGeneratingAgent(service)
            service._get_agent = lambda model_name: agent  # type: ignore[method-assign]

            intent = {"intent": "analysis_task", "confidence": 0.95, "needs_followup_resolution": False}
            plan = {
                "task_type": "analysis_task",
                "should_ask_clarification": False,
                "workflow_plan": [],
                "tool_plan": [],
                "recommended_tools": [],
            }
            with (
                mock.patch("core.service.classify_user_intent", return_value=intent),
                mock.patch("core.service.build_task_plan", return_value=plan),
                mock.patch("core.service.execute_workflow_plan", return_value={"executed": False}),
                mock.patch("core.service.execute_validated_tool_plan", return_value={"executed": False}),
                mock.patch.object(service, "_builtin_workspace_reply", return_value=None),
            ):
                response = service.ask("生成一个 GeoJSON 文件")

            self.assertEqual(len(response["artifacts"]), 1)
            artifact = response["artifacts"][0]
            self.assertEqual(artifact["filename"], "agent_points.geojson")
            self.assertEqual(artifact["type"], "derived")
            self.assertGreater(artifact["size_bytes"], 0)
            self.assertTrue(artifact["created_at"])
            self.assertEqual(artifact["meta"]["tool_name"], "agent_tool_execution")
            self.assertEqual(artifact["source"]["tool_name"], "agent_tool_execution")
            self.assertIn(f"/api/artifacts/{artifact['artifact_id']}/download", artifact["download_url"])
            assistant = service.current_messages()[-1]
            self.assertEqual(assistant["meta"]["artifacts"][0]["artifact_id"], artifact["artifact_id"])


if __name__ == "__main__":
    unittest.main()
