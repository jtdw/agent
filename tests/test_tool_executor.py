from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

from core.config import Settings
from core.conversation_intent import classify_user_intent
from core.context_builder import build_conversation_context
from core.conversation_state import ConversationState
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.tool_contracts import parse_tool_result
from core.tool_executor import execute_validated_tool_plan


class ToolExecutorTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_data_upload_analysis_plan_executes_describe_dataset(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"population": [10, 20], "rainfall": [1.2, 2.5]}))
            context = {
                "workspace": {"dataset_count": 1},
                "active_dataset": {"name": "stations", "type": "table"},
                "available_fields": ["population", "rainfall"],
                "numeric_fields": ["population", "rainfall"],
            }
            intent = {"intent": "data_upload_analysis", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("check this dataset", intent, context, manager=service.manager)
            execution = execute_validated_tool_plan(service.manager, plan)

            self.assertIn("describe_dataset", plan["validated_tool_args"])
            self.assertTrue(execution["executed"])
            self.assertTrue(execution["ok"])
            self.assertEqual(execution["executed_tools"], ["describe_dataset"])
            result = parse_tool_result(execution["raw_reply"])
            self.assertIsNotNone(result)
            self.assertEqual(result["tool_name"], "describe_dataset")
            self.assertEqual(result["outputs"]["name"], "stations")

    def test_population_density_plan_executes_plot_dataset_and_returns_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector(
                "county",
                gpd.GeoDataFrame(
                    {"pop_density": [10.0, 20.0], "geometry": [Point(0, 0), Point(1, 1)]},
                    crs="EPSG:4326",
                ),
            )
            context = {
                "workspace": {"dataset_count": 1},
                "active_dataset": {"name": "county", "type": "vector"},
                "available_fields": ["pop_density", "geometry"],
                "numeric_fields": ["pop_density"],
            }
            intent = {"intent": "map_generation", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("plot population density map", intent, context, manager=service.manager)
            execution = execute_validated_tool_plan(service.manager, plan)

            self.assertTrue(execution["executed"])
            self.assertTrue(execution["ok"])
            result = parse_tool_result(execution["raw_reply"])
            self.assertIsNotNone(result)
            self.assertEqual(result["tool_name"], "plot_dataset")
            self.assertEqual(result["inputs"]["column"], "pop_density")
            self.assertEqual(result["artifacts"][0]["type"], "map")
            self.assertTrue(Path(result["artifacts"][0]["path"]).exists())

    def test_vector_clip_plan_executes_spatial_processing_tool(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector(
                "points",
                gpd.GeoDataFrame(
                    {"value": [1, 2, 3], "geometry": [Point(0, 0), Point(1, 1), Point(5, 5)]},
                    crs="EPSG:4326",
                ),
            )
            service.manager.put_vector(
                "study_area",
                gpd.GeoDataFrame({"name": ["a"], "geometry": [box(-1, -1, 2, 2)]}, crs="EPSG:4326"),
            )
            context = {
                "workspace": {"dataset_count": 2},
                "active_dataset": {"name": "points", "type": "vector"},
                "referenced_object": {"type": "dataset", "name": "study_area", "dataset_id": "study_area"},
            }
            intent = {"intent": "data_processing", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("clip this shp to the study area", intent, context, manager=service.manager)
            execution = execute_validated_tool_plan(service.manager, plan)

            self.assertTrue(execution["executed"])
            self.assertTrue(execution["ok"])
            result = parse_tool_result(execution["raw_reply"])
            self.assertIsNotNone(result)
            self.assertEqual(result["tool_name"], "vector_clip_by_vector")
            self.assertEqual(result["outputs"]["feature_count"], 2)
            self.assertIn(result["outputs"]["result_dataset"], service.manager.datasets)

    def test_non_allowlisted_validated_tool_is_not_executed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            plan = {
                "tool_plan": [{"tool_name": "train_xgboost_fusion_model", "args": {"dataset_name": "training"}}],
                "validated_tool_args": {"train_xgboost_fusion_model": {"dataset_name": "training"}},
            }

            execution = execute_validated_tool_plan(service.manager, plan)

            self.assertFalse(execution["executed"])
            self.assertFalse(execution["ok"])
            self.assertEqual(execution["executed_tools"], [])
            self.assertEqual(execution["skipped_tools"], ["train_xgboost_fusion_model"])

    def test_invalid_tool_output_is_wrapped_as_structured_failure(self) -> None:
        class BadTool:
            name = "describe_dataset"

            def invoke(self, args):
                return "plain text"

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            plan = {"tool_plan": [{"tool_name": "describe_dataset", "args": {"dataset_name": "x"}}]}

            with mock.patch("core.tool_executor.build_tools", return_value=[BadTool()]):
                execution = execute_validated_tool_plan(service.manager, plan)

            self.assertTrue(execution["executed"])
            self.assertFalse(execution["ok"])
            result = parse_tool_result(execution["raw_reply"])
            self.assertIsNotNone(result)
            self.assertEqual(result["error_code"], "INVALID_TOOL_RESULT")
            self.assertIn("describe_dataset", result["user_message"])

    def test_service_uses_deterministic_executor_before_llm_for_data_check(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"population": [10, 20], "rainfall": [1.2, 2.5]}))

            with mock.patch.object(service, "_get_agent", side_effect=AssertionError("LLM should not be called")):
                result = service.ask("check this dataset")

            self.assertEqual(result["mode"], "deterministic_tool")
            self.assertEqual(result["model"], "conversation-coordinator")
            self.assertIn("stations", result["reply"])

    def test_service_uses_deterministic_executor_before_llm_for_map_generation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector(
                "county",
                gpd.GeoDataFrame(
                    {"pop_density": [10.0, 20.0], "geometry": [Point(0, 0), Point(1, 1)]},
                    crs="EPSG:4326",
                ),
            )

            with mock.patch.object(service, "_get_agent", side_effect=AssertionError("LLM should not be called")):
                result = service.ask("plot population density map")

            self.assertEqual(result["mode"], "deterministic_tool")
            self.assertTrue(result["images"])
            self.assertTrue(Path(result["images"][0]).exists())

    def test_service_uses_deterministic_executor_before_llm_for_vector_clip(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector(
                "points",
                gpd.GeoDataFrame(
                    {"value": [1, 2, 3], "geometry": [Point(0, 0), Point(1, 1), Point(5, 5)]},
                    crs="EPSG:4326",
                ),
            )
            service.manager.put_vector(
                "study_area",
                gpd.GeoDataFrame({"name": ["a"], "geometry": [box(-1, -1, 2, 2)]}, crs="EPSG:4326"),
            )

            with mock.patch.object(service, "_get_agent", side_effect=AssertionError("LLM should not be called")):
                result = service.ask(
                    "clip this shp to the study area",
                    frontend_context={"active_dataset_id": "points", "selected_layer_id": "study_area"},
                )

            self.assertEqual(result["mode"], "deterministic_tool")
            self.assertIn("points_clipped", service.manager.datasets)


if __name__ == "__main__":
    unittest.main()
