from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from core.config import Settings
from core.conversation_intent import classify_user_intent
from core.gis_tools import build_tools
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.tool_contracts import parse_tool_result
from core.workflow_executor import execute_workflow_plan, parse_workflow_result


pytestmark = pytest.mark.slow


class CheckpointGenericXGBoostMigrationTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def write_raster(self, service: GISWorkspaceService, name: str, values: np.ndarray) -> str:
        path = service.manager.derived_dir / f"{name}.tif"
        profile = {
            "driver": "GTiff",
            "height": values.shape[0],
            "width": values.shape[1],
            "count": 1,
            "dtype": "float32",
            "crs": "EPSG:4326",
            "transform": from_origin(0, values.shape[0], 1, 1),
            "nodata": -9999.0,
        }
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(values.astype("float32"), 1)
        return service.manager.put_raster_path(name, path, meta={"crs": "EPSG:4326", "width": values.shape[1], "height": values.shape[0]})

    def test_generic_xgboost_tool_is_registered(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            names = {tool.name for tool in build_tools(service.manager)}
            self.assertIn("generic_xgboost_workflow", names)

    def test_missing_target_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "samples",
                pd.DataFrame(
                    {
                        "x": [1, 2, 3, 4],
                        "y": [2, 3, 4, 5],
                    }
                ),
            )
            tool = {item.name: item for item in build_tools(service.manager)}["generic_xgboost_workflow"]
            result = parse_tool_result(tool.invoke({"dataset_name": "samples"}))

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "TARGET_REQUIRED")
            self.assertIn("target", result["diagnostics"]["required_inputs"])

    def test_csv_regression_trains_and_registers_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            rng = np.random.default_rng(42)
            rows = 48
            df = pd.DataFrame(
                {
                    "lon": np.linspace(100.0, 101.0, rows),
                    "lat": np.linspace(30.0, 31.0, rows),
                    "elevation": rng.normal(400.0, 20.0, rows),
                    "slope": rng.uniform(1.0, 12.0, rows),
                    "precip_7d": rng.uniform(0.0, 50.0, rows),
                }
            )
            df["soil_moisture"] = 0.2 + df["precip_7d"] * 0.003 - df["slope"] * 0.002
            service.manager.put_table("points", df)
            tool = {item.name: item for item in build_tools(service.manager)}["generic_xgboost_workflow"]

            result = parse_tool_result(
                tool.invoke(
                    {
                        "dataset_name": "points",
                        "target_col": "soil_moisture",
                        "feature_cols": "elevation,slope,precip_7d,lon,lat",
                        "output_name": "gxgb_points",
                        "task_type": "regression",
                    }
                )
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["model_type"], "regression")
            self.assertTrue(result["outputs"]["model_result_id"])
            self.assertIn("R2", result["outputs"]["metrics"])
            artifact_types = {artifact["type"] for artifact in result["artifacts"]}
            self.assertIn("csv", artifact_types)
            self.assertIn("metrics", artifact_types)
            self.assertIn("feature_importance", artifact_types)
            self.assertIn("model", artifact_types)
            model_result = service.manager.get_model_result(result["outputs"]["model_result_id"])
            self.assertIsNotNone(model_result)
            self.assertGreaterEqual(len(model_result["artifacts"]), 5)

    def test_csv_classification_trains(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            rows = 50
            df = pd.DataFrame(
                {
                    "f1": list(range(rows)),
                    "f2": [value % 7 for value in range(rows)],
                    "label": ["wet" if value % 3 else "dry" for value in range(rows)],
                }
            )
            service.manager.put_table("classes", df)
            tool = {item.name: item for item in build_tools(service.manager)}["generic_xgboost_workflow"]

            result = parse_tool_result(
                tool.invoke(
                    {
                        "dataset_name": "classes",
                        "target_col": "label",
                        "feature_cols": "f1,f2",
                        "output_name": "gxgb_classes",
                        "task_type": "classification",
                    }
                )
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["model_type"], "classification")
            self.assertIn("Accuracy", result["outputs"]["metrics"])

    def test_geojson_vector_regression_creates_map_ready_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            rows = 24
            gdf = gpd.GeoDataFrame(
                {
                    "target": [float(value) for value in range(rows)],
                    "f1": [float(value % 6) for value in range(rows)],
                    "f2": [float(value) / 2.0 for value in range(rows)],
                },
                geometry=[Point(100 + value * 0.01, 30 + value * 0.01) for value in range(rows)],
                crs="EPSG:4326",
            )
            service.manager.put_vector("vector_points", gdf)
            tool = {item.name: item for item in build_tools(service.manager)}["generic_xgboost_workflow"]

            result = parse_tool_result(
                tool.invoke(
                    {
                        "dataset_name": "vector_points",
                        "target_col": "target",
                        "feature_cols": "f1,f2",
                        "output_name": "gxgb_vector",
                        "task_type": "regression",
                    }
                )
            )

            self.assertTrue(result["ok"], result)
            result_artifact = result["artifacts"][0]
            self.assertEqual(result_artifact["type"], "geojson")
            self.assertTrue(result_artifact["meta"]["map_ready"])
            self.assertTrue(result["outputs"]["map_layer_id"])

    def test_point_samples_with_raster_features_train(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            grid = np.arange(36, dtype="float32").reshape(6, 6)
            self.write_raster(service, "raster_feature", grid)
            rows = []
            for row in range(6):
                for col in range(4):
                    lon = col + 0.5
                    lat = 5.5 - row
                    value = float(grid[row, col])
                    rows.append({"lon": lon, "lat": lat, "target": value * 0.5 + 1.0})
            service.manager.put_table("samples", pd.DataFrame(rows))
            tool = {item.name: item for item in build_tools(service.manager)}["generic_xgboost_workflow"]

            result = parse_tool_result(
                tool.invoke(
                    {
                        "mode": "sample_raster",
                        "sample_dataset_name": "samples",
                        "raster_names": "raster_feature",
                        "target_col": "target",
                        "output_name": "gxgb_sample_raster",
                        "task_type": "regression",
                    }
                )
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["task_mode"], "sample_raster")
            self.assertEqual(result["artifacts"][0]["type"], "geojson")
            self.assertTrue(result["artifacts"][0]["meta"]["map_ready"])

    def test_raster_stack_trains_and_writes_prediction_tif(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            f1 = np.arange(36, dtype="float32").reshape(6, 6)
            f2 = np.flipud(f1)
            target = f1 * 0.2 + f2 * 0.1
            self.write_raster(service, "feature_a", f1)
            self.write_raster(service, "feature_b", f2)
            self.write_raster(service, "target_raster", target)
            tool = {item.name: item for item in build_tools(service.manager)}["generic_xgboost_workflow"]

            result = parse_tool_result(
                tool.invoke(
                    {
                        "mode": "raster_stack",
                        "raster_names": "feature_a,feature_b",
                        "target_raster_name": "target_raster",
                        "output_name": "gxgb_raster",
                        "task_type": "regression",
                    }
                )
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["task_mode"], "raster_stack")
            self.assertTrue(str(service.manager.get(result["outputs"]["result_dataset"]).path).endswith("_prediction.tif"))
            self.assertEqual(result["artifacts"][0]["type"], "raster")
            self.assertTrue(result["artifacts"][0]["meta"]["map_ready"])

    def test_generic_xgboost_is_allowed_in_workflow_executor(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "points",
                pd.DataFrame(
                    {
                        "target": [float(value) for value in range(20)],
                        "f1": [float(value) for value in range(20)],
                        "f2": [float(value % 5) for value in range(20)],
                    }
                ),
            )
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "train_generic",
                        "tool_name": "generic_xgboost_workflow",
                        "validated_tool_args": {
                            "dataset_name": "points",
                            "target_col": "target",
                            "feature_cols": "f1,f2",
                            "output_name": "gxgb_workflow",
                            "task_type": "regression",
                        },
                    }
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"], result)
            self.assertEqual(result["steps"][0]["status"], "success")
            self.assertTrue(result["final_artifacts"])

    def test_prompt_can_route_to_generic_xgboost_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            fields = ["target", "f1", "f2", "lon", "lat"]
            service.manager.put_table(
                "points",
                pd.DataFrame({field: [float(value) for value in range(20)] for field in fields}),
            )
            context = {
                "workspace": {"dataset_count": 1},
                "active_dataset": {"name": "points", "type": "table", "meta": {"columns": fields, "rows": 20}},
                "available_datasets": service.manager.list_datasets(),
                "available_fields": fields,
                "numeric_fields": fields,
            }
            prompt = "Use generic XGBoost regression on points. target_col=target feature_cols=f1,f2,lon,lat output_name=gxgb_prompt"
            intent = classify_user_intent(prompt, {"active_dataset": "points"}, {"dataset_count": 1}, enable_llm=False)

            plan = build_task_plan(prompt, intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"], plan)
            self.assertIn("generic_xgboost_workflow", plan["validated_tool_args"])
            self.assertIn("generic_xgboost_workflow", [step.get("tool_name") for step in plan["workflow_plan"]])

    def test_chinese_prompt_routes_to_generic_xgboost_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            fields = ["soil_moisture", "elevation", "slope", "lon", "lat"]
            service.manager.put_table(
                "points",
                pd.DataFrame({field: [float(value + 1) for value in range(24)] for field in fields}),
            )
            context = {
                "workspace": {"dataset_count": 1},
                "active_dataset": {"name": "points", "type": "table", "meta": {"columns": fields, "rows": 24}},
                "available_datasets": service.manager.list_datasets(),
                "available_fields": fields,
                "numeric_fields": fields,
            }
            prompt = "使用当前上传的数据做通用 XGBoost 回归。目标列是 soil_moisture。特征列使用 elevation,slope,lon,lat。输出名称为 gxgb_cn。"
            intent = classify_user_intent(prompt, {"active_dataset": "points"}, {"dataset_count": 1}, enable_llm=False)

            plan = build_task_plan(prompt, intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"], plan)
            args = plan["validated_tool_args"]["generic_xgboost_workflow"]
            self.assertEqual(args["target_col"], "soil_moisture")
            self.assertEqual(args["feature_cols"], "elevation,slope,lon,lat")
            self.assertEqual(args["output_name"], "gxgb_cn")

    def test_service_dialog_runs_generic_xgboost_and_returns_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.set_interaction_mode("tool_enabled")
            rows = 36
            service.manager.put_table(
                "points",
                pd.DataFrame(
                    {
                        "soil_moisture": [0.2 + value * 0.01 for value in range(rows)],
                        "elevation": [400.0 + value for value in range(rows)],
                        "slope": [float(value % 6) for value in range(rows)],
                        "lon": [100.0 + value * 0.01 for value in range(rows)],
                        "lat": [30.0 + value * 0.01 for value in range(rows)],
                    }
                ),
            )

            prompt = (
                "Use generic XGBoost regression on current data. "
                "target_col=soil_moisture feature_cols=elevation,slope,lon,lat output_name=gxgb_dialog"
            )

            def active_plan(prompt_text: str, context: dict, **kwargs):
                plan = build_task_plan(prompt_text, context.get("intent") or {}, context, manager=service.manager)
                return {"status": "ready", "mode": "active", "planner_source": "test", "executes_tools": False, "plan": plan}

            with mock.patch("core.service.build_llm_task_plan", side_effect=active_plan):
                with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                    response = service.ask(prompt)
            dashboard = service.dashboard()

            self.assertEqual(response["mode"], "validated_workflow_executor")
            self.assertGreaterEqual(len(response["artifacts"]), 5)
            self.assertEqual(len(response["files"]), len(response["artifacts"]))
            self.assertEqual(dashboard["model_results"][0]["model"], "generic_xgboost")


if __name__ == "__main__":
    unittest.main()
