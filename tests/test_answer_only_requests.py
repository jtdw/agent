from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
import json

from core.config import Settings
from core.llm_task_planner import build_llm_task_plan
from core.plan_validator import validate_task_plan_before_execution
from core.service import GISWorkspaceService
from core.task_plan_schema import validate_llm_task_plan
from core.zhipu_json_client import LLMProviderError


class AnswerOnlyRequestTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_answer_only_task_plan_validates_without_tools(self) -> None:
        payload = {
            "primary_goal": "回答用户的 GIS 知识问题",
            "intent": "knowledge_qa",
            "operation": "answer_question",
            "execution_required": False,
            "response_mode": "answer_only",
            "input_assets": [],
            "asset_roles": {},
            "requested_downloads": [],
            "download_requests": [],
            "study_area": "",
            "time_range": {},
            "spatial_resolution": "",
            "candidate_tools": [],
            "selected_tools": [],
            "workflow_steps": [],
            "expected_outputs": ["chat_answer"],
            "requires_confirmation": False,
            "clarification_question": "",
            "confidence": 0.9,
            "source_attribution": {},
            "explicit_history_references": [],
            "response_language": "zh-CN",
        }

        schema = validate_llm_task_plan(payload, {"response_language": "zh-CN"})
        self.assertTrue(schema["ok"], schema)
        gate = validate_task_plan_before_execution(schema["plan"], {"response_language": "zh-CN"})

        self.assertTrue(gate["ok"], gate)
        self.assertEqual(gate["status"], "valid_answer_only")
        self.assertEqual(gate["execution_plan"]["workflow_plan"], [])
        self.assertEqual(gate["execution_plan"]["tool_plan"], [])

    def test_what_is_gis_answers_in_chinese_with_zero_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                with mock.patch("core.service.execute_workflow_plan") as workflow_mock:
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                        result = service.ask("什么是 GIS？")

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("GIS 是地理信息系统", result["reply"])
        self.assertIn("数据管理", result["reply"])
        self.assertIn("地图展示", result["reply"])
        self.assertFalse(workflow_mock.called)
        self.assertFalse(tool_mock.called)
        self.assertNotIn("计划输入", result["reply"])

    def test_ready_plan_without_executable_steps_falls_back_to_chat_answer(self) -> None:
        ready_no_step_plan = {
            "primary_goal": "回答用户的 GIS 知识问题",
            "intent": "knowledge_qa",
            "operation": "answer_question",
            "execution_required": True,
            "response_mode": "",
            "input_assets": [],
            "asset_roles": {},
            "requested_downloads": [],
            "download_requests": [],
            "study_area": "",
            "time_range": {},
            "spatial_resolution": "",
            "candidate_tools": [],
            "selected_tools": [],
            "workflow_steps": [],
            "expected_outputs": ["chat_answer"],
            "requires_confirmation": False,
            "clarification_question": "",
            "confidence": 0.82,
            "source_attribution": {},
            "explicit_history_references": [],
            "response_language": "zh-CN",
        }

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch(
                "core.service.build_llm_task_plan",
                return_value={"status": "ready", "mode": "active", "planner_source": "test", "executes_tools": False, "plan": ready_no_step_plan},
            ):
                with mock.patch("core.service.execute_workflow_plan", return_value={"executed": False}) as workflow_mock:
                    with mock.patch("core.service.execute_validated_tool_plan", return_value={"executed": False}) as tool_mock:
                        result = service.ask("gis给人们带来了什么便利")
            assistant_meta = service.current_messages()[-1].get("meta") or {}

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("GIS", result["reply"])
        self.assertNotIn("The LLM plan was validated", result["reply"])
        self.assertEqual(assistant_meta.get("interaction_type"), "chat_answer")
        self.assertNotIn("task_card", assistant_meta)
        self.assertFalse(workflow_mock.called)
        self.assertFalse(tool_mock.called)

    def test_chinese_greeting_is_answer_only_with_zero_tool_execution(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                with mock.patch("core.service.execute_download_requests") as download_mock:
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                        result = service.ask("你好")

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("你好", result["reply"])
        self.assertIn("GIS", result["reply"])
        self.assertFalse(download_mock.called)
        self.assertFalse(tool_mock.called)
        self.assertNotIn("计划输入", result["reply"])

    def test_what_is_ndvi_is_answer_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                result = service.ask("什么是 NDVI？")

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("NDVI 是归一化植被指数", result["reply"])
        self.assertNotIn("下载", result["reason"])

    def test_supported_downloads_answers_from_catalog_without_creating_job(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                with mock.patch("core.service.execute_download_requests") as download_mock:
                    result = service.ask("你支持哪些数据下载？")

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("Product Catalog", result["reply"])
        self.assertIn("地理空间数据云 DEM 30米", result["reply"])
        self.assertFalse(download_mock.called)

    def test_capability_question_with_variant_bypasses_timeout_and_executes_zero_tools(self) -> None:
        class TimeoutClient:
            def invoke(self, messages):
                raise LLMProviderError("timeout", "timeout")

        plan_result = build_llm_task_plan("你能做些什么？", {"candidate_tool_cards": [], "response_language": "zh-CN"}, client=TimeoutClient())
        self.assertEqual(plan_result["status"], "ready")
        self.assertEqual(plan_result["plan"]["response_mode"], "answer_only")
        self.assertEqual(plan_result["plan"]["llm_task_plan"]["intent"], "capability_question")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=TimeoutClient()):
                with mock.patch("core.service.execute_download_requests") as download_mock:
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                        result = service.ask("你能做些什么？")

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("GIS 数据管理", result["reply"])
        self.assertNotIn("模型服务响应超时", result["reply"])
        self.assertFalse(download_mock.called)
        self.assertFalse(tool_mock.called)

    def test_chat_mode_unknown_knowledge_question_does_not_show_execution_failure_on_timeout(self) -> None:
        class TimeoutClient:
            def invoke(self, messages):
                raise LLMProviderError("timeout", "timeout")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=TimeoutClient()):
                with mock.patch("core.service.execute_workflow_plan") as workflow_mock:
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                        result = service.ask("空间自相关在生活里有什么用？")

        self.assertEqual(result["mode"], "answer_only")
        self.assertNotIn("模型服务响应超时", result["reply"])
        self.assertNotIn("计划输入", result["reply"])
        self.assertFalse(workflow_mock.called)
        self.assertFalse(tool_mock.called)

    def test_spatial_autocorrelation_question_is_answer_only_when_provider_rate_limited(self) -> None:
        class RateLimitedClient:
            def invoke(self, messages):
                raise LLMProviderError("rate_limited", "rate limited")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.set_interaction_mode("tool_enabled")
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=RateLimitedClient()):
                with mock.patch("core.service.execute_workflow_plan") as workflow_mock:
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                        result = service.ask("空间自相关在生活里有什么用？")

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("空间自相关", result["reply"])
        self.assertIn("生活", result["reply"])
        self.assertNotIn("模型服务当前触发限流", result["reply"])
        self.assertFalse(workflow_mock.called)
        self.assertFalse(tool_mock.called)

    def test_answer_only_uses_llm_when_api_key_is_available_and_records_usage(self) -> None:
        class AnswerClient:
            last_usage = {"prompt_tokens": 21, "completion_tokens": 9, "total_tokens": 30}
            last_cached_tokens = 5
            last_latency_ms = 123
            last_retry_count = 0
            last_model = "glm-test"
            last_status = "ok"

            def __init__(self) -> None:
                self.calls = 0

            def invoke(self, messages):
                self.calls += 1
                return json.dumps({"answer": "这是来自模型的回答。", "confidence": 0.9}, ensure_ascii=False)

        client = AnswerClient()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="test-key", workdir=Path(tmp) / "workspace"))
            with mock.patch("core.service.build_default_answer_client", return_value=client):
                result = service.ask("什么是 XGBoost 回归？")
            messages = service.current_messages()

        self.assertEqual(result["mode"], "answer_only")
        self.assertEqual(result["reply"], "这是来自模型的回答。")
        self.assertEqual(client.calls, 1)
        assistant_meta = messages[-1].get("meta") or {}
        self.assertEqual(assistant_meta.get("answer_source"), "llm_answer")
        self.assertEqual(assistant_meta.get("llm_answer_usage", {}).get("usage", {}).get("total_tokens"), 30)

    def test_chat_mode_directly_uses_answer_model_without_task_planner_or_card(self) -> None:
        class AnswerClient:
            last_usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
            last_cached_tokens = 3
            last_latency_ms = 88
            last_retry_count = 0
            last_model = "glm-chat-direct"
            last_status = "ok"

            def invoke(self, messages):
                return json.dumps({"answer": "这是直接来自聊天模型的回答。", "confidence": 0.9}, ensure_ascii=False)

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="test-key", workdir=Path(tmp) / "workspace"))
            self.assertEqual(service.current_interaction_mode(), "chat_only")
            with mock.patch("core.service.build_default_answer_client", return_value=AnswerClient()):
                with mock.patch("core.service.build_llm_task_plan", side_effect=AssertionError("chat mode must not invoke task planner")):
                    with mock.patch("core.service.execute_workflow_plan", side_effect=AssertionError("chat mode must not execute workflows")):
                        with mock.patch("core.service.execute_validated_tool_plan", side_effect=AssertionError("chat mode must not execute tools")):
                            result = service.ask("gis如何进行开发")
            assistant_meta = service.current_messages()[-1].get("meta") or {}

        self.assertEqual(result["mode"], "answer_only")
        self.assertEqual(result["reply"], "这是直接来自聊天模型的回答。")
        self.assertEqual(result["reason"], "chat_only_direct_answer")
        self.assertEqual(assistant_meta.get("interaction_type"), "chat_answer")
        self.assertNotIn("task_card", assistant_meta)
        self.assertEqual(assistant_meta.get("answer_source"), "llm_answer")

    def test_answer_only_streams_model_deltas_without_tool_execution(self) -> None:
        class StreamClient:
            last_usage = {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18}
            last_cached_tokens = 2
            last_latency_ms = 25
            last_retry_count = 0
            last_model = "glm-stream-test"
            last_status = "ok"

            def stream_text(self, messages):
                yield "这是"
                yield "流式回答。"

            def invoke(self, messages):
                raise AssertionError("stream callback path must not fall back to invoke")

        deltas: list[str] = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="test-key", workdir=Path(tmp) / "workspace"))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                with mock.patch("core.service.build_default_answer_client", return_value=StreamClient()):
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                        result = service.ask("什么是 GIS？", stream_callback=deltas.append)

        self.assertEqual(result["mode"], "answer_only")
        self.assertEqual(result["reply"], "这是流式回答。")
        self.assertEqual(deltas, ["这是", "流式回答。"])
        self.assertFalse(tool_mock.called)

    def test_usage_help_upload_shp_is_answer_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                result = service.ask("如何上传 shp？")

        self.assertEqual(result["mode"], "answer_only")
        self.assertIn("压缩成 ZIP", result["reply"])
        self.assertIn("真实文件元数据", result["reply"])

    def test_execution_request_is_not_downgraded_to_answer_only(self) -> None:
        with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
            result = build_llm_task_plan("分析我上传的 DEM", {"candidate_tool_cards": [], "response_language": "zh-CN"})

        self.assertNotEqual(result.get("reason"), "valid_answer_only")
        self.assertNotEqual(result.get("plan", {}).get("response_mode"), "answer_only")
        self.assertNotEqual(result.get("plan", {}).get("execution_required"), False)


if __name__ == "__main__":
    unittest.main()
