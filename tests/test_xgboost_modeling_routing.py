import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from core.config import Settings
from core.conversation_intent import classify_user_intent
from core.object_resolver import resolve_object_reference
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.workflow_executor import execute_workflow_plan, parse_workflow_result


pytestmark = pytest.mark.slow


DEMO_DATASET = "aefcc18e8625419890b38194ecd810a8_demo_xgboost_soil_moisture"
DEMO_PROMPT = f"@{{{DEMO_DATASET}}} 对其进行xgboost分析"
FULL_PROMPT = (
    "使用当前上传的数据demo_xgboost_soil_moisture.csv训练 XGBoost 土壤水分模型。"
    "目标列是 soil_moisture。"
    "特征列使用 elevation,slope,precip_7d,ndvi,lst,lon,lat。"
    "时间列是 date。"
    "输出名称为 xgb_sm_demo。"
    "开启空间分块验证，生成预测结果、残差、特征重要性、精度指标和模型文件。"
)
USER_SPACED_PROMPT = (
    "使用当前上传的数据demo_xgboost_soil_moisture.csv训练 XGBoost 土壤水分模型。 "
    "目标列是 soil_moisture。 "
    "特征列使用 elevation,slope,precip_7d,ndvi,lst,lon,lat。 "
    "时间列是 date。 "
    "输出名称为 xgb_sm_demo。 "
    "开启空间分块验证，生成预测结果、残差、特征重要性、精度指标和模型文件。"
)
XGBOOST_WITH_GCP_PROMPT = USER_SPACED_PROMPT + " Perform GCP uncertainty analysis, prediction intervals, coverage and interval width maps."


def _demo_frame(rows: int = 48) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "station_id": [f"S{i:03d}" for i in range(rows)],
            "lon": [100.0 + (i % 8) * 0.05 for i in range(rows)],
            "lat": [30.0 + (i // 8) * 0.05 for i in range(rows)],
            "date": pd.date_range("2024-01-01", periods=rows, freq="D").strftime("%Y-%m-%d"),
            "soil_moisture": [0.18 + i * 0.003 for i in range(rows)],
            "elevation": [400.0 + i * 2.0 for i in range(rows)],
            "slope": [2.0 + (i % 6) * 0.4 for i in range(rows)],
            "precip_7d": [10.0 + (i % 9) * 1.5 for i in range(rows)],
            "ndvi": [0.25 + (i % 12) * 0.02 for i in range(rows)],
            "lst": [285.0 + (i % 10) * 0.8 for i in range(rows)],
        }
    )


class XGBoostModelingRoutingTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        service = GISWorkspaceService(settings)
        service.set_interaction_mode("tool_enabled")
        return service

    def seed_demo(self, service: GISWorkspaceService, *, name: str = DEMO_DATASET, include_coords: bool = True) -> None:
        df = _demo_frame()
        if not include_coords:
            df = df.drop(columns=["lon", "lat"])
        service.manager.put_table(name, df)

    def context(self, service: GISWorkspaceService, *, name: str = DEMO_DATASET, include_coords: bool = True) -> dict:
        fields = [str(col) for col in service.manager.get_table(name).columns]
        numeric = [col for col in fields if col != "date" and col != "station_id"]
        return {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": name, "type": "table", "meta": {"columns": fields, "rows": 48}},
            "available_datasets": service.manager.list_datasets(),
            "available_fields": fields,
            "numeric_fields": numeric if include_coords else [col for col in numeric if col not in {"lon", "lat"}],
            "likely_target_fields": ["soil_moisture"],
        }

    def active_rule_plan(self, service: GISWorkspaceService):
        def active_plan(prompt_text: str, context: dict, **kwargs):
            plan = build_task_plan(prompt_text, context.get("intent") or {}, context, manager=service.manager)
            return {"status": "ready", "mode": "active", "planner_source": "test", "executes_tools": False, "plan": plan}

        return active_plan

    def test_short_xgboost_request_uses_field_candidates_not_template_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service)
            context = self.context(service)
            intent = classify_user_intent("对其进行xgboost分析", {"active_dataset": DEMO_DATASET}, {"dataset_count": 1}, enable_llm=False)

            plan = build_task_plan("对其进行xgboost分析", intent, context, manager=service.manager)

            self.assertEqual(intent["intent"], "modeling")
            self.assertEqual(plan["slots"]["model_type"], "xgboost")
            self.assertTrue(plan["should_ask_clarification"])
            self.assertIn("soil_moisture", plan["clarification_question"])
            self.assertIn("elevation", plan["clarification_question"])
            self.assertNotIn("raster_basic_stats", str(plan.get("workflow_plan", [])))

    def test_explicit_at_dataset_binding_overrides_dem_substring(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service)
            context = self.context(service)

            resolved = resolve_object_reference(DEMO_PROMPT, context, manager=service.manager, object_type="dataset")
            intent = classify_user_intent(DEMO_PROMPT, {"active_dataset": "other_table"}, {"dataset_count": 1}, enable_llm=False)
            plan = build_task_plan(DEMO_PROMPT, intent, context, manager=service.manager)

            self.assertTrue(resolved["ok"])
            self.assertEqual(resolved["name"], DEMO_DATASET)
            self.assertEqual(intent["intent"], "modeling")
            self.assertNotIn("raster_basic_stats", [step.get("tool_name") for step in plan.get("workflow_plan", [])])

    def test_full_xgboost_command_builds_modeling_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service)
            context = self.context(service)
            intent = classify_user_intent(FULL_PROMPT, {"active_dataset": DEMO_DATASET}, {"dataset_count": 1}, enable_llm=False)

            plan = build_task_plan(FULL_PROMPT, intent, context, manager=service.manager)

            self.assertEqual(intent["intent"], "modeling")
            self.assertFalse(plan["should_ask_clarification"])
            args = plan["validated_tool_args"]["train_xgboost_fusion_model"]
            self.assertEqual(args["dataset_name"], DEMO_DATASET)
            self.assertEqual(args["target_col"], "soil_moisture")
            self.assertEqual(args["feature_cols"], "elevation,slope,precip_7d,ndvi,lst,lon,lat")
            self.assertEqual(args["date_col"], "date")
            self.assertEqual(args["output_name"], "xgb_sm_demo")
            self.assertTrue(args["spatial_validation"])
            self.assertEqual(args["lon_col"], "lon")
            self.assertEqual(args["lat_col"], "lat")
            self.assertIn("train_xgboost_fusion_model", [step.get("tool_name") for step in plan["workflow_plan"]])
            self.assertNotIn("raster_basic_stats", [step.get("tool_name") for step in plan["workflow_plan"]])

    def test_spaced_user_xgboost_command_builds_modeling_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service, name="demo_xgboost_soil_moisture")
            context = self.context(service, name="demo_xgboost_soil_moisture")
            intent = classify_user_intent(USER_SPACED_PROMPT, {"active_dataset": "demo_xgboost_soil_moisture"}, {"dataset_count": 1}, enable_llm=False)

            plan = build_task_plan(USER_SPACED_PROMPT, intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            args = plan["validated_tool_args"]["train_xgboost_fusion_model"]
            self.assertEqual(args["target_col"], "soil_moisture")
            self.assertEqual(args["feature_cols"], "elevation,slope,precip_7d,ndvi,lst,lon,lat")
            self.assertEqual(args["date_col"], "date")
            self.assertEqual(args["output_name"], "xgb_sm_demo")
            self.assertTrue(args["spatial_validation"])

    def test_full_xgboost_workflow_registers_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service)
            context = self.context(service)
            intent = {"intent": "modeling", "confidence": 0.9, "secondary_intents": []}
            plan = build_task_plan(FULL_PROMPT, intent, context, manager=service.manager)

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            artifact_types = {artifact["type"] for artifact in result["final_artifacts"]}
            self.assertIn("dataset", artifact_types)
            self.assertIn("residuals", artifact_types)
            self.assertIn("feature_importance", artifact_types)
            self.assertIn("metrics", artifact_types)
            self.assertIn("model", artifact_types)
            self.assertIn("image", artifact_types)
            image_artifacts = [artifact for artifact in result["final_artifacts"] if artifact["type"] == "image"]
            self.assertGreaterEqual(len(image_artifacts), 5)
            for artifact in image_artifacts:
                self.assertEqual(artifact.get("mime_type"), "image/png")
                self.assertTrue(artifact.get("preview_available"))
                self.assertTrue(Path(artifact["path"]).exists())
            train_step = next(step for step in result["steps"] if step["step_id"] == "train_model")
            outputs = train_step["tool_result"]["outputs"]
            self.assertGreaterEqual(len(outputs["images"]), 5)
            self.assertEqual(outputs["skipped_images"], [])
            self.assertTrue(train_step["tool_result"]["diagnostics"]["spatial_diagnostics"])

    def test_service_response_includes_xgboost_visualization_images(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service, name="demo_xgboost_soil_moisture")

            with mock.patch("core.service.build_llm_task_plan", side_effect=self.active_rule_plan(service)):
                with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                    response = service.ask(USER_SPACED_PROMPT)

            self.assertEqual(response["mode"], "validated_workflow_executor")
            self.assertGreaterEqual(len(response["images"]), 5)
            self.assertTrue(any(str(path).endswith("_feature_importance.png") for path in response["images"]))

    def test_service_message_meta_exposes_current_xgboost_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service, name="demo_xgboost_soil_moisture")

            with mock.patch("core.service.build_llm_task_plan", side_effect=self.active_rule_plan(service)):
                with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                    response = service.ask(USER_SPACED_PROMPT)
            assistant = service.current_messages()[-1]
            meta = assistant.get("meta") or {}

            self.assertEqual(response["mode"], "validated_workflow_executor")
            self.assertGreaterEqual(len(meta.get("artifacts") or []), 8)
            self.assertTrue(any(str(item.get("path") or "").endswith("_feature_importance.png") for item in meta["artifacts"]))

    def test_xgboost_reply_uses_user_facing_result_without_internal_paths(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service, name="demo_xgboost_soil_moisture")

            with mock.patch("core.service.build_llm_task_plan", side_effect=self.active_rule_plan(service)):
                with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                    response = service.ask(USER_SPACED_PROMPT)
            reply = response["reply"]
            presentation_result = response.get("presentation_result") or {}

            self.assertEqual(response["mode"], "validated_workflow_executor")
            self.assertNotIn("workspace\\users", reply)
            self.assertNotIn("workspace/users", reply)
            self.assertNotIn("input:", reply)
            self.assertNotIn("output:", reply)
            self.assertNotIn("diagnostics", reply)
            self.assertNotIn("裁剪或处理结果", reply)
            self.assertIn("model_result_id", reply)
            self.assertIn("xgb_sm_demo_predictions.csv", reply)
            self.assertIn("feature_importance", reply)
            self.assertEqual(presentation_result.get("status"), "succeeded")
            self.assertTrue(presentation_result.get("concise_summary"))
            artifact_titles = " ".join(str(item.get("title") or item.get("name") or "") for item in presentation_result.get("artifact_refs") or [])
            self.assertIn("xgb_sm_demo_predictions.csv", artifact_titles)
            self.assertIn("feature_importance", artifact_titles)

    def test_full_xgboost_workflow_registers_standard_user_facing_outputs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service, name="demo_xgboost_soil_moisture")
            context = self.context(service, name="demo_xgboost_soil_moisture")
            intent = {"intent": "modeling", "confidence": 0.9, "secondary_intents": []}
            plan = build_task_plan(USER_SPACED_PROMPT, intent, context, manager=service.manager)

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])
            names = {Path(str(artifact.get("path") or "")).name for artifact in result["final_artifacts"]}

            self.assertTrue(execution["ok"])
            self.assertIn("xgb_sm_demo_predictions.csv", names)
            self.assertIn("xgb_sm_demo_feature_importance.csv", names)
            self.assertIn("xgb_sm_demo_metrics.json", names)
            self.assertIn("xgb_sm_demo_report.md", names)

    def test_xgboost_request_with_gcp_runs_uncertainty_step(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service, name="demo_xgboost_soil_moisture")
            context = self.context(service, name="demo_xgboost_soil_moisture")
            intent = classify_user_intent(XGBOOST_WITH_GCP_PROMPT, {"active_dataset": "demo_xgboost_soil_moisture"}, {"dataset_count": 1}, enable_llm=False)

            plan = build_task_plan(XGBOOST_WITH_GCP_PROMPT, intent, context, manager=service.manager)

            self.assertIn("run_gcp", [step.get("step_id") for step in plan["workflow_plan"]])
            gcp_step = next(step for step in plan["workflow_plan"] if step.get("step_id") == "run_gcp")
            self.assertEqual(gcp_step["validated_tool_args"]["calibration_dataset"], "$steps.train_model.outputs.result_dataset")
            self.assertEqual(gcp_step["validated_tool_args"]["observed_col"], "$steps.train_model.outputs.target_column")
            self.assertEqual(gcp_step["validated_tool_args"]["predicted_cols"], "$steps.train_model.outputs.cv_prediction_column")

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            run_gcp = next(step for step in result["steps"] if step["step_id"] == "run_gcp")
            self.assertEqual(run_gcp["tool_result"]["tool_name"], "geographical_conformal_prediction")
            artifact_types = {artifact["type"] for artifact in run_gcp["tool_result"]["artifacts"]}
            self.assertIn("report", artifact_types)
            self.assertIn("image", artifact_types)
            self.assertIn("gcp_metrics_json", artifact_types)

    def test_spatial_block_validation_requires_coordinates_for_table(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_demo(service, name="soil_no_coords", include_coords=False)
            context = self.context(service, name="soil_no_coords", include_coords=False)
            prompt = FULL_PROMPT.replace("demo_xgboost_soil_moisture.csv", "soil_no_coords").replace(",lon,lat", "")
            intent = {"intent": "modeling", "confidence": 0.9, "secondary_intents": []}
            plan = build_task_plan(prompt, intent, context, manager=service.manager)

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertFalse(execution["ok"])
            train_step = next(step for step in result["steps"] if step["step_id"] == "train_model")
            self.assertEqual(train_step["tool_result"]["error_code"], "SPATIAL_COORDINATES_REQUIRED")


if __name__ == "__main__":
    unittest.main()
