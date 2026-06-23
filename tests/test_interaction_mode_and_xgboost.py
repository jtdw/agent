from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from core.config import Settings
from core.conversation_state import recover_conversation_state, save_conversation_state
from core.service import GISWorkspaceService
from core.task_plan_schema import validate_llm_task_plan


XGB_PROMPT = (
    "使用当前上传的数据 demo_xgboost_soil_moisture.csv 训练 XGBoost 土壤水分模型。"
    "目标列是 soil_moisture。特征列使用 elevation,slope,precip_7d,ndvi,lst,lon,lat。"
    "时间列是 date。输出名称为 xgb_sm_demo。开启空间分块验证，生成预测结果、残差、"
    "特征重要性、精度指标和模型文件。"
)


def make_service(root: Path) -> GISWorkspaceService:
    settings = Settings(api_key="", workdir=root / "workspace")
    settings.ensure_dirs()
    return GISWorkspaceService(settings)


def add_demo_xgb_table(service: GISWorkspaceService, rows: int = 48) -> str:
    rng = np.random.default_rng(7)
    lon = np.linspace(104.0, 104.9, rows)
    lat = np.linspace(30.0, 30.8, rows)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-06-01", periods=rows, freq="D").astype(str),
            "lon": lon,
            "lat": lat,
            "elevation": rng.normal(500, 30, rows),
            "slope": rng.uniform(1, 15, rows),
            "precip_7d": rng.uniform(0, 60, rows),
            "ndvi": rng.uniform(0.2, 0.8, rows),
            "lst": rng.uniform(285, 310, rows),
        }
    )
    df["soil_moisture"] = 0.18 + df["precip_7d"] * 0.002 + df["ndvi"] * 0.1 - df["slope"] * 0.001
    name = service.manager.put_table("demo_xgboost_soil_moisture", df)
    state = recover_conversation_state(service.manager, service.current_session_id)
    state.active_dataset = name
    save_conversation_state(service.manager, service.current_session_id, state)
    return name


def llm_plan_for_xgb(prompt: str, context: dict, **_: object) -> dict:
    dataset = str((context.get("active_dataset") or {}).get("name") or "demo_xgboost_soil_moisture")
    phase2 = {
        "primary_goal": "soil_moisture_xgboost_regression",
        "intent": "modeling",
        "operation": "train_model",
        "input_assets": [{"role": "training_table", "name": dataset, "source": "current_upload"}],
        "asset_roles": {
            dataset: "training_table",
            "soil_moisture": "target_variable",
            "elevation": "model_feature",
            "slope": "model_feature",
            "precip_7d": "model_feature",
            "ndvi": "model_feature",
            "lst": "model_feature",
            "lon": "coordinate_field",
            "lat": "coordinate_field",
            "date": "time_field",
        },
        "requested_downloads": [],
        "download_requests": [],
        "study_area": "",
        "time_range": {},
        "spatial_resolution": "",
        "candidate_tools": ["train_xgboost_fusion_model"],
        "selected_tools": ["train_xgboost_fusion_model"],
        "workflow_steps": [
            {
                "step_id": "train_xgboost",
                "tool_name": "train_xgboost_fusion_model",
                "args": {
                    "dataset_name": dataset,
                    "target_col": "soil_moisture",
                    "feature_cols": "elevation,slope,precip_7d,ndvi,lst,lon,lat",
                    "date_col": "date",
                    "lon_col": "lon",
                    "lat_col": "lat",
                    "output_name": "xgb_sm_demo",
                    "spatial_validation": True,
                    "validation_method": "spatial_block",
                    "spatial_block_count": 4,
                    "requested_outputs": "predictions,residuals,feature_importance,metrics,model",
                },
                "expected_outputs": ["prediction_table", "residual_table", "feature_importance", "metrics", "model_file"],
            }
        ],
        "expected_outputs": ["prediction_table", "residual_table", "feature_importance", "metrics", "model_file"],
        "requires_confirmation": False,
        "execution_required": True,
        "response_mode": "",
        "clarification_question": "",
        "confidence": 0.92,
        "source_attribution": {
            dataset: "current_upload",
            "soil_moisture": "current_upload",
            "elevation": "current_upload",
            "slope": "current_upload",
            "precip_7d": "current_upload",
            "ndvi": "current_upload",
            "lst": "current_upload",
            "lon": "current_upload",
            "lat": "current_upload",
            "date": "current_upload",
        },
        "explicit_history_references": [],
        "response_language": "zh-CN",
    }
    validation = validate_llm_task_plan(phase2, context)
    if not validation.get("ok"):
        return {"status": "invalid_plan", "mode": "active", "planner_source": "test", "plan": validation.get("fallback_plan"), "errors": validation.get("errors")}
    return {"status": "ready", "mode": "active", "planner_source": "test", "executes_tools": False, "plan": validation["plan"]}


def llm_dirty_plan_for_xgb(prompt: str, context: dict, **_: object) -> dict:
    dataset = str((context.get("active_dataset") or {}).get("name") or "demo_xgboost_soil_moisture")
    phase2 = {
        "primary_goal": "soil_moisture_xgboost_regression",
        "intent": "modeling",
        "operation": "train_model",
        "input_assets": [dataset],
        "asset_roles": {
            dataset: "training_table",
            "soil_moisture": "target_variable",
            "elevation": "model_feature",
            "slope": "model_feature",
            "precip_7d": "model_feature",
            "ndvi": "model_feature",
            "lst": "model_feature",
            "lon": "coordinate_field",
            "lat": "coordinate_field",
            "date": "time_field",
        },
        "requested_downloads": None,
        "download_requests": None,
        "study_area": None,
        "time_range": None,
        "spatial_resolution": None,
        "candidate_tools": ["train_xgboost_fusion_model"],
        "selected_tools": ["train_xgboost_fusion_model"],
        "workflow_steps": [
            {
                "step_id": 1,
                "tool_name": "train_xgboost_fusion_model",
                "args": {
                    "dataset_name": dataset,
                    "target_col": "soil_moisture",
                    "feature_cols": "elevation,slope,precip_7d,ndvi,lst,lon,lat",
                    "date_col": "date",
                    "lon_col": "lon",
                    "lat_col": "lat",
                    "output_name": "xgb_sm_demo",
                    "spatial_validation": True,
                    "validation_method": "spatial_block",
                    "requested_outputs": "predictions,residuals,feature_importance,metrics,model",
                },
                "expected_outputs": ["prediction_table", "residual_table", "feature_importance", "metrics", "model_file"],
            }
        ],
        "expected_outputs": ["prediction_table", "residual_table", "feature_importance", "metrics", "model_file"],
        "requires_confirmation": False,
        "execution_required": True,
        "response_mode": None,
        "clarification_question": None,
        "confidence": "0.92",
        "source_attribution": ["current_upload"],
        "explicit_history_references": None,
        "response_language": "zh-CN",
    }
    validation = validate_llm_task_plan(phase2, context)
    if not validation.get("ok"):
        return {"status": "invalid_plan", "mode": "active", "planner_source": "test", "plan": validation.get("fallback_plan"), "errors": validation.get("errors")}
    return {"status": "ready", "mode": "active", "planner_source": "test", "executes_tools": False, "plan": validation["plan"]}


def llm_answer_only(prompt: str, context: dict, **_: object) -> dict:
    phase2 = {
        "primary_goal": "answer_gis_question",
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
    return {"status": "ready", "mode": "active", "planner_source": "test", "executes_tools": False, "plan": validate_llm_task_plan(phase2, context)["plan"]}


class InteractionModeAndXGBoostTests(unittest.TestCase):
    def test_empty_new_session_is_reused_and_recent_list_collapses_duplicates(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = make_service(Path(tmp))
            first = service.create_new_session()
            second = service.create_new_session()
            third = service.create_new_session()

            self.assertEqual(first, second)
            self.assertEqual(second, third)
            sessions = service.list_sessions()
            empty_new = [item for item in sessions if item.get("title") == "新对话" and item.get("message_count") == 0]
            self.assertEqual(len(empty_new), 1)

    def test_default_mode_is_chat_only_and_persists_per_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = make_service(Path(tmp))
            self.assertEqual(service.current_interaction_mode(), "chat_only")
            service.set_interaction_mode("tool_enabled")
            first = service.current_session_id
            self.assertEqual(service.current_interaction_mode(), "tool_enabled")
            second = service.create_new_session()
            self.assertEqual(service.current_interaction_mode(), "chat_only")
            service.switch_session(first)
            self.assertEqual(service.current_interaction_mode(), "tool_enabled")
            service.switch_session(second)
            self.assertEqual(service.current_interaction_mode(), "chat_only")

    def test_chat_mode_blocks_xgboost_execution_without_jobs_or_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = make_service(Path(tmp))
            add_demo_xgb_table(service)
            with mock.patch("core.service.build_llm_task_plan", side_effect=llm_plan_for_xgb):
                with mock.patch("core.service.execute_workflow_plan") as workflow_exec:
                    with mock.patch("core.service.execute_validated_tool_plan") as tool_exec:
                        response = service.ask(XGB_PROMPT)
            self.assertEqual(response["mode"], "chat_only_blocked")
            self.assertIn("当前处于聊天模式", response["reply"])
            self.assertIn("打开工具模式", response["reply"])
            workflow_exec.assert_not_called()
            tool_exec.assert_not_called()
            self.assertFalse(service.dashboard()["model_results"])

    def test_tool_mode_answer_only_still_executes_zero_tools(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = make_service(Path(tmp))
            service.set_interaction_mode("tool_enabled")
            with mock.patch("core.service.build_llm_task_plan", side_effect=llm_answer_only):
                with mock.patch("core.service.execute_workflow_plan") as workflow_exec:
                    response = service.ask("什么是 GIS？")
            self.assertEqual(response["mode"], "answer_only")
            workflow_exec.assert_not_called()

    def test_tool_mode_runs_real_xgboost_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = make_service(Path(tmp))
            service.set_interaction_mode("tool_enabled")
            add_demo_xgb_table(service, rows=56)
            with mock.patch("core.service.build_llm_task_plan", side_effect=llm_plan_for_xgb):
                with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                    response = service.ask(XGB_PROMPT)
            self.assertEqual(response["mode"], "validated_workflow_executor")
            artifacts = response.get("artifacts") or []
            self.assertGreaterEqual(len(artifacts), 5)
            artifact_types = {str(item.get("type") or "") for item in artifacts}
            self.assertIn("model", artifact_types)
            self.assertTrue({"predictions", "residuals", "metrics", "feature_importance"} & artifact_types)
            dashboard = service.dashboard()
            self.assertTrue(dashboard["model_results"])
            diagnostics = dashboard["model_results"][0].get("diagnostics") or {}
            self.assertIn("metrics", diagnostics)

    def test_tool_mode_normalizes_llm_json_type_drift_for_xgboost(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = make_service(Path(tmp))
            service.set_interaction_mode("tool_enabled")
            add_demo_xgb_table(service, rows=56)
            with mock.patch("core.service.build_llm_task_plan", side_effect=llm_dirty_plan_for_xgb):
                with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                    response = service.ask(XGB_PROMPT)
            self.assertEqual(response["mode"], "validated_workflow_executor")
            self.assertNotIn("缺失、无效或不可信", response["reply"])
            artifacts = response.get("artifacts") or []
            self.assertTrue(any(str(item.get("title") or "").endswith("xgb_sm_demo_predictions.csv") for item in artifacts))


if __name__ == "__main__":
    unittest.main()
