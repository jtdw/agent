from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config import Settings
from core.llm_config import load_llm_provider_config
from core.llm_task_planner import build_default_llm_task_planner_client, build_llm_task_plan
from core.llm_usage import recent_llm_usage
from core.presentation_result import build_presentation_bundle
from core.service import GISWorkspaceService
from core.workflow_coordinator import build_coordinator_decision
from core.zhipu_json_client import LLMProviderError, ZhipuJSONClient


class ZhipuProviderContractTests(unittest.TestCase):
    def env(self, extra: dict[str, str]):
        values = {
            "LLM_PROVIDER": "zai",
            "LLM_MODEL": "glm-4.5-air",
            "ZAI_API_KEY": "test-zai-key",
            "LLM_TIMEOUT": "7",
            "LLM_MAX_RETRIES": "1",
            "LLM_MAX_TOKENS": "900",
            "GIS_AGENT_E2E_LLM_FIXTURES": "0",
        }
        values.update(extra)
        return mock.patch.dict(os.environ, values, clear=False)

    def test_zhipu_json_mode_payload_and_usage_cached_tokens(self) -> None:
        captured: dict[str, object] = {}

        def transport(payload, config):
            captured.update(payload)
            return {
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15, "prompt_tokens_details": {"cached_tokens": 8}},
            }

        with self.env({}):
            config = load_llm_provider_config()
            client = ZhipuJSONClient(config, api_key="test-zai-key", transport=transport, operation="planner")
            content = client.invoke([("system", "sys"), ("user", "hi")])

        self.assertEqual(content, "{\"ok\": true}")
        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertFalse(captured["stream"])
        self.assertEqual(captured["max_tokens"], 900)
        self.assertNotIn("tools", captured)
        self.assertNotIn("functions", captured)
        self.assertEqual(client.last_cached_tokens, 8)
        self.assertEqual(recent_llm_usage(1)[-1]["cached_tokens"], 8)
        self.assertEqual(recent_llm_usage(1)[-1]["status"], "ok")

    def test_zhipu_retries_and_falls_back_to_json_capable_model(self) -> None:
        calls: list[str] = []

        def transport(payload, config):
            model = str(payload["model"])
            calls.append(model)
            if model == "glm-primary":
                raise LLMProviderError("timeout", "timeout")
            return {
                "choices": [{"message": {"content": "{\"ok\": true}"}}],
                "usage": {"total_tokens": 5, "prompt_tokens_details": {"cached_tokens": 1}},
            }

        with self.env({"LLM_MODEL": "glm-primary", "LLM_FALLBACK_MODELS": "glm-backup", "LLM_MAX_RETRIES": "1"}):
            config = load_llm_provider_config()
            client = ZhipuJSONClient(config, api_key="test-zai-key", transport=transport, operation="planner")
            content = client.invoke("hello")

        self.assertEqual(content, "{\"ok\": true}")
        self.assertEqual(calls, ["glm-primary", "glm-primary", "glm-backup"])
        self.assertEqual(client.last_model, "glm-backup")
        self.assertEqual(client.last_retry_count, 1)
        self.assertGreaterEqual(client.last_latency_ms, 0)

    def test_default_zai_client_uses_native_json_client(self) -> None:
        with self.env({}):
            client = build_default_llm_task_planner_client()
        self.assertIsInstance(client, ZhipuJSONClient)

    def test_coordinator_uses_json_mode_client_and_schema_validation(self) -> None:
        captured: dict[str, object] = {}

        def transport(payload, config):
            captured.update(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "stop_success",
                                    "next_step_id": "",
                                    "selected_next_action": "",
                                    "required_tool": "",
                                    "required_inputs": {},
                                    "reason": "已完成。",
                                    "user_question": "",
                                    "confidence": 0.9,
                                    "response_language": "zh-CN",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 9, "prompt_tokens_details": {"cached_tokens": 2}},
            }

        with self.env({}):
            config = load_llm_provider_config()
            client = ZhipuJSONClient(config, api_key="test-zai-key", transport=transport, operation="coordinator")
            decision = build_coordinator_decision(
                {"primary_goal": "测试", "selected_tools": [], "candidate_tools": [], "response_language": "zh-CN"},
                None,
                [],
                {"results": []},
                "继续",
                client=client,
            )

        self.assertEqual(decision["status"], "ready")
        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", captured)

    def test_result_interpreter_uses_json_mode_and_filters_forged_artifacts(self) -> None:
        captured: dict[str, object] = {}

        def transport(payload, config):
            captured.update(payload)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": "presentation-result/v1",
                                    "response_language": "zh-CN",
                                    "status": "succeeded",
                                    "concise_summary": "已完成。",
                                    "executed_steps": [{"step_id": "s1", "tool_name": "tool", "status": "succeeded"}],
                                    "data_sources": ["dataset"],
                                    "result_highlights": [],
                                    "artifact_refs": [{"artifact_id": "fake_artifact", "title": "伪造", "type": "tif"}],
                                    "map_layer_refs": [],
                                    "table_refs": [],
                                    "image_refs": [],
                                    "warnings": [],
                                    "error_summary": "",
                                    "next_action_suggestions": [],
                                    "clarification_question": "",
                                    "confidence": 0.9,
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 11, "prompt_tokens_details": {"cached_tokens": 3}},
            }

        with self.env({}):
            config = load_llm_provider_config()
            client = ZhipuJSONClient(config, api_key="test-zai-key", transport=transport, operation="result_interpreter")
            bundle = build_presentation_bundle(
                task_goal="测试",
                task_plan_summary={"primary_goal": "测试", "response_language": "zh-CN"},
                coordinator_status="succeeded",
                normalized_results=[
                    {
                        "status": "succeeded",
                        "step_id": "s1",
                        "tool_name": "tool",
                        "outputs": {"result_dataset": "dataset"},
                        "artifacts": [],
                        "map_layers": [],
                        "tables": [],
                        "images": [],
                        "warnings": [],
                        "errors": [],
                        "next_actions": [],
                        "input_asset_ids": [],
                    }
                ],
                llm_client=client,
                response_language="zh-CN",
            )

        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertEqual(bundle["presentation_result"]["artifact_refs"], [])

    def test_provider_errors_become_controlled_zero_tool_response(self) -> None:
        class TimeoutClient:
            def invoke(self, messages):
                raise LLMProviderError("timeout", "timeout")

        result = build_llm_task_plan("下载成都市30m的DEM数据", {"candidate_tool_cards": []}, client=TimeoutClient())

        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["executes_tools"])
        self.assertIn("超时", result["plan"]["clarification_question"])

    def test_safety_and_rate_limit_errors_are_controlled_zero_tool_responses(self) -> None:
        class SafetyClient:
            def invoke(self, messages):
                raise LLMProviderError("safety_blocked", "blocked")

        class RateLimitClient:
            def invoke(self, messages):
                raise LLMProviderError("rate_limited", "rate")

        safety = build_llm_task_plan("下载成都市30m的DEM数据", {"candidate_tool_cards": []}, client=SafetyClient())
        rate = build_llm_task_plan("下载成都市30m的DEM数据", {"candidate_tool_cards": []}, client=RateLimitClient())

        self.assertEqual(safety["status"], "safety_blocked")
        self.assertEqual(rate["status"], "rate_limited")
        self.assertFalse(safety["executes_tools"])
        self.assertFalse(rate["executes_tools"])
        self.assertIn("安全", safety["plan"]["clarification_question"])
        self.assertIn("限流", rate["plan"]["clarification_question"])

    def test_invalid_json_returns_controlled_zero_tool_response(self) -> None:
        class InvalidJSONClient:
            def invoke(self, messages):
                return "not-json"

        result = build_llm_task_plan("下载成都市30m的DEM数据", {"candidate_tool_cards": []}, client=InvalidJSONClient())

        self.assertEqual(result["status"], "invalid_json")
        self.assertFalse(result["executes_tools"])
        self.assertIn("格式无效", result["plan"]["clarification_question"])

    def test_planner_result_exposes_provider_usage(self) -> None:
        class UsageClient:
            last_usage = {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}
            last_cached_tokens = 6

            def invoke(self, messages):
                return json.dumps(
                    {
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
                    },
                    ensure_ascii=False,
                )

        result = build_llm_task_plan("请生成结构化聊天计划", {"candidate_tool_cards": []}, client=UsageClient())

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["llm_usage"]["cached_tokens"], 6)
        self.assertEqual(result["llm_usage"]["usage"]["total_tokens"], 14)

    def test_answer_only_and_capability_questions_do_not_execute_tools_when_provider_unavailable(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            service.current_session_id = service.create_new_session()
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", return_value=None):
                with mock.patch("core.service.execute_validated_tool_plan") as tool_mock:
                    gis = service.ask("什么是 GIS？")
                    capability = service.ask("你可以做什么")

        self.assertEqual(gis["mode"], "answer_only")
        self.assertEqual(capability["mode"], "answer_only")
        self.assertFalse(tool_mock.called)
        self.assertIn("GIS 是地理信息系统", gis["reply"])

    def test_pending_confirmation_continue_is_not_replanned_by_provider(self) -> None:
        from tests.test_pending_download_confirmation import _chengdu_dem_plan

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
            service.current_user_id = "u_zhipu"
            service.current_session_id = service.create_new_session()
            service.set_interaction_mode("tool_enabled")
            with mock.patch("core.service.build_llm_task_plan", return_value={"status": "ready", "plan": _chengdu_dem_plan()}):
                first = service.ask("下载成都市 30m DEM")
            with mock.patch("core.llm_task_planner.build_default_llm_task_planner_client", side_effect=AssertionError("provider should not decide a new download plan")):
                second = service.ask(f"下载成都市 30m DEM confirmed_action_id={first['confirmation_id']}")

        self.assertEqual(second["reason"], "confirmed_pending_download")


if __name__ == "__main__":
    unittest.main()
