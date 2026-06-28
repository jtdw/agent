from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box

from core.config import Settings
from core.conversation_intent import classify_user_intent
from core.gis_tools import build_tools
from core.result_interpreter import interpret_result
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.tool_contracts import parse_tool_result


class ToolContractTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def tool_map(self, service: GISWorkspaceService):
        return {tool.name: tool for tool in build_tools(service.manager)}

    def write_test_raster(self, path: Path) -> Path:
        transform = from_origin(-0.5, 2.5, 1, 1)
        data = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype="float32")
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype=data.dtype,
            crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)
        return path

    def test_map_request_without_uploaded_data_plans_clarification_before_tools(self) -> None:
        context = {"workspace": {"dataset_count": 0}, "active_dataset": None}
        intent = classify_user_intent("画一张地图", {}, {"dataset_count": 0}, enable_llm=False)

        plan = build_task_plan("画一张地图", intent, context)

        self.assertTrue(plan["should_ask_clarification"])
        self.assertIn("dataset", plan["missing_inputs"])
        self.assertEqual(plan["recommended_tools"], [])

    def test_vector_without_crs_returns_structured_precondition_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            gdf = gpd.GeoDataFrame(
                {"population": [10, 20, 30], "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)]},
                crs=None,
            )
            service.manager.put_vector("missing_crs_points", gdf)
            tools = self.tool_map(service)

            raw = tools["plot_dataset"].invoke({"dataset_name": "missing_crs_points", "column": "population"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "CRS_REQUIRED")
            self.assertIn("next_actions", result)

    def test_plot_missing_population_field_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            gdf = gpd.GeoDataFrame(
                {"density": [1.2, 2.5], "geometry": [Point(0, 0), Point(1, 1)]},
                crs="EPSG:4326",
            )
            service.manager.put_vector("population_layer", gdf)
            tools = self.tool_map(service)

            raw = tools["plot_dataset"].invoke({"dataset_name": "population_layer", "column": "population"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "FIELD_NOT_FOUND")
            self.assertIn("density", str(result["diagnostics"]))
            self.assertTrue(result["next_actions"])

    def test_planner_validated_plot_args_can_invoke_plot_tool(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            gdf = gpd.GeoDataFrame(
                {"pop_density": [10.0, 20.0], "geometry": [Point(0, 0), Point(1, 1)]},
                crs="EPSG:4326",
            )
            service.manager.put_vector("county", gdf)
            context = {
                "workspace": {"dataset_count": 1},
                "active_dataset": {"name": "county", "type": "vector"},
                "available_fields": ["pop_density", "geometry"],
                "numeric_fields": ["pop_density"],
            }
            intent = {"intent": "map_generation", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("plot population density map", intent, context, manager=service.manager)
            raw = self.tool_map(service)["plot_dataset"].invoke(plan["validated_tool_args"]["plot_dataset"])
            result = parse_tool_result(raw)

            self.assertFalse(plan["should_ask_clarification"])
            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertTrue(result["artifacts"])

    def test_model_request_without_target_variable_asks_before_tool_call(self) -> None:
        context = {"workspace": {"dataset_count": 1}, "active_dataset": {"name": "soil_station", "type": "table"}}
        intent = classify_user_intent("帮我训练一个预测模型", {"active_dataset": "soil_station"}, {"dataset_count": 1}, enable_llm=False)

        plan = build_task_plan("帮我训练一个预测模型", intent, context)

        self.assertTrue(plan["should_ask_clarification"])
        self.assertIn("target column", plan["missing_inputs"])
        self.assertIn("tool_preconditions", plan)
        self.assertIn("train_xgboost_fusion_model", plan["tool_preconditions"])

    def test_xgboost_missing_target_returns_structured_error_before_dependency_errors(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("training_table", pd.DataFrame({"feature_a": list(range(25)), "feature_b": list(range(25, 50))}))
            tools = self.tool_map(service)

            raw = tools["train_xgboost_fusion_model"].invoke(
                {
                    "dataset_name": "training_table",
                    "target_col": "",
                    "feature_cols": "feature_a,feature_b",
                    "output_name": "xgb_out",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "TARGET_FIELD_MISSING")
            self.assertIn("目标变量", result["user_message"])

    def test_valid_vector_plot_returns_structured_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            gdf = gpd.GeoDataFrame(
                {"population": [10, 20, 30], "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)]},
                crs="EPSG:4326",
            )
            service.manager.put_vector("valid_points", gdf)
            tools = self.tool_map(service)

            raw = tools["plot_dataset"].invoke({"dataset_name": "valid_points", "column": "population", "output_name": "valid_plot"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "plot_dataset")
            self.assertEqual(result["artifacts"][0]["type"], "map")
            self.assertTrue(Path(result["artifacts"][0]["path"]).exists())

    def test_result_interpreter_explains_tool_result_failure_without_raw_exception_dependency(self) -> None:
        raw = (
            '{"ok": false, "tool_name": "plot_dataset", "task_id": "task_test", '
            '"inputs": {"dataset_name": "population_layer"}, "outputs": {}, "artifacts": [], '
            '"summary": "", "diagnostics": {"available_fields": ["density"]}, "warnings": [], '
            '"next_actions": ["请选择 density 字段，或先计算人口字段。"], '
            '"error_code": "FIELD_NOT_FOUND", "error_title": "字段不存在", '
            '"user_message": "未找到字段 population。", '
            '"technical_detail": "ValueError: population missing"}'
        )

        reply = interpret_result(
            "画人口密度图",
            {"intent": "map_generation"},
            {
                "task_type": "map_generation",
                "normalized_results": [
                    {
                        "status": "failed",
                        "step_id": "plot",
                        "tool_name": "plot_dataset",
                        "outputs": {},
                        "artifacts": [],
                        "errors": [{"code": "FIELD_NOT_FOUND", "message": "未找到字段 population。"}],
                        "next_actions": ["请选择 density 字段，或先计算人口字段。"],
                    }
                ],
            },
            "",
            {"active_dataset": {"name": "population_layer"}},
            {},
        )

        self.assertIn("FIELD_NOT_FOUND", reply)
        self.assertIn("未找到字段 population", reply)
        self.assertIn("请选择 density 字段", reply)
        self.assertNotIn("ValueError: population missing", reply.split("可能问题：", 1)[0])

    def test_table_to_points_missing_coordinate_field_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"lon": [0, 1], "value": [5, 6]}))
            tools = self.tool_map(service)

            raw = tools["table_to_points"].invoke(
                {"dataset_name": "stations", "x_col": "lon", "y_col": "lat", "crs": "EPSG:4326", "output_name": "station_points"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "FIELD_NOT_FOUND")
            self.assertIn("lat", str(result["diagnostics"]))

    def test_valid_table_to_points_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"lon": [0, 1], "lat": [0, 1], "value": [5, 6]}))
            tools = self.tool_map(service)

            raw = tools["table_to_points"].invoke(
                {"dataset_name": "stations", "x_col": "lon", "y_col": "lat", "crs": "EPSG:4326", "output_name": "station_points"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "table_to_points")
            self.assertEqual(result["outputs"]["feature_count"], 2)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_vector_clip_missing_crs_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            source = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs=None)
            clipper = gpd.GeoDataFrame({"id": [1], "geometry": [box(-1, -1, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("source_points", source)
            service.manager.put_vector("clip_boundary", clipper)
            tools = self.tool_map(service)

            raw = tools["vector_clip_by_vector"].invoke(
                {"dataset_name": "source_points", "clip_name": "clip_boundary", "output_name": "clipped_points"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "CRS_REQUIRED")

    def test_valid_vector_clip_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            source = gpd.GeoDataFrame(
                {"id": [1, 2], "geometry": [Point(0, 0), Point(5, 5)]},
                crs="EPSG:4326",
            )
            clipper = gpd.GeoDataFrame({"id": [1], "geometry": [box(-1, -1, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("source_points", source)
            service.manager.put_vector("clip_boundary", clipper)
            tools = self.tool_map(service)

            raw = tools["vector_clip_by_vector"].invoke(
                {"dataset_name": "source_points", "clip_name": "clip_boundary", "output_name": "clipped_points"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "vector_clip_by_vector")
            self.assertEqual(result["outputs"]["feature_count"], 1)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_vector_overlay_invalid_mode_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            tools = self.tool_map(service)

            raw = tools["vector_overlay"].invoke(
                {"dataset_name": "a", "overlay_name": "b", "how": "bad_mode", "output_name": "overlay_out"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "OVERLAY_MODE_UNSUPPORTED")
            self.assertTrue(result["next_actions"])

    def test_valid_vector_overlay_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = gpd.GeoDataFrame({"left_id": [1], "geometry": [box(0, 0, 2, 2)]}, crs="EPSG:4326")
            right = gpd.GeoDataFrame({"right_id": [1], "geometry": [box(1, 1, 3, 3)]}, crs="EPSG:4326")
            service.manager.put_vector("left_poly", left)
            service.manager.put_vector("right_poly", right)
            tools = self.tool_map(service)

            raw = tools["vector_overlay"].invoke(
                {"dataset_name": "left_poly", "overlay_name": "right_poly", "how": "intersection", "output_name": "overlay_out"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "vector_overlay")
            self.assertEqual(result["outputs"]["feature_count"], 1)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_vector_spatial_join_missing_crs_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            target = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs=None)
            join = gpd.GeoDataFrame({"zone": [1], "geometry": [box(-1, -1, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("target_points", target)
            service.manager.put_vector("join_poly", join)
            tools = self.tool_map(service)

            raw = tools["vector_spatial_join"].invoke(
                {"target_name": "target_points", "join_name": "join_poly", "predicate": "within", "output_name": "joined_out"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "CRS_REQUIRED")

    def test_valid_vector_spatial_join_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            target = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs="EPSG:4326")
            join = gpd.GeoDataFrame({"zone": [7], "geometry": [box(-1, -1, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("target_points", target)
            service.manager.put_vector("join_poly", join)
            tools = self.tool_map(service)

            raw = tools["vector_spatial_join"].invoke(
                {"target_name": "target_points", "join_name": "join_poly", "predicate": "within", "output_name": "joined_out"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "vector_spatial_join")
            self.assertEqual(result["outputs"]["feature_count"], 1)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_extract_raster_values_requires_point_geometry(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            polygons = gpd.GeoDataFrame({"id": [1], "geometry": [box(0, 0, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("polygon_layer", polygons)
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            tools = self.tool_map(service)

            raw = tools["extract_raster_values_to_points"].invoke(
                {"point_name": "polygon_layer", "raster_name": "test_raster", "output_name": "sampled", "field_name": "raster_val"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "GEOMETRY_TYPE_UNSUPPORTED")

    def test_valid_extract_raster_values_to_points_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            points = gpd.GeoDataFrame({"id": [1, 2], "geometry": [Point(0, 0), Point(1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("point_layer", points)
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            tools = self.tool_map(service)

            raw = tools["extract_raster_values_to_points"].invoke(
                {"point_name": "point_layer", "raster_name": "test_raster", "output_name": "sampled", "field_name": "raster_val"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "extract_raster_values_to_points")
            self.assertEqual(result["outputs"]["field_name"], "raster_val")
            self.assertEqual(result["outputs"]["feature_count"], 2)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_raster_zonal_stats_requires_polygon_geometry(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            points = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs="EPSG:4326")
            service.manager.put_vector("point_layer", points)
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            tools = self.tool_map(service)

            raw = tools["raster_zonal_stats"].invoke(
                {"raster_name": "test_raster", "polygon_name": "point_layer", "output_name": "zonal_out", "stat": "mean"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "GEOMETRY_TYPE_UNSUPPORTED")

    def test_valid_raster_zonal_stats_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            polygons = gpd.GeoDataFrame({"id": [1], "geometry": [box(-0.25, -0.25, 1.25, 1.25)]}, crs="EPSG:4326")
            service.manager.put_vector("polygon_layer", polygons)
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            tools = self.tool_map(service)

            raw = tools["raster_zonal_stats"].invoke(
                {"raster_name": "test_raster", "polygon_name": "polygon_layer", "output_name": "zonal_out", "stat": "mean"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "raster_zonal_stats")
            self.assertEqual(result["outputs"]["fields_added"], ["raster_mean"])
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_clip_raster_by_vector_missing_vector_crs_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            boundary = gpd.GeoDataFrame({"id": [1], "geometry": [box(0, 0, 1, 1)]}, crs=None)
            service.manager.put_vector("boundary", boundary)
            tools = self.tool_map(service)

            raw = tools["clip_raster_by_vector"].invoke(
                {"raster_name": "test_raster", "vector_name": "boundary", "output_name": "clipped_raster"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "CRS_REQUIRED")

    def test_valid_clip_raster_by_vector_returns_structured_raster_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            boundary = gpd.GeoDataFrame({"id": [1], "geometry": [box(0, 0, 1.2, 1.2)]}, crs="EPSG:4326")
            service.manager.put_vector("boundary", boundary)
            tools = self.tool_map(service)

            raw = tools["clip_raster_by_vector"].invoke(
                {"raster_name": "test_raster", "vector_name": "boundary", "output_name": "clipped_raster"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "clip_raster_by_vector")
            self.assertEqual(result["artifacts"][0]["type"], "raster")
            self.assertTrue(Path(result["artifacts"][0]["path"]).exists())

    def test_rf_missing_target_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("training_table", pd.DataFrame({"feature_a": list(range(25)), "feature_b": list(range(25, 50))}))
            tools = self.tool_map(service)

            raw = tools["train_rf_fusion_model"].invoke(
                {
                    "dataset_name": "training_table",
                    "target_col": "",
                    "feature_cols": "feature_a,feature_b",
                    "output_name": "rf_out",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "TARGET_FIELD_MISSING")

    def test_valid_rf_model_returns_structured_model_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            rows = list(range(25))
            service.manager.put_table(
                "training_table",
                pd.DataFrame(
                    {
                        "target": [float(i * 2 + 1) for i in rows],
                        "feature_a": [float(i) for i in rows],
                        "feature_b": [float(i % 5) for i in rows],
                    }
                ),
            )
            tools = self.tool_map(service)

            raw = tools["train_rf_fusion_model"].invoke(
                {
                    "dataset_name": "training_table",
                    "target_col": "target",
                    "feature_cols": "feature_a,feature_b",
                    "output_name": "rf_out",
                    "n_estimators": 5,
                    "max_depth": 4,
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "train_rf_fusion_model")
            artifact_types = {item["type"] for item in result["artifacts"]}
            self.assertIn("model", artifact_types)
            self.assertIn("metrics", artifact_types)
            model_result = service.manager.get_model_result(result["outputs"]["model_result_id"])
            self.assertIsNotNone(model_result)
            self.assertEqual(
                {item["artifact_id"] for item in result["artifacts"]},
                {item["artifact_id"] for item in model_result["artifacts"]},
            )

    def test_valid_lstm_model_registers_model_result_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            rows = list(range(28))
            service.manager.put_table(
                "time_table",
                pd.DataFrame(
                    {
                        "date": pd.date_range("2024-01-01", periods=len(rows), freq="D"),
                        "target": [float(i * 0.5 + 1) for i in rows],
                        "feature_a": [float(i) for i in rows],
                    }
                ),
            )
            tools = self.tool_map(service)

            raw = tools["train_lstm_fusion_model"].invoke(
                {
                    "dataset_name": "time_table",
                    "target_col": "target",
                    "dynamic_feature_cols": "feature_a",
                    "output_name": "lstm_out",
                    "date_col": "date",
                    "seq_len": 2,
                    "epochs": 1,
                    "hidden_size": 4,
                    "batch_size": 8,
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "train_lstm_fusion_model")
            self.assertIn("model_result_id", result["outputs"])
            model_result = service.manager.get_model_result(result["outputs"]["model_result_id"])
            self.assertIsNotNone(model_result)
            artifact_types = {item["type"] for item in model_result["artifacts"]}
            self.assertIn("training_history", artifact_types)
            self.assertIn("metrics", artifact_types)

    def test_lstm_missing_dynamic_field_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "time_table",
                pd.DataFrame({"date": pd.date_range("2024-01-01", periods=25), "target": list(range(25))}),
            )
            tools = self.tool_map(service)

            raw = tools["train_lstm_fusion_model"].invoke(
                {
                    "dataset_name": "time_table",
                    "target_col": "target",
                    "dynamic_feature_cols": "",
                    "output_name": "lstm_out",
                    "date_col": "date",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "LSTM_DYNAMIC_FIELDS_MISSING")

    def test_valid_gcp_registers_model_result_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            rows = list(range(30))
            service.manager.put_table(
                "prediction_table",
                pd.DataFrame(
                    {
                        "observed": [float(i) for i in rows],
                        "pred": [float(i) + (0.2 if i % 2 else -0.1) for i in rows],
                        "lon": [100.0 + (i % 10) * 0.01 for i in rows],
                        "lat": [30.0 + (i // 10) * 0.01 for i in rows],
                    }
                ),
            )
            tools = self.tool_map(service)

            raw = tools["geographical_conformal_prediction"].invoke(
                {
                    "calibration_dataset": "prediction_table",
                    "observed_col": "observed",
                    "predicted_cols": "pred",
                    "output_name": "gcp_out",
                    "lon_col": "lon",
                    "lat_col": "lat",
                    "calibration_ratio": 0.7,
                    "alpha": 0.1,
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "geographical_conformal_prediction")
            model_result = service.manager.get_model_result(result["outputs"]["model_result_id"])
            self.assertIsNotNone(model_result)
            self.assertEqual(model_result["model"], "GCP")
            artifact_types = {item["type"] for item in model_result["artifacts"]}
            self.assertIn("metrics", artifact_types)
            self.assertIn("report", artifact_types)
            self.assertIn("image", artifact_types)
            artifacts = model_result["artifacts"]
            artifact_names = {Path(item["path"]).name for item in artifacts}
            self.assertIn("gcp_out_gcp_predictions.csv", artifact_names)
            self.assertIn("gcp_out_gcp_metrics.json", artifact_names)
            self.assertIn("gcp_out_gcp_report.md", artifact_names)
            self.assertIn("gcp_out_gcp_prediction_intervals.png", artifact_names)
            self.assertIn("gcp_out_gcp_interval_width_spatial.png", artifact_names)
            for artifact in artifacts:
                self.assertEqual(artifact.get("owner_user_id"), service.manager.current_user_id)
                self.assertEqual(artifact.get("session_id"), service.manager.current_session_id)
                self.assertEqual(artifact.get("source_tool"), "geographical_conformal_prediction")
                if artifact["type"] == "image":
                    self.assertEqual(artifact.get("mime_type"), "image/png")
                    self.assertTrue(artifact.get("preview_available"))
                    self.assertTrue(Path(artifact["path"]).exists())
                    self.assertGreater(Path(artifact["path"]).stat().st_size, 0)

    def test_gcp_missing_predicted_field_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("prediction_table", pd.DataFrame({"observed": list(range(25))}))
            tools = self.tool_map(service)

            raw = tools["geographical_conformal_prediction"].invoke(
                {
                    "calibration_dataset": "prediction_table",
                    "observed_col": "observed",
                    "predicted_cols": "missing_pred",
                    "output_name": "gcp_out",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertIn(result["error_code"], {"FIELD_NOT_FOUND", "NUMERIC_FIELD_REQUIRED"})

    def test_vector_overlay_invalid_mode_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = gpd.GeoDataFrame({"id": [1], "geometry": [box(0, 0, 2, 2)]}, crs="EPSG:4326")
            right = gpd.GeoDataFrame({"id": [1], "geometry": [box(1, 1, 3, 3)]}, crs="EPSG:4326")
            service.manager.put_vector("left_layer", left)
            service.manager.put_vector("right_layer", right)
            tools = self.tool_map(service)

            raw = tools["vector_overlay"].invoke(
                {"dataset_name": "left_layer", "overlay_name": "right_layer", "how": "bad_mode", "output_name": "overlay_out"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "OVERLAY_MODE_UNSUPPORTED")

    def test_valid_vector_overlay_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = gpd.GeoDataFrame({"left_id": [1], "geometry": [box(0, 0, 2, 2)]}, crs="EPSG:4326")
            right = gpd.GeoDataFrame({"right_id": [1], "geometry": [box(1, 1, 3, 3)]}, crs="EPSG:4326")
            service.manager.put_vector("left_layer", left)
            service.manager.put_vector("right_layer", right)
            tools = self.tool_map(service)

            raw = tools["vector_overlay"].invoke(
                {"dataset_name": "left_layer", "overlay_name": "right_layer", "how": "intersection", "output_name": "overlay_out"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "vector_overlay")
            self.assertEqual(result["outputs"]["feature_count"], 1)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_raster_histogram_invalid_band_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            tools = self.tool_map(service)

            raw = tools["raster_histogram"].invoke({"dataset_name": "test_raster", "band": 9, "output_name": "hist"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "RASTER_BAND_OUT_OF_RANGE")

    def test_valid_raster_histogram_returns_structured_plot_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            tools = self.tool_map(service)

            raw = tools["raster_histogram"].invoke({"dataset_name": "test_raster", "band": 1, "output_name": "hist"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "raster_histogram")
            self.assertEqual(result["artifacts"][0]["type"], "plot")
            self.assertTrue(Path(result["artifacts"][0]["path"]).exists())

    def test_vector_dissolve_missing_field_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            gdf = gpd.GeoDataFrame({"group": ["a"], "geometry": [box(0, 0, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("zones", gdf)
            tools = self.tool_map(service)

            raw = tools["vector_dissolve"].invoke({"dataset_name": "zones", "by_field": "missing", "output_name": "dissolved"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "FIELD_NOT_FOUND")

    def test_valid_vector_dissolve_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            gdf = gpd.GeoDataFrame(
                {"group": ["a", "a"], "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)]},
                crs="EPSG:4326",
            )
            service.manager.put_vector("zones", gdf)
            tools = self.tool_map(service)

            raw = tools["vector_dissolve"].invoke({"dataset_name": "zones", "by_field": "group", "output_name": "dissolved"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "vector_dissolve")
            self.assertEqual(result["outputs"]["feature_count"], 1)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_vector_spatial_join_invalid_predicate_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            points = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0.5, 0.5)]}, crs="EPSG:4326")
            polygons = gpd.GeoDataFrame({"zone": ["a"], "geometry": [box(0, 0, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("points", points)
            service.manager.put_vector("zones", polygons)
            tools = self.tool_map(service)

            raw = tools["vector_spatial_join"].invoke(
                {"target_name": "points", "join_name": "zones", "predicate": "bad", "output_name": "joined"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "SPATIAL_PREDICATE_UNSUPPORTED")

    def test_valid_vector_spatial_join_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            points = gpd.GeoDataFrame({"id": [1, 2], "geometry": [Point(0.5, 0.5), Point(3, 3)]}, crs="EPSG:4326")
            polygons = gpd.GeoDataFrame({"zone": ["a"], "geometry": [box(0, 0, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("points", points)
            service.manager.put_vector("zones", polygons)
            tools = self.tool_map(service)

            raw = tools["vector_spatial_join"].invoke(
                {"target_name": "points", "join_name": "zones", "predicate": "within", "output_name": "joined", "how": "left"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "vector_spatial_join")
            self.assertEqual(result["outputs"]["feature_count"], 2)
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_summarize_points_within_polygons_missing_numeric_field_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            points = gpd.GeoDataFrame({"id": [1], "geometry": [Point(0.5, 0.5)]}, crs="EPSG:4326")
            polygons = gpd.GeoDataFrame({"zone": ["a"], "geometry": [box(0, 0, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("points", points)
            service.manager.put_vector("zones", polygons)
            tools = self.tool_map(service)

            raw = tools["summarize_points_within_polygons"].invoke(
                {"point_name": "points", "polygon_name": "zones", "output_name": "summary", "numeric_field": "value"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "FIELD_NOT_FOUND")

    def test_valid_summarize_points_within_polygons_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            points = gpd.GeoDataFrame(
                {"id": [1, 2], "value": [4.0, 6.0], "geometry": [Point(0.5, 0.5), Point(0.6, 0.6)]},
                crs="EPSG:4326",
            )
            polygons = gpd.GeoDataFrame({"zone": ["a"], "geometry": [box(0, 0, 1, 1)]}, crs="EPSG:4326")
            service.manager.put_vector("points", points)
            service.manager.put_vector("zones", polygons)
            tools = self.tool_map(service)

            raw = tools["summarize_points_within_polygons"].invoke(
                {"point_name": "points", "polygon_name": "zones", "output_name": "summary", "numeric_field": "value", "stat": "mean"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "summarize_points_within_polygons")
            self.assertEqual(result["outputs"]["feature_count"], 1)
            self.assertIn("value_mean", result["outputs"]["fields_added"])

    def test_valid_raster_zonal_stats_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            zones = gpd.GeoDataFrame({"zone": ["a"], "geometry": [box(-0.5, -0.5, 2.5, 2.5)]}, crs="EPSG:4326")
            service.manager.put_vector("zones", zones)
            tools = self.tool_map(service)

            raw = tools["raster_zonal_stats"].invoke(
                {"raster_name": "test_raster", "polygon_name": "zones", "output_name": "zonal", "stat": "mean"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "raster_zonal_stats")
            self.assertEqual(result["artifacts"][0]["type"], "dataset")
            self.assertIn("mean", result["outputs"]["fields_added"][0])

    def test_export_dataset_returns_structured_file_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("table_result", pd.DataFrame({"a": [1, 2]}))
            target = service.manager.derived_dir / "exports" / "table_result.csv"
            tools = self.tool_map(service)

            raw = tools["export_dataset"].invoke({"dataset_name": "table_result", "output_path": str(target)})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "export_dataset")
            self.assertEqual(result["artifacts"][0]["type"], "file")
            self.assertTrue(target.exists())

    def test_export_vector_shapefile_returns_zip_with_sidecar_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector(
                "vector_result",
                gpd.GeoDataFrame(
                    {"value": [1.0, 2.0], "geometry": [Point(0, 0), Point(1, 1)]},
                    crs="EPSG:4326",
                ),
            )
            target = service.manager.derived_dir / "exports" / "vector_result.shp"
            tools = self.tool_map(service)

            raw = tools["export_dataset"].invoke({"dataset_name": "vector_result", "output_path": str(target)})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            exported_path = Path(result["outputs"]["path"])
            self.assertEqual(exported_path.suffix.lower(), ".zip")
            self.assertTrue(exported_path.exists())
            self.assertEqual(result["outputs"]["format"], "shapefile_zip")
            with zipfile.ZipFile(exported_path) as archive:
                names = set(archive.namelist())
            self.assertIn("vector_result.shp", names)
            self.assertIn("vector_result.shx", names)
            self.assertIn("vector_result.dbf", names)
            self.assertIn("vector_result.prj", names)

    def test_export_vector_shapefile_documents_zip_encoding_and_field_truncation_limits(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector(
                "long_field_vector",
                gpd.GeoDataFrame(
                    {
                        "population_density": [1.0, 2.0],
                        "administrative_region_name": ["a", "b"],
                        "geometry": [Point(0, 0), Point(1, 1)],
                    },
                    crs="EPSG:4326",
                ),
            )
            target = service.manager.derived_dir / "exports" / "long_field_vector.shp"
            tools = self.tool_map(service)

            raw = tools["export_dataset"].invoke({"dataset_name": "long_field_vector", "output_path": str(target)})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            exported_path = Path(result["outputs"]["path"])
            self.assertEqual(exported_path.suffix.lower(), ".zip")
            self.assertEqual(result["outputs"]["format"], "shapefile_zip")
            self.assertEqual(result["outputs"]["requested_format"], ".shp")
            self.assertIn("long_field_vector.cpg", result["outputs"]["members"])
            self.assertTrue(any(warning["code"] == "SHAPEFILE_FIELD_NAME_TRUNCATION" for warning in result["warnings"]))
            self.assertTrue(any(warning["code"] == "SHAPEFILE_ZIP_PACKAGE" for warning in result["warnings"]))
            self.assertIn("UTF-8", str(result["diagnostics"]))
            with zipfile.ZipFile(exported_path) as archive:
                names = set(archive.namelist())
            self.assertIn("long_field_vector.cpg", names)
            self.assertIn("long_field_vector.prj", names)

    def test_vector_buffer_missing_crs_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector("points_no_crs", gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs=None))
            raw = self.tool_map(service)["vector_buffer"].invoke({"dataset_name": "points_no_crs", "distance": 100, "output_name": "buffered"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["tool_name"], "vector_buffer")
            self.assertEqual(result["error_code"], "CRS_REQUIRED")

    def test_valid_vector_buffer_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector("points", gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs="EPSG:4326"))
            raw = self.tool_map(service)["vector_buffer"].invoke({"dataset_name": "points", "distance": 100, "output_name": "points_buffered"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "vector_buffer")
            self.assertEqual(result["outputs"]["result_dataset"], "points_buffered")
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_reproject_vector_invalid_crs_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector("points", gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs="EPSG:4326"))
            raw = self.tool_map(service)["reproject_vector"].invoke({"dataset_name": "points", "target_crs": "not-a-crs", "output_name": "points_bad"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["tool_name"], "reproject_vector")
            self.assertEqual(result["error_code"], "TARGET_CRS_INVALID")

    def test_valid_reproject_vector_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector("points", gpd.GeoDataFrame({"id": [1], "geometry": [Point(0, 0)]}, crs="EPSG:4326"))
            raw = self.tool_map(service)["reproject_vector"].invoke({"dataset_name": "points", "target_crs": "EPSG:3857", "output_name": "points_3857"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "reproject_vector")
            self.assertEqual(result["outputs"]["target_crs"], "EPSG:3857")
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_join_attributes_missing_key_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("left_table", pd.DataFrame({"id": [1], "value": [10]}))
            service.manager.put_table("right_table", pd.DataFrame({"code": [1], "name": ["A"]}))
            raw = self.tool_map(service)["join_attributes"].invoke(
                {"left_name": "left_table", "right_name": "right_table", "left_key": "missing", "right_key": "code", "output_name": "joined"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["tool_name"], "join_attributes")
            self.assertEqual(result["error_code"], "FIELD_NOT_FOUND")

    def test_valid_join_attributes_returns_structured_dataset_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("left_table", pd.DataFrame({"id": [1, 2], "value": [10, 20]}))
            service.manager.put_table("right_table", pd.DataFrame({"id": [1, 2], "name": ["A", "B"]}))
            raw = self.tool_map(service)["join_attributes"].invoke(
                {"left_name": "left_table", "right_name": "right_table", "left_key": "id", "right_key": "id", "output_name": "joined"}
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "join_attributes")
            self.assertEqual(result["outputs"]["result_dataset"], "joined")
            self.assertEqual(result["artifacts"][0]["type"], "dataset")

    def test_raster_basic_stats_invalid_band_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            raw = self.tool_map(service)["raster_basic_stats"].invoke({"dataset_name": "test_raster", "band": 99})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["tool_name"], "raster_basic_stats")
            self.assertEqual(result["error_code"], "RASTER_BAND_OUT_OF_RANGE")

    def test_valid_raster_basic_stats_returns_structured_outputs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            raw = self.tool_map(service)["raster_basic_stats"].invoke({"dataset_name": "test_raster", "band": 1})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "raster_basic_stats")
            self.assertEqual(result["outputs"]["valid_count"], 9)
            self.assertIn("mean", result["outputs"])

    def test_raster_covariate_quality_check_flags_nodata_and_out_of_range_pixels(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = Path(tmp) / "ndvi_day.tif"
            data = np.array(
                [
                    [0.1, 0.2, -9999.0, 1.2],
                    [0.3, -0.4, -9999.0, 0.5],
                    [0.6, 0.7, 0.8, -9999.0],
                    [0.9, 0.95, -9999.0, -9999.0],
                ],
                dtype="float32",
            )
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=data.shape[0],
                width=data.shape[1],
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 4, 1, 1),
                nodata=-9999.0,
            ) as dst:
                dst.write(data, 1)
            service.manager.put_raster_path("ndvi_20190715", raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["raster_covariate_quality_check"].invoke(
                {
                    "raster_names": "ndvi_20190715",
                    "output_name": "ndvi_qa",
                    "band": 1,
                    "min_valid_ratio": 0.8,
                    "expected_ranges": "ndvi_20190715=-1:1",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["tool_name"], "raster_covariate_quality_check")
            self.assertEqual(result["outputs"]["overall_quality"], "failed")
            self.assertEqual(result["outputs"]["raster_count"], 1)
            self.assertEqual(result["outputs"]["summary_dataset"], "ndvi_qa")
            raster_summary = result["diagnostics"]["rasters"][0]
            self.assertEqual(raster_summary["valid_pixels"], 11)
            self.assertEqual(raster_summary["nodata_pixels"], 5)
            self.assertAlmostEqual(raster_summary["valid_ratio"], 11 / 16)
            self.assertEqual(raster_summary["out_of_range_pixels"], 1)
            self.assertEqual(raster_summary["quality"], "failed")
            self.assertTrue(result["artifacts"])
            self.assertEqual(result["artifacts"][0]["type"], "summary")
            self.assertTrue(result["next_actions"])

    def test_raster_covariate_quality_check_applies_precipitation_type_defaults(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = Path(tmp) / "precip_day.tif"
            data = np.array([[0.0, 1.5], [-2.0, 25.0]], dtype="float32")
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=data.shape[0],
                width=data.shape[1],
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 2, 1, 1),
                nodata=-9999.0,
            ) as dst:
                dst.write(data, 1)
            service.manager.put_raster_path("precip_20190715", raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["raster_covariate_quality_check"].invoke(
                {
                    "raster_names": "precip_20190715",
                    "output_name": "precip_qa",
                    "covariate_type": "precipitation_mm",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            summary = result["diagnostics"]["rasters"][0]
            self.assertEqual(summary["covariate_type"], "precipitation_mm")
            self.assertEqual(summary["expected_min"], 0.0)
            self.assertEqual(summary["out_of_range_pixels"], 1)
            self.assertEqual(summary["quality"], "failed")
            self.assertIn("values_outside_expected_range", summary["reasons"])

    def test_raster_covariate_quality_check_treats_landcover_as_categorical(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = Path(tmp) / "landcover.tif"
            data = np.array([[1, 2, 3], [2, 3, 99]], dtype="int16")
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=data.shape[0],
                width=data.shape[1],
                count=1,
                dtype="int16",
                crs="EPSG:4326",
                transform=from_origin(0, 2, 1, 1),
                nodata=0,
            ) as dst:
                dst.write(data, 1)
            service.manager.put_raster_path("landcover_2020", raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["raster_covariate_quality_check"].invoke(
                {
                    "raster_names": "landcover_2020",
                    "output_name": "landcover_qa",
                    "covariate_type": "landcover",
                    "expected_categories": "1,2,3",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            summary = result["diagnostics"]["rasters"][0]
            self.assertEqual(summary["data_model"], "categorical")
            self.assertEqual(summary["unique_class_count"], 4)
            self.assertEqual(summary["unexpected_category_pixels"], 1)
            self.assertEqual(summary["unexpected_categories"], [99])
            self.assertEqual(summary["quality"], "failed")

    def test_raster_covariate_quality_check_has_planner_tool_card(self) -> None:
        from core.tool_cards import candidate_tool_cards, list_tool_cards

        names = {card["tool_name"] for card in list_tool_cards()}
        candidates = {
            card["tool_name"]
            for card in candidate_tool_cards("daily NDVI LST covariate quality check missing data", task_type="data_processing", limit=12)
        }
        chinese_candidates = [
            card["tool_name"]
            for card in candidate_tool_cards("检查日数据 NDVI LST 缺失和有效像元比例", task_type="data_processing", limit=8)
        ]
        precipitation_candidates = [
            card["tool_name"]
            for card in candidate_tool_cards("检查日降水 precipitation 缺失和负值质量", task_type="data_processing", limit=8)
        ]
        landcover_candidates = [
            card["tool_name"]
            for card in candidate_tool_cards("检查土地利用 landcover 分类编码质量", task_type="data_processing", limit=8)
        ]

        self.assertIn("raster_covariate_quality_check", names)
        self.assertIn("raster_covariate_quality_check", candidates)
        self.assertEqual(chinese_candidates[0], "raster_covariate_quality_check")
        self.assertEqual(precipitation_candidates[0], "raster_covariate_quality_check")
        self.assertEqual(landcover_candidates[0], "raster_covariate_quality_check")

    def test_temporal_covariate_composite_uses_ndvi_default_max(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            transform = from_origin(0, 2, 1, 1)
            rasters = {
                "ndvi_day_1": np.array([[0.1, -9999.0], [0.3, -9999.0]], dtype="float32"),
                "ndvi_day_2": np.array([[0.4, 0.2], [-9999.0, -9999.0]], dtype="float32"),
                "ndvi_day_3": np.array([[0.2, 0.7], [0.5, -9999.0]], dtype="float32"),
            }
            for name, data in rasters.items():
                raster_path = Path(tmp) / f"{name}.tif"
                with rasterio.open(
                    raster_path,
                    "w",
                    driver="GTiff",
                    height=data.shape[0],
                    width=data.shape[1],
                    count=1,
                    dtype="float32",
                    crs="EPSG:4326",
                    transform=transform,
                    nodata=-9999.0,
                ) as dst:
                    dst.write(data, 1)
                service.manager.put_raster_path(name, raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["build_temporal_covariate_composite"].invoke(
                {
                    "raster_names": "ndvi_day_1,ndvi_day_2,ndvi_day_3",
                    "output_name": "ndvi_composite",
                    "covariate_type": "ndvi",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["tool_name"], "build_temporal_covariate_composite")
            self.assertEqual(result["outputs"]["method"], "max")
            self.assertEqual(result["outputs"]["source_raster_count"], 3)
            self.assertEqual(result["outputs"]["valid_pixel_count"], 3)
            self.assertEqual(result["outputs"]["all_missing_pixel_count"], 1)
            with rasterio.open(result["outputs"]["path"]) as src:
                out = src.read(1)
                self.assertTrue(np.allclose(out, np.array([[0.4, 0.7], [0.5, -9999.0]], dtype="float32")))
                self.assertEqual(src.nodata, -9999.0)
            self.assertTrue(any(artifact["type"] == "raster" for artifact in result["artifacts"]))
            self.assertTrue(any(artifact["type"] == "summary" for artifact in result["artifacts"]))
            self.assertTrue(result["map_layers"])
            self.assertEqual(result["diagnostics"]["valid_observation_count"]["max"], 3)

    def test_temporal_covariate_composite_sums_precipitation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            transform = from_origin(0, 2, 1, 1)
            rasters = {
                "precip_day_1": np.array([[1.0, -9999.0], [3.0, -9999.0]], dtype="float32"),
                "precip_day_2": np.array([[2.5, 4.0], [-9999.0, -9999.0]], dtype="float32"),
            }
            for name, data in rasters.items():
                raster_path = Path(tmp) / f"{name}.tif"
                with rasterio.open(
                    raster_path,
                    "w",
                    driver="GTiff",
                    height=data.shape[0],
                    width=data.shape[1],
                    count=1,
                    dtype="float32",
                    crs="EPSG:4326",
                    transform=transform,
                    nodata=-9999.0,
                ) as dst:
                    dst.write(data, 1)
                service.manager.put_raster_path(name, raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["build_temporal_covariate_composite"].invoke(
                {
                    "raster_names": "precip_day_1,precip_day_2",
                    "output_name": "precip_total",
                    "covariate_type": "precipitation_mm",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["method"], "sum")
            with rasterio.open(result["outputs"]["path"]) as src:
                out = src.read(1)
                self.assertTrue(np.allclose(out, np.array([[3.5, 4.0], [3.0, -9999.0]], dtype="float32")))
            self.assertEqual(result["diagnostics"]["valid_observation_count"]["min"], 0)
            self.assertEqual(result["outputs"]["all_missing_pixel_count"], 1)

    def test_temporal_covariate_composite_reads_single_multiband_raster_as_time_series(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = Path(tmp) / "ndvi_multiband.tif"
            data = np.array(
                [
                    [[0.1, -9999.0], [0.3, -9999.0]],
                    [[0.4, 0.2], [-9999.0, -9999.0]],
                    [[0.2, 0.7], [0.5, -9999.0]],
                ],
                dtype="float32",
            )
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=data.shape[1],
                width=data.shape[2],
                count=data.shape[0],
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 2, 1, 1),
                nodata=-9999.0,
            ) as dst:
                dst.write(data)
                dst.set_band_description(1, "2019_01_01_2019_01_01_NDVI")
                dst.set_band_description(2, "2019_01_02_2019_01_02_NDVI")
                dst.set_band_description(3, "2019_01_03_2019_01_03_NDVI")
            service.manager.put_raster_path("ndvi_multiband", raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["build_temporal_covariate_composite"].invoke(
                {
                    "raster_names": "ndvi_multiband",
                    "output_name": "ndvi_multiband_composite",
                    "covariate_type": "ndvi",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["method"], "max")
            self.assertEqual(result["outputs"]["source_raster_count"], 1)
            self.assertEqual(result["outputs"]["source_band_count"], 3)
            self.assertEqual(result["outputs"]["input_layout"], "single_multiband")
            self.assertEqual(result["diagnostics"]["source_bands"][0]["description"], "2019_01_01_2019_01_01_NDVI")
            with rasterio.open(result["outputs"]["path"]) as src:
                out = src.read(1)
                self.assertTrue(np.allclose(out, np.array([[0.4, 0.7], [0.5, -9999.0]], dtype="float32")))

    def test_temporal_covariate_composite_filters_multiband_raster_by_date_range(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = Path(tmp) / "ndvi_multiband.tif"
            data = np.array(
                [
                    [[0.9, -9999.0], [0.3, -9999.0]],
                    [[0.4, 0.2], [-9999.0, -9999.0]],
                    [[0.2, 0.7], [0.5, -9999.0]],
                ],
                dtype="float32",
            )
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=data.shape[1],
                width=data.shape[2],
                count=data.shape[0],
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 2, 1, 1),
                nodata=-9999.0,
            ) as dst:
                dst.write(data)
                dst.set_band_description(1, "2019_01_01_2019_01_01_NDVI")
                dst.set_band_description(2, "2019_01_02_2019_01_02_NDVI")
                dst.set_band_description(3, "2019_01_03_2019_01_03_NDVI")
            service.manager.put_raster_path("ndvi_multiband", raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["build_temporal_covariate_composite"].invoke(
                {
                    "raster_names": "ndvi_multiband",
                    "output_name": "ndvi_filtered_composite",
                    "covariate_type": "ndvi",
                    "start_date": "2019-01-02",
                    "end_date": "2019-01-03",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["source_band_count"], 2)
            self.assertEqual(result["outputs"]["selected_time_range"], {"start": "2019-01-02", "end": "2019-01-03"})
            self.assertEqual([item["date"] for item in result["diagnostics"]["source_bands"]], ["2019-01-02", "2019-01-03"])
            with rasterio.open(result["outputs"]["path"]) as src:
                out = src.read(1)
                self.assertTrue(np.allclose(out, np.array([[0.4, 0.7], [0.5, -9999.0]], dtype="float32")))

    def test_align_station_raster_time_window_selects_common_dates_and_stations(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "ismn_daily",
                pd.DataFrame(
                    {
                        "station_id": ["S1", "S1", "S1", "S2", "S3"],
                        "date": ["2019-01-01", "2019-01-02", "2019-01-04", "2019-01-02", "2019-01-04"],
                        "lon": [115.8, 115.8, 115.8, 116.0, 116.2],
                        "lat": [41.8, 41.8, 41.8, 41.9, 42.0],
                        "soil_moisture_mean": [0.11, 0.12, 0.15, 0.2, 0.25],
                    }
                ),
            )
            raster_specs = {
                "ndvi_daily": ["2019_01_01_2019_01_01_NDVI", "2019_01_02_2019_01_02_NDVI", "2019_01_03_2019_01_03_NDVI"],
                "lst_daily": ["2019_01_02_2019_01_02_LST", "2019_01_03_2019_01_03_LST"],
            }
            for name, descriptions in raster_specs.items():
                raster_path = Path(tmp) / f"{name}.tif"
                data = np.ones((len(descriptions), 2, 2), dtype="float32")
                with rasterio.open(
                    raster_path,
                    "w",
                    driver="GTiff",
                    height=2,
                    width=2,
                    count=len(descriptions),
                    dtype="float32",
                    crs="EPSG:4326",
                    transform=from_origin(0, 2, 1, 1),
                ) as dst:
                    dst.write(data)
                    for index, description in enumerate(descriptions, start=1):
                        dst.set_band_description(index, description)
                service.manager.put_raster_path(name, raster_path, meta={"crs": "EPSG:4326"})

            raw = self.tool_map(service)["align_station_raster_time_window"].invoke(
                {
                    "station_dataset": "ismn_daily",
                    "raster_names": "ndvi_daily,lst_daily",
                    "output_name": "aligned_station_dates",
                    "date_col": "date",
                    "station_col": "station_id",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["tool_name"], "align_station_raster_time_window")
            self.assertEqual(result["outputs"]["selected_time_range"], {"start": "2019-01-02", "end": "2019-01-02"})
            self.assertEqual(result["outputs"]["selected_date_count"], 1)
            self.assertEqual(result["outputs"]["selected_station_count"], 2)
            self.assertEqual(result["outputs"]["selected_station_ids"], ["S1", "S2"])
            aligned = service.manager.get_table(result["outputs"]["result_dataset"])
            self.assertEqual(aligned["date"].tolist(), ["2019-01-02", "2019-01-02"])
            self.assertEqual(sorted(aligned["station_id"].tolist()), ["S1", "S2"])

    def test_temporal_covariate_composite_has_planner_tool_card(self) -> None:
        from core.tool_cards import candidate_tool_cards, list_tool_cards

        names = {card["tool_name"] for card in list_tool_cards()}
        candidates = [
            card["tool_name"]
            for card in candidate_tool_cards("build temporal NDVI LST precipitation composite for missing daily rasters", task_type="data_processing", limit=8)
        ]

        self.assertIn("build_temporal_covariate_composite", names)
        self.assertEqual(candidates[0], "build_temporal_covariate_composite")

    def test_station_raster_temporal_alignment_has_planner_card_and_executor_allowlist(self) -> None:
        from core.tool_cards import candidate_tool_cards, list_tool_cards
        from core.tool_executor import DEFAULT_DETERMINISTIC_TOOLS
        from core.workflow_executor import SUPPORTED_WORKFLOW_TOOLS

        names = {card["tool_name"] for card in list_tool_cards()}
        candidates = [
            card["tool_name"]
            for card in candidate_tool_cards("align ISMN station dates with NDVI LST raster band dates", task_type="modeling", limit=8)
        ]

        self.assertIn("align_station_raster_time_window", names)
        self.assertEqual(candidates[0], "align_station_raster_time_window")
        self.assertIn("align_station_raster_time_window", DEFAULT_DETERMINISTIC_TOOLS)
        self.assertIn("align_station_raster_time_window", SUPPORTED_WORKFLOW_TOOLS)

    def test_batch_register_invalid_mode_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            service.manager.put_vector(
                "sample_points",
                gpd.GeoDataFrame({"site_id": ["a"], "geometry": [Point(0, 2)]}, crs="EPSG:4326"),
            )

            raw = self.tool_map(service)["batch_register_points_to_rasters"].invoke(
                {
                    "point_name": "sample_points",
                    "raster_names": "test_raster",
                    "output_name": "registered",
                    "id_cols": "site_id",
                    "output_mode": "invalid",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["tool_name"], "batch_register_points_to_rasters")
            self.assertEqual(result["error_code"], "OUTPUT_MODE_UNSUPPORTED")

    def test_batch_register_long_mode_returns_structured_dataset_and_summary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("test_raster", raster_path, meta={"crs": "EPSG:4326"})
            service.manager.put_vector(
                "sample_points",
                gpd.GeoDataFrame(
                    {"site_id": ["a", "b"], "geometry": [Point(0, 2), Point(1, 1)]},
                    crs="EPSG:4326",
                ),
            )

            raw = self.tool_map(service)["batch_register_points_to_rasters"].invoke(
                {
                    "point_name": "sample_points",
                    "raster_names": "test_raster",
                    "output_name": "registered",
                    "id_cols": "site_id",
                    "output_mode": "long",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "batch_register_points_to_rasters")
            self.assertEqual(result["outputs"]["result_dataset"], "registered")
            self.assertEqual(result["outputs"]["row_count"], 2)
            artifact_types = {artifact["type"] for artifact in result["artifacts"]}
            self.assertIn("dataset", artifact_types)
            self.assertIn("file", artifact_types)

    def test_batch_register_applies_raster_scale_and_offset(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = Path(tmp) / "scaled_precip.tif"
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=1,
                width=1,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 1, 1, 1),
                nodata=-9999.0,
            ) as dst:
                dst.write(np.array([[584.0]], dtype="float32"), 1)
                dst.scales = (0.01,)
                dst.offsets = (0.0,)
            service.manager.put_raster_path("scaled_precip", raster_path)
            service.manager.put_vector(
                "sample_points",
                gpd.GeoDataFrame({"site_id": ["a"], "geometry": [Point(0.5, 0.5)]}, crs="EPSG:4326"),
            )

            raw = self.tool_map(service)["batch_register_points_to_rasters"].invoke(
                {
                    "point_name": "sample_points",
                    "raster_names": "scaled_precip",
                    "output_name": "registered_scaled",
                    "output_mode": "wide",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            sampled = service.manager.get_vector("registered_scaled").drop(columns=["geometry"], errors="ignore")
            self.assertAlmostEqual(float(sampled.iloc[0]["raster_scaled_precip"]), 5.84, places=5)


if __name__ == "__main__":
    unittest.main()
