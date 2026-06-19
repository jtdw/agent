from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from core.config import Settings
from core.context_builder import build_conversation_context
from core.conversation_intent import classify_user_intent
from core.conversation_state import ConversationState, load_conversation_state, save_conversation_state
from core.followup_resolver import resolve_followup
from core.llm_intent_classifier import classify_intent_with_llm
from core.result_interpreter import interpret_result
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan


class ConversationIntelligenceTests(unittest.TestCase):
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

    def test_uploaded_data_capability_question_uses_data_upload_analysis_intent(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)
            state = ConversationState(active_dataset="soil_station", last_task_type="data_upload_analysis")

            intent = classify_user_intent("刚才上传的数据能做什么？", state.to_dict(), service.manager.workspace_summary())
            context = build_conversation_context("刚才上传的数据能做什么？", intent, state.to_dict(), service.manager, service.dashboard())
            plan = build_task_plan("刚才上传的数据能做什么？", intent, context)

            self.assertEqual(intent["intent"], "data_upload_analysis")
            self.assertIn("soil_station", str(context["active_dataset"]))
            self.assertIn("slots", plan)
            self.assertIn("profile_missing_values", plan["recommended_tools"])
            self.assertFalse(plan["should_ask_clarification"])

    def test_map_request_with_ambiguous_field_asks_minimal_clarification(self) -> None:
        context = {"workspace": {"dataset_count": 1}, "active_dataset": {"name": "soil_station", "type": "table"}, "recent_artifacts": []}
        intent = classify_user_intent("给这个数据画一张分布图", {"active_dataset": "soil_station"}, {"dataset_count": 1})

        plan = build_task_plan("给这个数据画一张分布图", intent, context)

        self.assertEqual(intent["intent"], "map_generation")
        self.assertTrue(plan["should_ask_clarification"])
        self.assertIn("字段", plan["clarification_question"])

    def test_modeling_without_target_column_asks_for_target(self) -> None:
        context = {"workspace": {"dataset_count": 1}, "active_dataset": {"name": "soil_station", "type": "table"}}
        intent = classify_user_intent("用随机森林建模预测", {"active_dataset": "soil_station"}, {"dataset_count": 1})

        plan = build_task_plan("用随机森林建模预测", intent, context)

        self.assertEqual(intent["intent"], "modeling")
        self.assertTrue(plan["should_ask_clarification"])
        self.assertIn("目标变量", plan["clarification_question"])

    def test_followup_result_reference_resolves_to_recent_model_or_artifact(self) -> None:
        state = ConversationState(last_model_result={"model": "XGBoost", "output_prefix": "soil_xgb"}).to_dict()
        dashboard = {
            "model_results": [{"model": "XGBoost", "output_prefix": "soil_xgb"}],
            "artifacts": [{"name": "soil_xgb_metrics.csv", "path": "derived/soil_xgb_metrics.csv"}],
        }

        resolved = resolve_followup("这个结果说明什么？", state, dashboard)

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["referenced_object"]["type"], "model_result")

    def test_feature_importance_followup_is_result_analysis(self) -> None:
        state = ConversationState(last_model_result={"model": "generic_xgboost", "output_prefix": "gxgb"}).to_dict()

        intent = classify_user_intent("Which factors are most important for this model?", state, {"dataset_count": 1}, enable_llm=False)

        self.assertEqual(intent["intent"], "result_analysis")
        self.assertTrue(intent["needs_followup_resolution"])

    def test_continue_followup_uses_last_user_goal(self) -> None:
        state = ConversationState(active_dataset="soil_station", last_user_goal="检查并建模", last_task_type="data_upload_analysis").to_dict()

        resolved = resolve_followup("继续", state, {"datasets": [{"name": "soil_station"}], "artifacts": []})

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["referenced_object"]["type"], "task")
        self.assertIn("检查并建模", resolved["referenced_object"]["label"])

    def test_recent_map_followup_resolves_to_last_map_path(self) -> None:
        state = ConversationState(last_map_path="plots/soil_map.png").to_dict()

        resolved = resolve_followup("刚才那张图怎么看？", state, {"artifacts": []})

        self.assertTrue(resolved["resolved"])
        self.assertEqual(resolved["referenced_object"]["type"], "map")
        self.assertIn("soil_map.png", resolved["referenced_object"]["path"])

    def test_map_request_without_data_asks_for_dataset_first(self) -> None:
        intent = classify_user_intent("画一张地图", {}, {"dataset_count": 0})

        plan = build_task_plan("画一张地图", intent, {"workspace": {"dataset_count": 0}, "active_dataset": None})

        self.assertEqual(intent["intent"], "map_generation")
        self.assertTrue(plan["should_ask_clarification"])
        self.assertIn("上传", plan["clarification_question"])

    def test_model_result_interpreter_explains_metrics(self) -> None:
        dashboard = {
            "model_results": [
                {
                    "model": "XGBoost",
                    "metrics": {"R": 0.72, "RMSE": 0.12, "MAE": 0.09, "Bias": -0.01, "NSE": 0.51},
                    "artifacts": [{"label": "指标表", "display_path": "derived/xgb_metrics.csv"}],
                    "recommendations": ["检查残差空间分布"],
                }
            ]
        }
        context = {"active_dataset": {"name": "soil_station"}, "recent_model_result": dashboard["model_results"][0]}
        plan = {"task_type": "result_analysis", "recommended_tools": [], "expected_outputs": ["模型解释"]}

        reply = interpret_result("解释模型结果", {"intent": "result_analysis"}, plan, "XGBoost 完成", context, dashboard)

        for token in ["R", "RMSE", "MAE", "Bias", "NSE", "特征重要性", "残差空间分布"]:
            self.assertIn(token, reply)

    def test_result_interpreter_reports_missing_selected_model_result(self) -> None:
        context = {
            "referenced_object": {
                "type": "model_result",
                "id": "missing_model",
                "missing": True,
                "source": "frontend_context",
            }
        }

        reply = interpret_result(
            "模型效果怎么样",
            {"intent": "result_analysis"},
            {"task_type": "result_analysis"},
            "",
            context,
            {"model_results": []},
        )

        self.assertIn("missing_model", reply)
        self.assertIn("找不到", reply)
        self.assertNotIn("RMSE=0", reply)

    def test_error_followup_explains_last_error(self) -> None:
        state = ConversationState(last_error={"message": "字段 target 不存在", "task_type": "modeling"}).to_dict()
        resolved = resolve_followup("为什么失败？", state, {})
        context = {"recent_error": state["last_error"], "referenced_object": resolved["referenced_object"]}

        reply = interpret_result("为什么失败？", {"intent": "troubleshooting"}, {"task_type": "troubleshooting"}, "", context, {})

        self.assertIn("字段 target 不存在", reply)
        self.assertIn("下一步建议", reply)

    def test_next_step_advice_uses_active_dataset_or_result(self) -> None:
        context = {"active_dataset": {"name": "soil_station", "type": "table"}, "recent_model_result": None}
        intent = classify_user_intent("下一步做什么？", {"active_dataset": "soil_station"}, {"dataset_count": 1})

        plan = build_task_plan("下一步做什么？", intent, context)
        reply = interpret_result("下一步做什么？", intent, plan, "", context, {})

        self.assertIn("soil_station", reply)
        self.assertIn("下一步建议", reply)

    def test_conversation_state_persists_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            session_id = service.current_session_id
            state = ConversationState(active_dataset="soil_station", last_task_type="data_upload_analysis")

            save_conversation_state(service.manager, session_id, state)
            loaded = load_conversation_state(service.manager, session_id)

            self.assertEqual(loaded.active_dataset, "soil_station")
            self.assertEqual(loaded.last_task_type, "data_upload_analysis")

    def test_fixture_conversation_cases_classify_and_plan(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "conversation_cases.json"
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["id"]):
                intent = classify_user_intent(
                    case["prompt"],
                    case.get("state", {}),
                    case.get("workspace_summary", {}),
                    enable_llm=False,
                )
                context = dict(case.get("context", {}))
                if intent.get("referenced_object") and "referenced_object" not in context:
                    context["referenced_object"] = intent["referenced_object"]
                plan = build_task_plan(case["prompt"], intent, context)

                self.assertEqual(intent["intent"], case["expected_intent"])
                for secondary in case.get("expected_secondary_intents", []):
                    self.assertIn(secondary, intent.get("secondary_intents", []))
                for flag, expected in case.get("expected_plan_flags", {}).items():
                    self.assertEqual(plan.get(flag), expected)

    def test_high_confidence_rule_result_does_not_call_llm_classifier(self) -> None:
        calls: list[str] = []

        def fake_llm_classifier(prompt, conversation_state, workspace_summary):
            calls.append(prompt)
            return {
                "available": True,
                "intent": "unclear_request",
                "confidence": 0.9,
                "reasoning_summary": "should not be used",
            }

        intent = classify_user_intent(
            "帮我制图",
            {"active_dataset": "soil_station"},
            {"dataset_count": 1},
            llm_classifier=fake_llm_classifier,
            enable_llm=True,
        )

        self.assertEqual(intent["intent"], "map_generation")
        self.assertEqual(intent["classifier"], "rule")
        self.assertEqual(calls, [])

    def test_low_confidence_complex_prompt_can_use_fake_llm_classifier(self) -> None:
        calls: list[str] = []

        def fake_llm_classifier(prompt, conversation_state, workspace_summary):
            calls.append(prompt)
            return {
                "available": True,
                "intent": "data_processing",
                "confidence": 0.88,
                "referenced_object": {"type": "dataset", "name": "soil_station"},
                "missing_inputs": [],
                "reasoning_summary": "识别为处理后制图的复合任务。",
                "should_ask_clarification": False,
                "secondary_intents": ["map_generation"],
            }

        intent = classify_user_intent(
            "帮我整理一下这个数据并出一张图",
            {"active_dataset": "soil_station"},
            {"dataset_count": 1},
            llm_classifier=fake_llm_classifier,
            enable_llm=True,
        )

        self.assertEqual(intent["intent"], "data_processing")
        self.assertEqual(intent["classifier"], "llm")
        self.assertIn("map_generation", intent["secondary_intents"])
        self.assertEqual(calls, ["帮我整理一下这个数据并出一张图"])

    def test_llm_intent_classifier_rejects_invalid_json(self) -> None:
        class InvalidJsonClient:
            def classify_intent(self, prompt, conversation_state, workspace_summary):
                return "not-json"

        result = classify_intent_with_llm("帮我整理一下", {}, {}, client=InvalidJsonClient())

        self.assertFalse(result["available"])
        self.assertEqual(result["fallback_reason"], "llm_invalid_json")

    def test_invalid_llm_result_falls_back_to_rule_result(self) -> None:
        def invalid_llm_classifier(prompt, conversation_state, workspace_summary):
            return {"available": False, "fallback_reason": "llm_invalid_json"}

        intent = classify_user_intent(
            "帮我整理一下这个数据",
            {"active_dataset": "soil_station"},
            {"dataset_count": 1},
            llm_classifier=invalid_llm_classifier,
            enable_llm=True,
        )

        self.assertEqual(intent["classifier"], "rule")
        self.assertEqual(intent["fallback_reason"], "llm_invalid_json")

    def test_no_llm_key_still_returns_structured_fallback(self) -> None:
        with mock.patch.dict("os.environ", {"GIS_AGENT_ENABLE_LLM_INTENT": "1"}, clear=False):
            with mock.patch.dict("os.environ", {"ZAI_API_KEY": ""}, clear=False):
                intent = classify_user_intent("想综合看一下这里适合怎么分析", {}, {"dataset_count": 0})

        self.assertIn(intent["intent"], {"unclear_request", "general_gis_question"})
        self.assertEqual(intent["classifier"], "rule")
        self.assertIn("fallback_reason", intent)

    def test_low_confidence_plan_asks_clarification_before_tools(self) -> None:
        intent = {
            "intent": "unclear_request",
            "confidence": 0.42,
            "missing_inputs": [],
            "referenced_object": None,
            "secondary_intents": [],
        }

        plan = build_task_plan("帮我看一下", intent, {"workspace": {"dataset_count": 1}, "active_dataset": {"name": "soil"}})

        self.assertTrue(plan["should_ask_clarification"])
        self.assertEqual(plan["recommended_tools"], [])


if __name__ == "__main__":
    unittest.main()
