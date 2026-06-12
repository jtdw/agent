from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box

from core.config import Settings
from core.conversation_intent import classify_user_intent
from core.context_builder import build_conversation_context
from core.conversation_state import ConversationState
from core.result_interpreter import interpret_result
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.tool_contracts import parse_tool_result
from core.tool_executor import execute_validated_tool_plan
from core.workflow_executor import execute_workflow_plan, parse_workflow_result


class WorkflowExecutorTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def seed_clip_map_data(self, service: GISWorkspaceService) -> None:
        service.manager.put_vector(
            "points",
            gpd.GeoDataFrame(
                {"pop_density": [10.0, 20.0, 30.0], "geometry": [Point(0, 0), Point(1, 1), Point(5, 5)]},
                crs="EPSG:4326",
            ),
        )
        service.manager.put_vector(
            "study_area",
            gpd.GeoDataFrame({"name": ["a"], "geometry": [box(-1, -1, 2, 2)]}, crs="EPSG:4326"),
        )

    def workflow_context(self) -> dict:
        return {
            "workspace": {"dataset_count": 2},
            "active_dataset": {"name": "points", "type": "vector"},
            "available_fields": ["pop_density", "geometry"],
            "numeric_fields": ["pop_density"],
            "referenced_object": {"type": "dataset", "name": "study_area", "dataset_id": "study_area"},
        }

    def seed_model_table(self, service: GISWorkspaceService, rows: int = 30) -> None:
        service.manager.put_table(
            "model_table",
            pd.DataFrame(
                {
                    "rainfall": [float(i) for i in range(rows)],
                    "elevation": [float(i * 2) for i in range(rows)],
                    "ndvi": [float(i * 0.3 + 1.0) for i in range(rows)],
                }
            ),
        )

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

    def modeling_context(self) -> dict:
        return {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "model_table", "type": "table"},
            "available_fields": ["rainfall", "elevation", "ndvi"],
            "numeric_fields": ["rainfall", "elevation", "ndvi"],
        }

    def test_single_tool_plan_still_uses_tool_executor(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            plan = {
                "tool_plan": [{"tool_name": "describe_dataset", "args": {"dataset_name": "points"}}],
                "validated_tool_args": {"describe_dataset": {"dataset_name": "points"}},
                "workflow_plan": [],
            }

            workflow_execution = execute_workflow_plan(service.manager, plan)
            tool_execution = execute_validated_tool_plan(service.manager, plan)

            self.assertFalse(workflow_execution["executed"])
            self.assertTrue(tool_execution["executed"])
            self.assertEqual(tool_execution["executed_tools"], ["describe_dataset"])

    def test_multistep_workflow_executes_in_order_and_passes_clip_output_to_plot(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            intent = {"intent": "data_processing", "confidence": 0.86, "secondary_intents": ["map_generation", "result_analysis"]}

            plan = build_task_plan(
                "clip this shp to the study area, then plot population density map and explain",
                intent,
                self.workflow_context(),
                manager=service.manager,
            )
            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["executed"])
            self.assertTrue(execution["ok"])
            self.assertIsNotNone(result)
            self.assertEqual([step["step_id"] for step in result["steps"]], ["check_dataset", "clip_vector", "generate_map", "interpret_map_result"])
            plot_step = next(step for step in result["steps"] if step["step_id"] == "generate_map")
            self.assertEqual(plot_step["validated_tool_args"]["dataset_name"], "points_clipped")
            self.assertTrue(result["final_artifacts"])
            self.assertEqual(result["final_artifacts"][-1]["type"], "map")
            self.assertTrue(Path(result["final_artifacts"][-1]["path"]).exists())

    def test_workflow_stops_after_failed_dependency_and_skips_later_steps(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "clip_vector",
                        "tool_name": "vector_clip_by_vector",
                        "validated_tool_args": {"dataset_name": "points", "clip_name": "missing_boundary", "output_name": "points_clipped"},
                    },
                    {
                        "step_id": "generate_map",
                        "tool_name": "plot_dataset",
                        "depends_on": ["clip_vector"],
                        "validated_tool_args": {"dataset_name": "$steps.clip_vector.outputs.result_dataset", "column": "pop_density"},
                    },
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertFalse(execution["ok"])
            self.assertEqual(result["failed_step"], "clip_vector")
            self.assertEqual(result["steps"][0]["status"], "failed")
            self.assertEqual(result["steps"][1]["status"], "skipped")

    def test_workflow_validates_objects_before_invoking_tool(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "generate_map",
                        "tool_name": "plot_dataset",
                        "validated_tool_args": {"dataset_name": "missing_dataset", "column": "pop_density"},
                    }
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertFalse(execution["ok"])
            self.assertEqual(result["failed_step"], "generate_map")
            self.assertEqual(result["steps"][0]["tool_result"]["error_code"], "OBJECT_NOT_FOUND")

    def test_unsupported_workflow_tool_returns_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            plan = {
                "workflow_plan": [
                    {"step_id": "unsupported", "tool_name": "unsupported_overlay_tool", "validated_tool_args": {"dataset_name": "a"}}
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertFalse(execution["ok"])
            self.assertEqual(result["failed_step"], "unsupported")
            self.assertEqual(result["steps"][0]["tool_result"]["error_code"], "UNSUPPORTED_WORKFLOW_TOOL")
            self.assertTrue(result["next_actions"])

    def test_result_interpreter_explains_workflow_success_and_failure(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            plan = {
                "workflow_plan": [
                    {"step_id": "check_dataset", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "points"}},
                ]
            }
            execution = execute_workflow_plan(service.manager, plan)
            context = {"active_dataset": {"name": "points", "type": "vector"}}

            success_reply = interpret_result("check", {"intent": "data_upload_analysis"}, plan, execution["raw_reply"], context, {})
            self.assertIn("逐步解释", success_reply)
            self.assertIn("check_dataset", success_reply)

            bad_plan = {"workflow_plan": [{"step_id": "bad", "tool_name": "unsupported_overlay_tool", "validated_tool_args": {}}]}
            bad_execution = execute_workflow_plan(service.manager, bad_plan)
            failure_reply = interpret_result("bad", {"intent": "data_processing"}, bad_plan, bad_execution["raw_reply"], context, {})
            self.assertIn("失败定位", failure_reply)
            self.assertIn("bad", failure_reply)
            self.assertIn("UNSUPPORTED_WORKFLOW_TOOL", failure_reply)

    def test_overlay_workflow_output_can_feed_map_step(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = gpd.GeoDataFrame({"pop_density": [12.0], "geometry": [box(0, 0, 2, 2)]}, crs="EPSG:4326")
            right = gpd.GeoDataFrame({"zone": [1], "geometry": [box(1, 1, 3, 3)]}, crs="EPSG:4326")
            service.manager.put_vector("left_poly", left)
            service.manager.put_vector("right_poly", right)
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "overlay",
                        "tool_name": "vector_overlay",
                        "validated_tool_args": {
                            "dataset_name": "left_poly",
                            "overlay_name": "right_poly",
                            "how": "intersection",
                            "output_name": "overlay_out",
                        },
                    },
                    {
                        "step_id": "generate_map",
                        "tool_name": "plot_dataset",
                        "depends_on": ["overlay"],
                        "validated_tool_args": {
                            "dataset_name": "$steps.overlay.outputs.result_dataset",
                            "column": "pop_density",
                            "output_name": "overlay_map.png",
                        },
                    },
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            self.assertEqual([step["step_id"] for step in result["steps"]], ["overlay", "generate_map"])
            map_step = next(step for step in result["steps"] if step["step_id"] == "generate_map")
            self.assertEqual(map_step["validated_tool_args"]["dataset_name"], "overlay_out")
            self.assertEqual(result["final_artifacts"][-1]["type"], "map")

    def test_table_to_points_can_feed_raster_extraction_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"lon": [0, 1], "lat": [0, 1], "station_id": ["A", "B"]}))
            raster_path = self.write_test_raster(Path(tmp) / "test.tif")
            service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:4326"})
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "make_points",
                        "tool_name": "table_to_points",
                        "validated_tool_args": {
                            "dataset_name": "stations",
                            "x_col": "lon",
                            "y_col": "lat",
                            "crs": "EPSG:4326",
                            "output_name": "station_points",
                        },
                    },
                    {
                        "step_id": "extract_dem",
                        "tool_name": "extract_raster_values_to_points",
                        "depends_on": ["make_points"],
                        "validated_tool_args": {
                            "point_name": "$steps.make_points.outputs.result_dataset",
                            "raster_name": "dem",
                            "output_name": "station_dem",
                            "field_name": "dem_value",
                        },
                    },
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            extract_step = next(step for step in result["steps"] if step["step_id"] == "extract_dem")
            self.assertEqual(extract_step["validated_tool_args"]["point_name"], "station_points")
            self.assertEqual(extract_step["tool_result"]["outputs"]["field_name"], "dem_value")
            self.assertIn("station_dem", service.manager.datasets)

    def test_planner_builds_table_to_points_then_raster_extraction_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"lon": [0, 1], "lat": [0, 1], "station_id": ["A", "B"]}))
            raster_path = self.write_test_raster(Path(tmp) / "dem.tif")
            service.manager.put_raster_path("dem", raster_path, meta={"crs": "EPSG:4326"})
            context = {
                "workspace": {"dataset_count": 2},
                "active_dataset": {"name": "stations", "type": "table"},
                "available_fields": ["lon", "lat", "station_id"],
                "numeric_fields": ["lon", "lat"],
                "available_datasets": [
                    {"name": "stations", "type": "table", "path": "stations.csv"},
                    {"name": "dem", "type": "raster", "path": "dem.tif"},
                ],
            }
            intent = {"intent": "data_processing", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("把表格转成点，然后提取 dem 栅格值", intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            self.assertEqual([step["tool_name"] for step in plan["workflow_plan"]], ["table_to_points", "extract_raster_values_to_points"])
            self.assertEqual(plan["workflow_plan"][0]["validated_tool_args"]["x_col"], "lon")
            self.assertEqual(plan["workflow_plan"][0]["validated_tool_args"]["y_col"], "lat")
            self.assertEqual(plan["workflow_plan"][1]["validated_tool_args"]["point_name"], "$steps.make_points.outputs.result_dataset")

    def test_planner_builds_table_to_points_then_map_workflow_for_csv_mapping(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "stations",
                pd.DataFrame({"lon": [0, 1], "lat": [0, 1], "pop_density": [12.0, 20.0]}),
            )
            context = {
                "workspace": {"dataset_count": 1},
                "active_dataset": {"name": "stations", "type": "table"},
                "available_fields": ["lon", "lat", "pop_density"],
                "numeric_fields": ["lon", "lat", "pop_density"],
                "available_datasets": [{"name": "stations", "type": "table", "path": "stations.csv"}],
            }
            intent = {"intent": "map_generation", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("plot population density map", intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            self.assertEqual([step["tool_name"] for step in plan["workflow_plan"]], ["table_to_points", "plot_dataset"])
            self.assertEqual(plan["workflow_plan"][0]["validated_tool_args"]["x_col"], "lon")
            self.assertEqual(plan["workflow_plan"][0]["validated_tool_args"]["y_col"], "lat")
            self.assertEqual(plan["workflow_plan"][1]["validated_tool_args"]["dataset_name"], "$steps.make_points.outputs.result_dataset")
            self.assertEqual(plan["workflow_plan"][1]["validated_tool_args"]["column"], "pop_density")

    def test_planner_clarifies_csv_mapping_when_coordinate_fields_are_missing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"xcoord": [0, 1], "pop_density": [12.0, 20.0]}))
            context = {
                "workspace": {"dataset_count": 1},
                "active_dataset": {"name": "stations", "type": "table"},
                "available_fields": ["xcoord", "pop_density"],
                "numeric_fields": ["xcoord", "pop_density"],
                "available_datasets": [{"name": "stations", "type": "table", "path": "stations.csv"}],
            }
            intent = {"intent": "map_generation", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("plot population density map", intent, context, manager=service.manager)

            self.assertTrue(plan["should_ask_clarification"])
            self.assertIn("coordinate field", " ".join(plan["missing_inputs"]))
            self.assertEqual(plan["workflow_plan"], [])

    def test_service_uses_deterministic_workflow_for_clip_then_map(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)

            with mock.patch.object(service, "_get_agent", side_effect=AssertionError("LLM should not be called")):
                result = service.ask(
                    "clip this shp to the study area, then plot population density map and explain",
                    frontend_context={"active_dataset_id": "points", "selected_layer_id": "study_area"},
                )

            self.assertEqual(result["mode"], "deterministic_workflow")
            self.assertTrue(result["images"])
            self.assertTrue(Path(result["images"][0]).exists())
            self.assertIn("points_clipped", service.manager.datasets)

    def test_modeling_workflow_succeeds_and_registers_model_result(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_model_table(service, rows=30)
            intent = {"intent": "modeling", "confidence": 0.86, "secondary_intents": ["result_analysis"]}

            plan = build_task_plan(
                "use rainfall and elevation to predict NDVI with random forest and explain",
                intent,
                self.modeling_context(),
                manager=service.manager,
            )
            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            self.assertEqual([step["step_id"] for step in result["steps"]], ["check_dataset", "field_match", "train_model", "interpret_model_result"])
            train_step = next(step for step in result["steps"] if step["step_id"] == "train_model")
            model_result_id = train_step["tool_result"]["outputs"]["model_result_id"]
            self.assertTrue(model_result_id)
            self.assertIsNotNone(service.manager.get_model_result(model_result_id))
            self.assertTrue(any(artifact["type"] == "metrics" for artifact in result["final_artifacts"]))
            reply = interpret_result("explain model", intent, plan, execution["raw_reply"], self.modeling_context(), {})
            self.assertIn(model_result_id, reply)
            self.assertIn("metrics", reply.lower())

    def test_missing_target_variable_does_not_create_modeling_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_model_table(service, rows=30)
            intent = {"intent": "modeling", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("build a model", intent, self.modeling_context(), manager=service.manager)

            self.assertTrue(plan["should_ask_clarification"])
            self.assertIn("target column", plan["missing_inputs"])
            self.assertEqual(plan["workflow_plan"], [])

    def test_modeling_workflow_failure_identifies_train_step_and_skips_interpretation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_model_table(service, rows=10)
            plan = {
                "workflow_plan": [
                    {"step_id": "check_dataset", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": "model_table"}},
                    {
                        "step_id": "train_model",
                        "tool_name": "train_rf_fusion_model",
                        "step_type": "modeling",
                        "depends_on": ["check_dataset"],
                        "validated_tool_args": {
                            "dataset_name": "model_table",
                            "target_col": "ndvi",
                            "feature_cols": "rainfall,elevation",
                            "output_name": "model_table_model",
                        },
                    },
                    {
                        "step_id": "interpret_model_result",
                        "tool_name": "interpret_result",
                        "depends_on": ["train_model"],
                        "validated_tool_args": {"referenced_step": "train_model"},
                    },
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertFalse(execution["ok"])
            self.assertEqual(result["failed_step"], "train_model")
            self.assertEqual(result["steps"][2]["status"], "skipped")

    def test_map_artifact_can_be_exported_to_png(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "generate_map",
                        "tool_name": "plot_dataset",
                        "validated_tool_args": {
                            "dataset_name": "points",
                            "column": "pop_density",
                            "output_name": "points_map.png",
                        },
                    },
                    {
                        "step_id": "export_map",
                        "tool_name": "export_artifact",
                        "step_type": "export_map",
                        "depends_on": ["generate_map"],
                        "validated_tool_args": {
                            "source_path": "$steps.generate_map.artifacts.0.path",
                            "output_path": str(service.manager.derived_dir / "exports" / "points_map_export.png"),
                        },
                    },
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            export_step = next(step for step in result["steps"] if step["step_id"] == "export_map")
            exported_path = Path(export_step["tool_result"]["outputs"]["path"])
            self.assertTrue(exported_path.exists())
            self.assertEqual(exported_path.suffix.lower(), ".png")
            reply = interpret_result("export map", {"intent": "data_processing"}, plan, execution["raw_reply"], {"active_dataset": {"name": "points"}}, {})
            self.assertIn(str(exported_path), reply)

    def test_vector_clip_result_can_be_exported_to_shapefile_zip(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "clip_vector",
                        "tool_name": "vector_clip_by_vector",
                        "validated_tool_args": {"dataset_name": "points", "clip_name": "study_area", "output_name": "points_clipped"},
                    },
                    {
                        "step_id": "export_vector",
                        "tool_name": "export_dataset",
                        "step_type": "export_vector",
                        "depends_on": ["clip_vector"],
                        "validated_tool_args": {
                            "dataset_name": "$steps.clip_vector.outputs.result_dataset",
                            "output_path": str(service.manager.derived_dir / "exports" / "points_clipped.shp"),
                        },
                    },
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            export_step = next(step for step in result["steps"] if step["step_id"] == "export_vector")
            exported_path = Path(export_step["tool_result"]["outputs"]["path"])
            self.assertEqual(exported_path.suffix.lower(), ".zip")
            self.assertTrue(exported_path.exists())
            with zipfile.ZipFile(exported_path) as archive:
                names = set(archive.namelist())
            self.assertIn("points_clipped.shp", names)
            self.assertIn("points_clipped.shx", names)
            self.assertIn("points_clipped.dbf", names)
            self.assertTrue(any(artifact["type"] == "file" for artifact in result["final_artifacts"]))

    def test_export_failure_does_not_remove_previous_map_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_clip_map_data(service)
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "generate_map",
                        "tool_name": "plot_dataset",
                        "validated_tool_args": {"dataset_name": "points", "column": "pop_density", "output_name": "safe_map.png"},
                    },
                    {
                        "step_id": "export_map",
                        "tool_name": "export_artifact",
                        "step_type": "export_map",
                        "depends_on": ["generate_map"],
                        "validated_tool_args": {"source_path": "", "output_path": str(service.manager.derived_dir / "exports" / "bad.png")},
                    },
                ]
            }

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])
            map_step = next(step for step in result["steps"] if step["step_id"] == "generate_map")

            self.assertFalse(execution["ok"])
            self.assertEqual(result["failed_step"], "export_map")
            self.assertTrue(Path(map_step["tool_result"]["artifacts"][0]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
