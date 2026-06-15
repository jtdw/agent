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

    def seed_gcp_prediction_result(self, service: GISWorkspaceService, rows: int = 36) -> None:
        dataset_name = service.manager.put_table(
            "xgb_sm_demo",
            pd.DataFrame(
                {
                    "soil_moisture": [float(i) / 100.0 for i in range(rows)],
                    "xgb_sm_demo_xgb": [float(i) / 100.0 + (0.002 if i % 2 else -0.001) for i in range(rows)],
                    "date": pd.date_range("2024-01-01", periods=rows, freq="D").astype(str),
                    "lon": [115.0 + i * 0.01 for i in range(rows)],
                    "lat": [41.0 + i * 0.01 for i in range(rows)],
                }
            ),
        )
        state = ConversationState(
            active_dataset=dataset_name,
            last_model_result={
                "model": "XGBoost",
                "output_prefix": "xgb_sm_demo",
                "result_dataset": dataset_name,
                "summary": {
                    "dataset": "demo_xgboost_soil_moisture",
                    "target_col": "soil_moisture",
                    "prediction_column": "xgb_sm_demo_xgb",
                    "date_col": "date",
                },
            },
        )
        save_conversation_state(service.manager, service.current_session_id, state)

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

    def test_structured_model_reply_is_not_wrapped_again(self) -> None:
        raw = "\n".join(
            [
                "已完成操作：XGBoost 土壤水分模型训练完成。",
                "关键结果",
                "- 预测列：xgb_sm_demo_xgb",
                "输出文件",
                "- 模型文件：xgb_sm_demo_xgb_model.joblib",
                "下一步建议",
                "- 查看特征重要性表。",
            ]
        )
        model = {
            "model": "XGBoost",
            "output_prefix": "xgb_sm_demo",
            "metrics": {"R": 0.99, "RMSE": 0.01},
            "artifacts": [{"label": "metrics", "path": "derived/xgb_sm_demo_xgb_metrics.csv"}],
        }

        reply = interpret_result(
            "训练 XGBoost 模型",
            {"intent": "modeling"},
            {"task_type": "modeling"},
            raw,
            {"active_dataset": {"name": "demo_xgboost_soil_moisture.csv"}, "recent_model_result": model},
            {"model_results": [model]},
        )

        self.assertEqual(reply.count("已完成操作"), 1)
        self.assertEqual(reply.count("关键结果"), 1)
        self.assertEqual(reply.count("下一步建议"), 1)
        self.assertNotIn("最新模型结果", reply)
        self.assertNotIn("该回答基于当前工作区", reply)

    def test_service_does_not_append_model_context_to_structured_reply(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            reply = "\n".join(
                [
                    "已完成操作：XGBoost 土壤水分模型训练完成。",
                    "输出文件",
                    "- xgb_sm_demo.csv",
                    "下一步建议",
                    "- 查看残差。",
                ]
            )

            self.assertFalse(service._should_append_model_result_context("训练 XGBoost 模型", reply))

    def test_gcp_prompt_executes_uncertainty_analysis_without_mojibake(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_gcp_prediction_result(service)

            response = service.ask("做 GCP 不确定性分析。")

            self.assertEqual(response["mode"], "deterministic_workflow")
            self.assertEqual(response["reason"], "workflow_plan")
            self.assertIn("GCP 分析已完成", str(response["task_outcome"]))
            self.assertIn("GCP", response["reply"])
            self.assertIn("低于名义覆盖率", response["reply"])
            self.assertIn("校准样本", response["reply"])
            self.assertNotIn("请指定要预测的目标变量字段", response["reply"])
            for token in ["\u9417", "\u5a08", "\u934f\u62bd", "\u6d93\u5b29\u7af4", "\u5bb8\u63d2"]:
                self.assertNotIn(token, response["reply"])

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

    def test_general_gis_question_is_not_wrapped_or_grounded_in_workspace_data(self) -> None:
        class FakeGeneralAgent:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def ask(self, prompt, history=None, image_paths=None, **kwargs):
                self.calls.append(
                    {
                        "prompt": prompt,
                        "history": history,
                        "image_paths": image_paths,
                        "kwargs": kwargs,
                    }
                )
                return (
                    "\u5df2\u5b8c\u6210\u64cd\u4f5c\uff1a\u57fa\u4e8eGIS\u9886\u57df\u5171\u8bc6\u4e0e\u5f53\u524d\u5de5\u4f5c\u533a\u6570\u636e\u7c7b\u578b\u8fdb\u884c\u6982\u62ec\u6027\u56de\u7b54\u3002\n"
                    "\u4f7f\u7528\u7684\u6570\u636e\uff1a\u672a\u4f7f\u7528\u5177\u4f53\u6570\u636e\u96c6\uff0c\u4ec5\u53c2\u8003\u5de5\u4f5c\u533a\u5df2\u6709\u7684\u77e2\u91cf\uff08shandianhe_basin_boundary\uff09\u3001\u6805\u683c\uff08Dem\uff09\u548c\u8868\u683c\uff08demo_xgboost_soil_moisture_1\uff09\u3002\n"
                    "\u5173\u952e\u7ed3\u679c\uff1aGIS\u7684\u672a\u6765\u53d1\u5c55\u65b9\u5411\u5305\u62ec\u4e91\u539f\u751f\u4e0e\u5b9e\u65f6\u534f\u540c\u3001AI\u878d\u5408\u3001\u4e09\u7ef4\u4e0e\u65f6\u7a7a\u4e00\u4f53\u5316\u3002\n"
                    "\u8f93\u51fa\u6587\u4ef6\uff1a\u672c\u6b21\u672a\u751f\u6210\u65b0\u6587\u4ef6\u3002\n"
                    "\u7ed3\u679c\u542b\u4e49\uff1aGIS\u6b63\u4ece\u4f20\u7edf\u684c\u9762\u5de5\u5177\u5411\u667a\u80fd\u3001\u5b9e\u65f6\u3001\u4e09\u7ef4\u4e0e\u4e91\u534f\u540c\u7684\u5e73\u53f0\u6f14\u8fdb\u3002\n"
                    "\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a\u5982\u9700\u5728\u5de5\u4f5c\u533a\u4e2d\u5b9e\u8df5\u4e0a\u8ff0\u65b9\u5411\uff0c\u8bf7\u8bf4\u660e\u76ee\u6807\u3002",
                    [],
                )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)
            fake_agent = FakeGeneralAgent()
            service._get_agent = lambda model_name: fake_agent  # type: ignore[method-assign]

            result = service.ask("gis\u7684\u672a\u6765\u53d1\u5c55\u65b9\u5411")

        reply = result["reply"]
        self.assertEqual(result["mode"], "general_knowledge")
        self.assertNotIn("\u5df2\u5b8c\u6210\u64cd\u4f5c", reply)
        self.assertNotIn("\u4f7f\u7528\u7684\u6570\u636e", reply)
        self.assertNotIn("\u8f93\u51fa\u6587\u4ef6", reply)
        self.assertNotIn("demo_xgboost_soil_moisture_1", reply)
        self.assertNotIn("shandianhe_basin_boundary", reply)
        self.assertNotIn("Dem", reply)
        self.assertEqual(reply.count("GIS\u7684\u672a\u6765\u53d1\u5c55\u65b9\u5411\u5305\u62ec"), 1)
        self.assertIn("\u4e91\u539f\u751f", reply)
        self.assertEqual(fake_agent.calls[0]["history"], [])
        self.assertFalse(fake_agent.calls[0]["kwargs"].get("include_workspace_hint", True))  # type: ignore[union-attr]

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
