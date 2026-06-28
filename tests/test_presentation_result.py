from __future__ import annotations

import json
import unittest
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.presentation_result import (
    PresentationResult,
    build_presentation_bundle,
    build_presentation_bundle_from_raw_execution,
    build_presentation_result,
)


pytestmark = pytest.mark.slow


class PresentationResultTests(unittest.TestCase):
    def normalized_results(self):
        return [
            {
                "status": "succeeded",
                "step_id": "train",
                "tool_name": "train_xgboost_fusion_model",
                "outputs": {"metrics": {"RMSE": 0.12, "MAE": 0.08}, "model_result_id": "m1"},
                "artifacts": [
                    {"artifact_id": "a_metrics", "title": "metrics.csv", "type": "metrics"},
                    {"artifact_id": "a_plot", "title": "importance.png", "type": "image"},
                    {"title": "not registered", "path": "C:/secret/workspace/users/u1/raw.csv"},
                ],
                "map_layers": [{"layer_id": "layer_prediction", "name": "prediction"}],
                "tables": [{"table_id": "table_metrics", "title": "metrics"}],
                "images": [{"artifact_id": "a_plot"}],
                "warnings": ["minor warning"],
                "errors": [],
                "next_actions": ["review residuals"],
                "input_asset_ids": ["stations"],
                "diagnostics": {"runtime_ms": 5},
            }
        ]

    def test_schema_rejects_unknown_fields_and_requires_real_refs(self) -> None:
        with self.assertRaises(ValidationError):
            PresentationResult.model_validate(
                {
                    "status": "succeeded",
                    "concise_summary": "ok",
                    "executed_steps": [],
                    "data_sources": [],
                    "result_highlights": [],
                    "artifact_refs": [],
                    "map_layer_refs": [],
                    "table_refs": [],
                    "image_refs": [],
                    "warnings": [],
                    "error_summary": "",
                    "next_action_suggestions": [],
                    "clarification_question": "",
                    "download_url": "/fake",
                }
            )

    def test_success_uses_only_canonical_facts_and_real_artifact_ids(self) -> None:
        result = build_presentation_result(
            task_goal="soil moisture xgboost",
            task_plan_summary={"primary_goal": "soil_moisture_xgboost_regression"},
            coordinator_status="succeeded",
            normalized_results=self.normalized_results(),
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual([item["artifact_id"] for item in result["artifact_refs"]], ["a_metrics", "a_plot"])
        self.assertEqual([item["artifact_id"] for item in result["image_refs"]], ["a_plot"])
        self.assertEqual(result["image_refs"][0]["source_step_id"], "train")
        self.assertIn("RMSE=0.12", " ".join(result["result_highlights"]))
        rendered = str(result)
        self.assertNotIn("C:/secret", rendered)
        self.assertNotIn("download_url", rendered)

    def test_xgboost_raster_prediction_result_is_map_ready_without_path_leaks(self) -> None:
        bundle = build_presentation_bundle(
            task_goal="use XGBoost to predict the full Shandian basin soil moisture raster map for 2019-07-15",
            task_plan_summary={"primary_goal": "full_basin_xgboost_soil_moisture_prediction_map"},
            coordinator_status="succeeded",
            normalized_results=[
                {
                    "status": "succeeded",
                    "step_id": "predict",
                    "tool_name": "predict_xgboost_raster_map",
                    "outputs": {
                        "result_dataset": "shandian_basin_soil_moisture_xgb_20190715",
                        "path": "E:/agent/workspace/derived/shandian.tif",
                        "preview_path": "E:/agent/workspace/plots/shandian.png",
                        "summary_path": "E:/agent/workspace/derived/shandian_summary.json",
                        "target": "soil_moisture_mean",
                        "representative_date": "2019-07-15",
                        "valid_prediction_pixels": 14049927,
                    },
                    "artifacts": [
                        {
                            "artifact_id": "artifact_prediction_raster",
                            "path": "E:/agent/workspace/derived/shandian.tif",
                            "title": "shandian.tif",
                            "type": "raster",
                        },
                        {
                            "artifact_id": "artifact_prediction_preview",
                            "path": "E:/agent/workspace/plots/shandian.png",
                            "title": "shandian.png",
                            "type": "png",
                        },
                        {
                            "artifact_id": "artifact_prediction_summary",
                            "path": "E:/agent/workspace/derived/shandian_summary.json",
                            "title": "shandian_summary.json",
                            "type": "summary",
                        },
                    ],
                    "map_layers": [
                        {
                            "layer_id": "dataset_shandian_basin_soil_moisture_xgb_20190715",
                            "name": "shandian_basin_soil_moisture_xgb_20190715",
                            "type": "raster",
                        }
                    ],
                    "images": [
                        {
                            "path": "E:/agent/workspace/plots/shandian.png",
                            "title": "shandian.png",
                        }
                    ],
                    "warnings": [
                        "Representative date only enters time features; if LST/NDVI are not same-day products, treat this as a covariate snapshot prediction map."
                    ],
                    "errors": [],
                    "next_actions": ["Inspect the prediction raster layer and NoData mask on the map."],
                    "diagnostics": {"output_tif": "E:/agent/workspace/derived/shandian.tif"},
                }
            ],
        )

        presentation = bundle["presentation_result"]
        reply = bundle["reply"]
        rendered = json.dumps(bundle, ensure_ascii=False)

        self.assertEqual(presentation["status"], "succeeded")
        self.assertEqual(
            [item["artifact_id"] for item in presentation["artifact_refs"]],
            ["artifact_prediction_raster", "artifact_prediction_preview", "artifact_prediction_summary"],
        )
        self.assertEqual(
            [item["layer_id"] for item in presentation["map_layer_refs"]],
            ["dataset_shandian_basin_soil_moisture_xgb_20190715"],
        )
        self.assertEqual([item["artifact_id"] for item in presentation["image_refs"]], ["artifact_prediction_preview"])
        self.assertIn("representative_date=2019-07-15", presentation["result_highlights"])
        self.assertIn("valid_prediction_pixels=14049927", presentation["result_highlights"])
        self.assertIn("target=soil_moisture_mean", presentation["result_highlights"])
        self.assertIn("shandian.tif", reply)
        self.assertNotIn("E:/agent", rendered)
        self.assertNotIn("workspace/derived", rendered)

    def test_failure_waiting_and_blocked_have_status_specific_messages(self) -> None:
        failed = build_presentation_result(
            task_goal="clip raster",
            task_plan_summary={},
            coordinator_status="failed",
            normalized_results=[
                {
                    "status": "failed",
                    "step_id": "clip",
                    "tool_name": "clip_raster_by_vector",
                    "outputs": {},
                    "artifacts": [],
                    "warnings": [],
                    "errors": [{"code": "CRS_MISMATCH", "message": "CRS mismatch"}],
                    "next_actions": ["reproject raster"],
                    "input_asset_ids": ["dem", "boundary"],
                }
            ],
        )
        self.assertEqual(failed["status"], "failed")
        self.assertIn("clip", failed["error_summary"])
        self.assertIn("CRS_MISMATCH", failed["error_summary"])
        self.assertFalse(failed["artifact_refs"])

        awaiting = build_presentation_result(
            task_goal="download DEM",
            task_plan_summary={},
            coordinator_status="awaiting_confirmation",
            normalized_results=[
                {
                    "status": "awaiting_confirmation",
                    "step_id": "download",
                    "tool_name": "run_gscloud_dem_capture_job",
                    "outputs": {},
                    "artifacts": [],
                    "warnings": [],
                    "errors": [],
                    "next_actions": ["Log in to GSCloud"],
                    "input_asset_ids": [],
                }
            ],
        )
        self.assertEqual(awaiting["status"], "awaiting_confirmation")
        self.assertEqual(awaiting["clarification_question"], "Log in to GSCloud")

    def test_failed_canonical_step_overrides_successful_coordinator_status(self) -> None:
        failed = build_presentation_result(
            task_goal="dem slope",
            task_plan_summary={"primary_goal": "dem_slope_aspect", "response_language": "zh-CN"},
            coordinator_status="succeeded",
            normalized_results=[
                {
                    "status": "failed",
                    "step_id": "terrain",
                    "tool_name": "dem_terrain_derivatives",
                    "outputs": {},
                    "artifacts": [],
                    "warnings": [],
                    "errors": [
                        {
                            "code": "DEM_PROJECTED_CRS_REQUIRED",
                            "message": "不能直接对地理坐标 CRS 的 DEM 计算平面坡度。",
                        }
                    ],
                    "next_actions": ["先执行 raster_reproject 到合适的投影 CRS，再计算坡度坡向。"],
                    "input_asset_ids": ["dem_geo"],
                }
            ],
            response_language="zh-CN",
        )
        self.assertEqual(failed["status"], "failed")
        self.assertFalse(failed["artifact_refs"])
        self.assertIn("DEM_PROJECTED_CRS_REQUIRED", failed["error_summary"])

    def test_old_result_structures_are_ignored(self) -> None:
        result = build_presentation_result(
            task_goal="bad old input",
            task_plan_summary={},
            coordinator_status="succeeded",
            normalized_results=[],
            legacy_payload={
                "workflow_result": {"steps": [{"tool_result": {"artifacts": [{"artifact_id": "fake"}]}}]},
                "download_tool_result": {"artifacts": [{"artifact_id": "fake_download"}]},
                "tool_execution": {"tool_results": [{"outputs": {"RMSE": 99}}]},
            },
        )
        self.assertEqual(result["artifact_refs"], [])
        self.assertEqual(result["result_highlights"], [])

    def test_execution_summary_contains_only_public_canonical_fields(self) -> None:
        from core.presentation_result import build_execution_summary

        presentation = build_presentation_result(
            task_goal="download DEM",
            task_plan_summary={"primary_goal": "download_dem"},
            coordinator_status="awaiting_confirmation",
            normalized_results=[
                {
                    "status": "awaiting_confirmation",
                    "step_id": "download",
                    "tool_name": "run_gscloud_dem_capture_job",
                    "outputs": {"job_id": "job_1", "path": "C:/secret/workspace/users/u1/out.zip"},
                    "artifacts": [{"artifact_id": "a_dem", "title": "dem.zip", "type": "archive"}],
                    "warnings": [],
                    "errors": [],
                    "next_actions": ["Log in to GSCloud"],
                    "diagnostics": {"traceback": "Traceback secret"},
                }
            ],
        )

        summary = build_execution_summary(presentation)
        rendered = str(summary)

        self.assertEqual(summary["schema_version"], "execution-summary/v1")
        self.assertEqual(summary["status"], "awaiting_confirmation")
        self.assertEqual(summary["artifact_count"], 1)
        self.assertNotIn("C:/secret", rendered)
        self.assertNotIn("Traceback", rendered)
        self.assertNotIn("job_1", rendered)

    def test_raw_workflow_and_tool_outputs_are_adapted_to_presentation_bundle(self) -> None:
        plan = {
            "plan_id": "plan_1",
            "workflow_plan": [
                {"step_id": "raster", "tool_name": "raster_basic_stats", "validated_tool_args": {}},
                {"step_id": "map", "tool_name": "plot_dataset", "validated_tool_args": {}},
            ],
        }
        raw = {
            "workflow_result": {
                "steps": [
                    {
                        "step_id": "raster",
                        "tool_name": "raster_basic_stats",
                        "tool_result": {
                            "status": "succeeded",
                            "tool_name": "raster_basic_stats",
                            "step_id": "raster",
                            "outputs": {"result_dataset": "dem_stats"},
                            "artifacts": [{"artifact_id": "a_stats", "title": "stats.csv", "type": "table"}],
                        },
                    },
                    {
                        "step_id": "map",
                        "tool_name": "plot_dataset",
                        "tool_result": {
                            "status": "failed",
                            "tool_name": "plot_dataset",
                            "step_id": "map",
                            "outputs": {},
                            "errors": [{"code": "FIELD_NOT_FOUND", "message": "field not found"}],
                        },
                    },
                ]
            },
            "tool_results": [{"step_id": "unexpected", "tool_name": "fake", "outputs": {"RMSE": 99}}],
        }

        bundle = build_presentation_bundle_from_raw_execution(
            plan=plan,
            raw_results=raw,
            task_goal="raster map",
            task_plan_summary={"primary_goal": "raster_map"},
            coordinator_status="failed",
        )

        self.assertEqual(bundle["presentation_result"]["status"], "failed")
        self.assertEqual([item["step_id"] for item in bundle["normalized_results"]], ["raster", "map"])
        self.assertEqual(bundle["presentation_result"]["artifact_refs"][0]["artifact_id"], "a_stats")
        self.assertIn("FIELD_NOT_FOUND", bundle["presentation_result"]["error_summary"])
        rendered = json.dumps(bundle, ensure_ascii=False)
        self.assertNotIn("unexpected", rendered)
        self.assertNotIn("RMSE=99", rendered)

    def test_llm_presentation_cannot_forge_artifact_or_layer_refs(self) -> None:
        class ForgingClient:
            def with_structured_output(self, schema):
                class Structured:
                    def invoke(self, payload):
                        return {
                            "status": "succeeded",
                            "concise_summary": "LLM summary",
                            "executed_steps": [{"step_id": "train", "tool_name": "xgb", "status": "succeeded"}],
                            "data_sources": [],
                            "result_highlights": ["RMSE=0.12", "invented metric"],
                            "artifact_refs": [
                                {"artifact_id": "a_metrics", "title": "metrics.csv", "type": "metrics"},
                                {"artifact_id": "fake_artifact", "title": "fake.zip", "type": "archive"},
                            ],
                            "map_layer_refs": [{"layer_id": "fake_layer", "name": "fake"}],
                            "table_refs": [{"table_id": "table_metrics", "title": "metrics"}],
                            "image_refs": [{"artifact_id": "fake_artifact", "title": "fake image"}],
                            "warnings": [],
                            "error_summary": "",
                            "next_action_suggestions": [],
                            "clarification_question": "",
                            "confidence": 0.9,
                        }

                return Structured()

        bundle = build_presentation_bundle_from_raw_execution(
            plan={"workflow_plan": [{"step_id": "train", "tool_name": "xgb"}]},
            raw_results={"tool_results": self.normalized_results()},
            task_goal="soil moisture xgboost",
            task_plan_summary={"primary_goal": "soil_moisture_xgboost_regression"},
            coordinator_status="succeeded",
            llm_client=ForgingClient(),
        )

        self.assertEqual(bundle["presentation_source"], "llm")
        self.assertEqual([item["artifact_id"] for item in bundle["presentation_result"]["artifact_refs"]], ["a_metrics"])
        self.assertEqual(bundle["presentation_result"]["map_layer_refs"], [])
        self.assertEqual([item["table_id"] for item in bundle["presentation_result"]["table_refs"]], ["table_metrics"])
        self.assertEqual(bundle["presentation_result"]["image_refs"], [])

    def test_result_interpreter_source_is_canonical_only(self) -> None:
        source = Path("core/result_interpreter.py").read_text(encoding="utf-8")

        forbidden_tokens = [
            "parse_workflow_result",
            "interpret_workflow_result",
            "build_user_facing_result_from_workflow",
            "build_user_facing_result_from_tool_results",
            "workflow_result.get(\"steps\")",
            "outputs.get(\"tool_results\")",
            "download_tool_result",
            "scene_job",
            "tile_job",
        ]
        for token in forbidden_tokens:
            self.assertNotIn(token, source)

    def test_display_fixtures_cover_core_result_types_success_and_failure(self) -> None:
        fixtures = {
            "download": (
                {"status": "succeeded", "step_id": "download", "tool_name": "download_job", "artifacts": [{"artifact_id": "a_download", "title": "dem.zip", "type": "archive"}]},
                {"status": "awaiting_confirmation", "step_id": "download", "tool_name": "download_job", "errors": [{"code": "LOGIN_REQUIRED", "message": "login required"}], "next_actions": ["Refresh login"]},
            ),
            "raster": (
                {"status": "succeeded", "step_id": "raster", "tool_name": "raster_basic_stats", "outputs": {"result_dataset": "dem_stats"}, "artifacts": [{"artifact_id": "a_raster", "title": "stats.csv", "type": "table"}]},
                {"status": "failed", "step_id": "raster", "tool_name": "clip_raster_by_vector", "errors": [{"code": "CRS_MISMATCH", "message": "CRS mismatch"}]},
            ),
            "vector": (
                {"status": "succeeded", "step_id": "vector", "tool_name": "vector_clip_by_vector", "outputs": {"result_dataset": "clip"}, "artifacts": [{"artifact_id": "a_vector", "title": "clip.zip", "type": "vector"}]},
                {"status": "failed", "step_id": "vector", "tool_name": "vector_clip_by_vector", "errors": [{"code": "GEOMETRY_EMPTY", "message": "empty result"}]},
            ),
            "table_to_points": (
                {"status": "succeeded", "step_id": "points", "tool_name": "table_to_points", "outputs": {"result_dataset": "stations_points"}, "artifacts": [{"artifact_id": "a_points", "title": "points.geojson", "type": "vector"}]},
                {"status": "failed", "step_id": "points", "tool_name": "table_to_points", "errors": [{"code": "FIELD_NOT_FOUND", "message": "lat missing"}]},
            ),
            "mapping": (
                {"status": "succeeded", "step_id": "map", "tool_name": "plot_dataset", "artifacts": [{"artifact_id": "a_map", "title": "map.png", "type": "map"}], "images": [{"artifact_id": "a_map"}]},
                {"status": "failed", "step_id": "map", "tool_name": "plot_dataset", "errors": [{"code": "FIELD_NOT_FOUND", "message": "style field missing"}]},
            ),
            "xgboost": (
                {"status": "succeeded", "step_id": "xgb", "tool_name": "train_xgboost_fusion_model", "outputs": {"metrics": {"RMSE": 0.2}, "model_result_id": "m_xgb"}, "artifacts": [{"artifact_id": "a_xgb", "title": "metrics.csv", "type": "metrics"}]},
                {"status": "failed", "step_id": "xgb", "tool_name": "train_xgboost_fusion_model", "errors": [{"code": "TARGET_FIELD_MISSING", "message": "target missing"}]},
            ),
            "gcp": (
                {"status": "succeeded", "step_id": "gcp", "tool_name": "evaluate_gcp_uncertainty", "outputs": {"metrics": {"PICP": 0.91, "MPIW": 0.4}}, "artifacts": [{"artifact_id": "a_gcp", "title": "gcp.csv", "type": "metrics"}]},
                {"status": "failed", "step_id": "gcp", "tool_name": "evaluate_gcp_uncertainty", "errors": [{"code": "PREDICTION_FIELD_MISSING", "message": "prediction missing"}]},
            ),
        }

        for name, (success, failure) in fixtures.items():
            with self.subTest(result_type=name, status="success"):
                bundle = build_presentation_bundle(
                    task_goal=name,
                    task_plan_summary={"primary_goal": name},
                    coordinator_status="succeeded",
                    normalized_results=[success],
                )
                self.assertEqual(bundle["presentation_result"]["status"], "succeeded")
                self.assertTrue(bundle["presentation_result"]["executed_steps"])
                self.assertNotIn("workspace", json.dumps(bundle, ensure_ascii=False))
            with self.subTest(result_type=name, status="failure"):
                bundle = build_presentation_bundle(
                    task_goal=name,
                    task_plan_summary={"primary_goal": name},
                    coordinator_status=str(failure["status"]),
                    normalized_results=[failure],
                )
                self.assertIn(bundle["presentation_result"]["status"], {"failed", "awaiting_confirmation"})
                self.assertTrue(bundle["presentation_result"]["error_summary"] or bundle["presentation_result"]["clarification_question"])


if __name__ == "__main__":
    unittest.main()
