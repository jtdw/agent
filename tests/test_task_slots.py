from __future__ import annotations

import unittest

from core.task_planner import build_task_plan
from core.task_slots import extract_task_slots


def _intent(intent: str, confidence: float = 0.86) -> dict:
    return {"intent": intent, "confidence": confidence, "secondary_intents": []}


class TaskSlotsTests(unittest.TestCase):
    def test_map_request_extracts_map_type_and_target_concept(self) -> None:
        slots = extract_task_slots(
            "plot population density map",
            _intent("map_generation"),
            {"active_dataset": "county"},
            {"dataset_count": 1, "available_fields": ["county", "pop_density", "geometry"]},
        )

        self.assertEqual(slots["task_type"], "map_generation")
        self.assertEqual(slots["dataset_id"], "county")
        self.assertEqual(slots["map_type"], "thematic")
        self.assertEqual(slots["target_concept"], "人口密度")
        self.assertEqual(slots["target_field"], "pop_density")

    def test_modeling_request_extracts_target_variable_and_feature_fields(self) -> None:
        slots = extract_task_slots(
            "use rainfall and elevation to predict NDVI",
            _intent("modeling"),
            {"active_dataset": "remote_sensing"},
            {
                "dataset_count": 1,
                "available_fields": ["rainfall", "elevation", "ndvi", "station_id"],
                "numeric_fields": ["rainfall", "elevation", "ndvi"],
            },
        )

        self.assertEqual(slots["target_variable"], "ndvi")
        self.assertEqual(slots["feature_fields"], ["rainfall", "elevation"])
        self.assertNotIn("station_id", slots["feature_fields"])

    def test_followup_request_uses_referenced_artifact(self) -> None:
        artifact = {"type": "map", "path": "plots/pop_density.png", "artifact_id": "map_001"}
        slots = extract_task_slots(
            "analyze that map",
            _intent("result_analysis"),
            {"referenced_object": artifact},
            {"dataset_count": 1},
        )

        self.assertEqual(slots["referenced_artifact"], artifact)
        self.assertEqual(slots["missing_inputs"], [])

    def test_planner_does_not_generate_tool_args_for_missing_field(self) -> None:
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "county", "type": "vector"},
            "available_fields": ["county", "population", "geometry"],
            "numeric_fields": ["population"],
        }

        plan = build_task_plan("plot GDP map", _intent("map_generation"), context)

        self.assertTrue(plan["should_ask_clarification"])
        self.assertEqual(plan["validated_tool_args"], {})
        self.assertIn("map_field", plan["missing_inputs"])

    def test_planner_keeps_candidate_fields_when_field_is_ambiguous(self) -> None:
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "county", "type": "vector"},
            "available_fields": ["population", "pop_total", "geometry"],
            "numeric_fields": ["population", "pop_total"],
        }

        plan = build_task_plan("plot population map", _intent("map_generation"), context)

        self.assertTrue(plan["should_ask_clarification"])
        self.assertEqual(plan["validated_tool_args"], {})
        self.assertIn("candidate_fields", plan["slots"])
        self.assertGreaterEqual(len(plan["slots"]["candidate_fields"]), 2)

    def test_planner_generates_validated_plot_args_when_inputs_are_sufficient(self) -> None:
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "county", "type": "vector"},
            "available_fields": ["county", "pop_density", "geometry"],
            "numeric_fields": ["pop_density"],
        }

        plan = build_task_plan("plot population density map", _intent("map_generation"), context)

        self.assertFalse(plan["should_ask_clarification"])
        self.assertEqual(plan["validated_tool_args"]["plot_dataset"]["dataset_name"], "county")
        self.assertEqual(plan["validated_tool_args"]["plot_dataset"]["column"], "pop_density")
        self.assertIn("plot_dataset", plan["tool_plan"][0]["tool_name"])

    def test_planner_generates_model_args_from_target_and_feature_slots(self) -> None:
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "remote_sensing", "type": "table"},
            "available_fields": ["rainfall", "elevation", "ndvi"],
            "numeric_fields": ["rainfall", "elevation", "ndvi"],
        }

        plan = build_task_plan("use rainfall and elevation to predict NDVI", _intent("modeling"), context)

        self.assertFalse(plan["should_ask_clarification"])
        self.assertEqual(plan["validated_tool_args"]["train_xgboost_fusion_model"]["target_col"], "ndvi")
        self.assertEqual(plan["validated_tool_args"]["train_xgboost_fusion_model"]["feature_cols"], "rainfall,elevation")

    def test_planner_preserves_explicit_xgboost_training_options(self) -> None:
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "soil_samples", "type": "vector"},
            "available_fields": [
                "soil_moisture",
                "elevation",
                "slope",
                "precip_7d",
                "ndvi",
                "lst",
                "lon",
                "lat",
                "date",
            ],
            "numeric_fields": [
                "soil_moisture",
                "elevation",
                "slope",
                "precip_7d",
                "ndvi",
                "lst",
                "lon",
                "lat",
            ],
        }
        prompt = (
            "使用当前上传的数据训练 XGBoost 土壤水分模型。"
            "目标列是 soil_moisture。"
            "特征列使用 elevation,slope,precip_7d,ndvi,lst,lon,lat。"
            "时间列是 date。"
            "输出名称为 xgb_sm_demo。"
            "开启空间分块验证，生成预测结果、残差、特征重要性、精度指标和模型文件。"
        )

        plan = build_task_plan(prompt, _intent("modeling"), context)

        self.assertFalse(plan["should_ask_clarification"])
        args = plan["validated_tool_args"]["train_xgboost_fusion_model"]
        self.assertEqual(args["target_col"], "soil_moisture")
        self.assertEqual(args["feature_cols"], "elevation,slope,precip_7d,ndvi,lst,lon,lat")
        self.assertEqual(args["date_col"], "date")
        self.assertEqual(args["output_name"], "xgb_sm_demo")
        self.assertTrue(args["spatial_validation"])

    def test_planner_clarifies_regression_request_without_target_or_features(self) -> None:
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "soil", "type": "table"},
            "available_fields": ["station_id", "value"],
            "numeric_fields": ["value"],
        }

        plan = build_task_plan("build a regression model", _intent("modeling"), context)

        self.assertTrue(plan["should_ask_clarification"])
        self.assertEqual(plan["validated_tool_args"], {})
        self.assertIn("target column", plan["missing_inputs"])

    def test_planner_resolves_study_area_boundary_without_referenced_object(self) -> None:
        context = {
            "workspace": {"dataset_count": 2},
            "active_dataset": {"name": "county_points", "type": "vector"},
            "available_fields": ["pop_density", "geometry"],
            "numeric_fields": ["pop_density"],
            "available_datasets": [
                {"name": "county_points", "type": "vector", "path": "county_points.geojson"},
                {"name": "study_area", "type": "vector", "path": "study_area.geojson"},
            ],
        }

        plan = build_task_plan("把这个 shp 裁剪到研究区", _intent("data_processing"), context)

        self.assertFalse(plan["should_ask_clarification"])
        self.assertEqual(plan["resolved_objects"]["clip_boundary"]["name"], "study_area")
        self.assertEqual(plan["validated_tool_args"]["vector_clip_by_vector"]["dataset_name"], "county_points")
        self.assertEqual(plan["validated_tool_args"]["vector_clip_by_vector"]["clip_name"], "study_area")


    def test_real_chinese_clip_request_extracts_clip_operation_and_boundary(self) -> None:
        slots = extract_task_slots(
            "把这个 shp 裁剪到研究区",
            _intent("data_processing"),
            {"active_dataset": "county_points"},
            {
                "dataset_count": 2,
                "available_fields": ["pop_density", "geometry"],
                "available_datasets": [
                    {"name": "county_points", "type": "vector"},
                    {"name": "study_area", "type": "vector"},
                ],
            },
        )

        self.assertEqual(slots["spatial_operation"], "clip")
        self.assertNotIn("clip layer", slots["missing_inputs"])

    def test_real_chinese_planner_resolves_clip_and_map_workflow_inputs(self) -> None:
        context = {
            "workspace": {"dataset_count": 2},
            "active_dataset": {"name": "county_points", "type": "vector"},
            "available_fields": ["pop_density", "geometry"],
            "numeric_fields": ["pop_density"],
            "available_datasets": [
                {"name": "county_points", "type": "vector", "path": "county_points.geojson"},
                {"name": "study_area", "type": "vector", "path": "study_area.geojson"},
            ],
        }

        plan = build_task_plan("把这个 shp 裁剪到研究区，然后画人口密度图", _intent("data_processing"), context)

        self.assertFalse(plan["should_ask_clarification"])
        self.assertEqual(plan["validated_tool_args"]["vector_clip_by_vector"]["clip_name"], "study_area")
        generate_map = [step for step in plan["workflow_plan"] if step.get("step_id") == "generate_map"][0]
        self.assertEqual(generate_map["validated_tool_args"]["column"], "pop_density")
        self.assertEqual(generate_map["validated_tool_args"]["dataset_name"], "$steps.clip_vector.outputs.result_dataset")


if __name__ == "__main__":
    unittest.main()
