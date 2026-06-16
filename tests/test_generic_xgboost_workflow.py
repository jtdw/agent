from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from core.config import Settings
from core.gis_tools import build_tools
from core.map_layers import MapLayerService
from core.service import GISWorkspaceService
from core.tool_contracts import parse_tool_result


class GenericXGBoostWorkflowTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def tool_map(self, service: GISWorkspaceService):
        return {tool.name: tool for tool in build_tools(service.manager)}

    def table_df(self, rows: int = 80) -> pd.DataFrame:
        x = np.linspace(0, 1, rows)
        category = np.where(np.arange(rows) % 2 == 0, "plain", "ridge")
        return pd.DataFrame(
            {
                "id": [f"s{i}" for i in range(rows)],
                "lon": 100.0 + x,
                "lat": 30.0 + x,
                "dem": 100 + 40 * x,
                "ndvi": 0.2 + 0.5 * x,
                "rainfall": 30 + 10 * np.sin(x * np.pi),
                "landform": category,
                "target_regression": 5 + 2.5 * x + np.where(category == "ridge", 0.6, -0.2),
                "target_classification": np.where(x + (category == "ridge") * 0.2 > 0.55, "high", "low"),
            }
        )

    def write_raster(self, path: Path, data: np.ndarray, *, west: float = 100.0, north: float = 31.0, res: float = 0.01) -> Path:
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype=str(data.dtype),
            crs="EPSG:4326",
            transform=from_origin(west, north, res, res),
            nodata=-9999.0,
        ) as dst:
            dst.write(data, 1)
        return path

    def test_csv_regression_outputs_metrics_importance_and_model_result(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("samples", self.table_df())

            raw = self.tool_map(service)["generic_xgboost_workflow"].invoke(
                {
                    "dataset_name": "samples",
                    "target_col": "target_regression",
                    "feature_cols": "dem,ndvi,rainfall,landform",
                    "output_name": "generic_regression",
                    "task_type": "regression",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["model_type"], "regression")
            self.assertIn("R2", result["outputs"]["metrics"])
            self.assertIn("RMSE", result["outputs"]["metrics"])
            self.assertIn("MAE", result["outputs"]["metrics"])
            self.assertTrue(result["outputs"]["model_result_id"])
            self.assertTrue(result["outputs"]["importance_dataset"])
            self.assertTrue(result["artifacts"])

    def test_csv_classification_outputs_classification_metrics(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("samples", self.table_df())

            raw = self.tool_map(service)["generic_xgboost_workflow"].invoke(
                {
                    "dataset_name": "samples",
                    "target_col": "target_classification",
                    "feature_cols": "dem,ndvi,rainfall,landform",
                    "output_name": "generic_classification",
                    "task_type": "classification",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["model_type"], "classification")
            self.assertIn("Accuracy", result["outputs"]["metrics"])
            self.assertIn("F1", result["outputs"]["metrics"])
            self.assertIn("AUC", result["outputs"]["metrics"])

    def test_vector_regression_registers_prediction_geojson_as_map_layer(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            df = self.table_df(60)
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326")
            service.manager.put_vector("point_samples", gdf)

            raw = self.tool_map(service)["generic_xgboost_workflow"].invoke(
                {
                    "dataset_name": "point_samples",
                    "target_col": "target_regression",
                    "feature_cols": "dem,ndvi,rainfall,landform",
                    "output_name": "generic_points_prediction",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["outputs"]["map_layer_id"].startswith("dataset_"))
            layers = MapLayerService(service).workspace_layers(user_id="u_test")["layers"]
            self.assertTrue(any(layer["dataset_name"] == result["outputs"]["result_dataset"] for layer in layers))

    def test_missing_target_returns_structured_question(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("samples", self.table_df())

            raw = self.tool_map(service)["generic_xgboost_workflow"].invoke({"dataset_name": "samples"})
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "TARGET_REQUIRED")
            self.assertIn("target", result["diagnostics"]["required_inputs"])

    def test_point_samples_extract_multiple_raster_features(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            points = gpd.GeoDataFrame(
                {
                    "target": np.linspace(1, 3, 30),
                    "geometry": [Point(100.05 + (i % 5) * 0.04, 30.95 - (i // 5) * 0.04) for i in range(30)],
                },
                crs="EPSG:4326",
            )
            service.manager.put_vector("sample_points", points)
            grid = np.arange(100, dtype="float32").reshape(10, 10)
            dem = service.manager.put_raster_path("dem", self.write_raster(root / "dem.tif", grid))
            ndvi = service.manager.put_raster_path("ndvi", self.write_raster(root / "ndvi.tif", grid / 100))

            raw = self.tool_map(service)["generic_xgboost_workflow"].invoke(
                {
                    "mode": "sample_raster",
                    "sample_dataset_name": "sample_points",
                    "target_col": "target",
                    "raster_names": f"{dem},{ndvi}",
                    "output_name": "point_raster_xgb",
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["task_mode"], "sample_raster")
            self.assertIn("dem", ",".join(result["diagnostics"]["features"]))
            self.assertTrue(result["outputs"]["result_dataset"])

    def test_raster_stack_target_raster_predicts_tif_and_layer(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            yy, xx = np.mgrid[0:20, 0:20].astype("float32")
            dem = service.manager.put_raster_path("dem", self.write_raster(root / "dem.tif", xx))
            ndvi = service.manager.put_raster_path("ndvi", self.write_raster(root / "ndvi.tif", yy / 20))
            target = service.manager.put_raster_path("target", self.write_raster(root / "target.tif", 2 * xx + yy / 20))

            raw = self.tool_map(service)["generic_xgboost_workflow"].invoke(
                {
                    "mode": "raster_stack",
                    "raster_names": f"{dem},{ndvi}",
                    "target_raster_name": target,
                    "output_name": "raster_prediction",
                    "max_prediction_pixels": 1000,
                }
            )
            result = parse_tool_result(raw)

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["outputs"]["task_mode"], "raster_stack")
            self.assertTrue(result["outputs"]["result_dataset"])
            self.assertTrue(result["outputs"]["map_layer_id"].startswith("dataset_"))
            with rasterio.open(service.manager.get_raster_path(result["outputs"]["result_dataset"])) as src:
                self.assertEqual((src.width, src.height), (20, 20))


if __name__ == "__main__":
    unittest.main()
