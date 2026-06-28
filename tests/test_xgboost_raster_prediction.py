from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box
from sklearn.linear_model import LinearRegression

from core.config import Settings
from core.gis_tools import build_tools
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.tool_cards import candidate_tool_cards, list_tool_cards
from core.tool_contracts import parse_tool_result
from core.workflow_executor import execute_workflow_plan, parse_workflow_result


FEATURES = ["dem_elevation", "lst_value", "ndvi_value", "lon", "lat", "day_of_year", "month", "year"]


class XGBoostRasterPredictionToolTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def write_raster(self, service: GISWorkspaceService, name: str, data: np.ndarray, transform=None) -> str:
        path = service.manager.derived_dir / f"{name}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform or from_origin(0, 4, 1, 1),
            nodata=-9999.0,
        ) as dst:
            dst.write(data.astype("float32"), 1)
        return service.manager.put_raster_path(name, path, meta={"crs": "EPSG:4326"})

    def write_model(self, path: Path) -> Path:
        train = pd.DataFrame(
            {
                "dem_elevation": [1.0, 2.0, 3.0, 4.0],
                "lst_value": [10.0, 11.0, 12.0, 13.0],
                "ndvi_value": [0.2, 0.3, 0.4, 0.5],
                "lon": [0.5, 1.5, 2.5, 3.5],
                "lat": [3.5, 2.5, 1.5, 0.5],
                "day_of_year": [196, 196, 196, 196],
                "month": [7, 7, 7, 7],
                "year": [2019, 2019, 2019, 2019],
            }
        )
        y = train["dem_elevation"] * 0.05 + train["lst_value"] * 0.01 + train["ndvi_value"] * 0.2
        model = LinearRegression().fit(train[FEATURES], y)
        joblib.dump({"pipeline": model, "features": FEATURES, "target": "soil_moisture_mean"}, path)
        return path

    def test_predict_xgboost_raster_map_writes_basin_prediction_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.write_raster(service, "dem", np.arange(1, 17, dtype="float32").reshape(4, 4))
            self.write_raster(service, "lst", np.full((4, 4), 12.0, dtype="float32"))
            self.write_raster(service, "ndvi", np.full((4, 4), 0.35, dtype="float32"))
            basin = gpd.GeoDataFrame({"name": ["basin"], "geometry": [box(0, 0, 2, 4)]}, crs="EPSG:4326")
            service.manager.put_vector("basin", basin)
            model_path = self.write_model(service.manager.derived_dir / "soil_model.joblib")
            tools = {tool.name: tool for tool in build_tools(service.manager)}

            raw = tools["predict_xgboost_raster_map"].invoke(
                {
                    "model_path": str(model_path),
                    "feature_rasters": "dem_elevation=dem,lst_value=lst,ndvi_value=ndvi",
                    "boundary_name": "basin",
                    "output_name": "soil_prediction",
                    "representative_date": "2019-07-15",
                    "max_prediction_pixels": 1000,
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["tool_name"], "predict_xgboost_raster_map")
            self.assertEqual(result["outputs"]["result_dataset"], "soil_prediction")
            self.assertEqual(result["outputs"]["representative_date"], "2019-07-15")
            self.assertEqual(result["outputs"]["valid_prediction_pixels"], 8)
            self.assertIn("soil_moisture_mean", result["outputs"]["target"])
            artifact_types = {artifact["type"] for artifact in result["artifacts"]}
            self.assertIn("raster", artifact_types)
            self.assertIn("png", artifact_types)
            self.assertIn("summary", artifact_types)
            self.assertTrue(result["map_layers"])

            raster_path = service.manager.get_raster_path("soil_prediction")
            with rasterio.open(raster_path) as src:
                arr = src.read(1)
                self.assertEqual(src.nodata, -9999.0)
                self.assertEqual(int(np.count_nonzero(arr != -9999.0)), 8)
                self.assertEqual(float(arr[0, 3]), -9999.0)
                self.assertGreater(float(arr[0, 0]), 0.0)

    def test_predict_xgboost_raster_map_can_use_explicit_target_grid(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.write_raster(service, "dem", np.arange(1, 17, dtype="float32").reshape(4, 4))
            self.write_raster(
                service,
                "lst",
                np.full((2, 2), 12.0, dtype="float32"),
                transform=from_origin(0, 4, 2, 2),
            )
            self.write_raster(service, "ndvi", np.full((4, 4), 0.35, dtype="float32"))
            model_path = self.write_model(service.manager.derived_dir / "soil_model.joblib")
            tools = {tool.name: tool for tool in build_tools(service.manager)}

            raw = tools["predict_xgboost_raster_map"].invoke(
                {
                    "model_path": str(model_path),
                    "feature_rasters": "dem_elevation=dem,lst_value=lst,ndvi_value=ndvi",
                    "target_raster_name": "lst",
                    "output_name": "soil_prediction_lst_grid",
                    "representative_date": "2019-07-15",
                    "max_prediction_pixels": 1000,
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["target_raster_name"], "lst")
            self.assertEqual(result["outputs"]["valid_prediction_pixels"], 4)
            self.assertEqual(result["diagnostics"]["reference_raster"], "lst")
            raster_path = service.manager.get_raster_path("soil_prediction_lst_grid")
            with rasterio.open(raster_path) as src:
                self.assertEqual((src.height, src.width), (2, 2))
                self.assertEqual(src.transform, from_origin(0, 4, 2, 2))

    def test_predict_xgboost_raster_map_defaults_to_coarsest_feature_grid(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.write_raster(service, "dem", np.arange(1, 17, dtype="float32").reshape(4, 4))
            self.write_raster(
                service,
                "lst",
                np.full((2, 2), 12.0, dtype="float32"),
                transform=from_origin(0, 4, 2, 2),
            )
            self.write_raster(service, "ndvi", np.full((4, 4), 0.35, dtype="float32"))
            model_path = self.write_model(service.manager.derived_dir / "soil_model.joblib")
            tools = {tool.name: tool for tool in build_tools(service.manager)}

            raw = tools["predict_xgboost_raster_map"].invoke(
                {
                    "model_path": str(model_path),
                    "feature_rasters": "dem_elevation=dem,lst_value=lst,ndvi_value=ndvi",
                    "output_name": "soil_prediction_coarse_grid",
                    "representative_date": "2019-07-15",
                    "max_prediction_pixels": 1000,
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["reference_raster"], "lst")
            self.assertEqual(result["diagnostics"]["reference_source"], "coarsest_feature_raster")
            self.assertEqual(result["outputs"]["valid_prediction_pixels"], 4)
            raster_path = service.manager.get_raster_path("soil_prediction_coarse_grid")
            with rasterio.open(raster_path) as src:
                self.assertEqual((src.height, src.width), (2, 2))
                self.assertEqual(src.transform, from_origin(0, 4, 2, 2))

    def test_predict_xgboost_raster_map_has_planner_tool_card(self) -> None:
        cards = {card["tool_name"]: card for card in list_tool_cards()}
        names = set(cards)
        candidates = {
            card["tool_name"]
            for card in candidate_tool_cards("XGBoost soil moisture full basin raster prediction map", task_type="modeling", limit=12)
        }

        self.assertIn("predict_xgboost_raster_map", names)
        self.assertIn("predict_xgboost_raster_map", candidates)
        card = cards["predict_xgboost_raster_map"]
        self.assertIn("target_raster_name", card["optional_inputs"])
        searchable_text = " ".join([card["capability"], *card["preconditions"], *card["common_failure_cases"]]).lower()
        self.assertIn("coarsest", searchable_text)
        self.assertIn("lowest-resolution", searchable_text)

    def test_planner_builds_and_executes_full_basin_xgboost_raster_prediction(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.write_raster(service, "dem", np.arange(1, 17, dtype="float32").reshape(4, 4))
            self.write_raster(service, "lst", np.full((4, 4), 12.0, dtype="float32"))
            self.write_raster(service, "ndvi", np.full((4, 4), 0.35, dtype="float32"))
            basin = gpd.GeoDataFrame({"name": ["basin"], "geometry": [box(0, 0, 2, 4)]}, crs="EPSG:4326")
            service.manager.put_vector("basin", basin)
            model_path = self.write_model(service.manager.derived_dir / "soil_model.joblib")
            context = {
                "workspace": {"dataset_count": 4},
                "active_dataset": {"name": "dem", "type": "raster"},
                "available_datasets": [
                    {"name": "dem", "type": "raster"},
                    {"name": "lst", "type": "raster"},
                    {"name": "ndvi", "type": "raster"},
                    {"name": "basin", "type": "vector"},
                ],
                "recent_artifacts": [
                    {"type": "model", "path": str(model_path), "title": "soil_model.joblib"},
                ],
                "candidate_tool_cards": [{"tool_name": "predict_xgboost_raster_map"}],
            }

            plan = build_task_plan(
                "use the existing XGBoost model to predict a full basin soil moisture raster map for 2019-07-15",
                {"intent": "modeling", "confidence": 0.92, "secondary_intents": []},
                context,
                manager=service.manager,
            )

            self.assertFalse(plan["should_ask_clarification"], plan)
            self.assertEqual(plan["recommended_tools"][0], "predict_xgboost_raster_map")
            args = plan["validated_tool_args"]["predict_xgboost_raster_map"]
            self.assertEqual(args["model_path"], str(model_path))
            self.assertEqual(args["feature_rasters"], "dem_elevation=dem,lst_value=lst,ndvi_value=ndvi")
            self.assertEqual(args["boundary_name"], "basin")
            self.assertEqual(args["representative_date"], "2019-07-15")
            self.assertEqual([step["tool_name"] for step in plan["workflow_plan"]], ["predict_xgboost_raster_map", "interpret_result"])

            execution = execute_workflow_plan(service.manager, plan)
            workflow_result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"], workflow_result)
            prediction_step = workflow_result["steps"][0]
            self.assertEqual(prediction_step["tool_result"]["tool_name"], "predict_xgboost_raster_map")
            self.assertTrue(any(artifact["type"] == "raster" for artifact in workflow_result["final_artifacts"]))


if __name__ == "__main__":
    unittest.main()
