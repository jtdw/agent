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
from shapely.geometry import box

from core.config import Settings
from core.domestic_sources.gscloud_adapter import plan_gscloud_dem_tiles
from core.domestic_sources.raster_postprocess import standardize_raster_download_result
from core.gis_tools import build_tools
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.tool_contracts import parse_tool_result
from core.workflow_executor import execute_workflow_plan, parse_workflow_result


class NextDataProcessingMigrationTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def tool_map(self, service: GISWorkspaceService):
        return {tool.name: tool for tool in build_tools(service.manager)}

    def write_tile(self, path: Path, *, west: float, values: np.ndarray) -> Path:
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="int16",
            crs="EPSG:4326",
            transform=from_origin(west, 2.0, 1.0, 1.0),
            nodata=-9999,
        ) as dst:
            dst.write(values.astype("int16"), 1)
        return path

    def write_projected_tile(self, path: Path, *, values: np.ndarray) -> Path:
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="float32",
            crs="EPSG:3857",
            transform=from_origin(0.0, float(values.shape[0]) * 30.0, 30.0, 30.0),
            nodata=-9999.0,
        ) as dst:
            dst.write(values.astype("float32"), 1)
        return path

    def raster_context(self, *datasets: tuple[str, str]) -> dict:
        active_name = datasets[0][0]
        return {
            "workspace": {"dataset_count": len(datasets)},
            "active_dataset": {"name": active_name, "type": "raster"},
            "available_datasets": [{"name": name, "type": "raster", "path": path} for name, path in datasets],
        }

    def seed_gcp_prediction_table(self, service: GISWorkspaceService, rows: int = 36) -> dict:
        dataset_name = service.manager.put_table(
            "xgb_sm_demo",
            pd.DataFrame(
                {
                    "soil_moisture": [float(i) / 100.0 for i in range(rows)],
                    "xgb_sm_demo_xgb": [float(i) / 100.0 + (0.002 if i % 2 else -0.001) for i in range(rows)],
                    "date": pd.date_range("2024-01-01", periods=rows, freq="D").astype(str),
                    "lon": [115.0 + i * 0.01 for i in range(rows)],
                    "lat": [41.0 + i * 0.01 for i in range(rows)],
                }
            ),
        )
        return {
            "model": "XGBoost",
            "output_prefix": "xgb_sm_demo",
            "result_dataset": dataset_name,
            "summary": {
                "dataset": "demo_xgboost_soil_moisture",
                "target_col": "soil_moisture",
                "prediction_column": "xgb_sm_demo_xgb",
                "date_col": "date",
            },
        }

    def test_raster_processing_tools_are_available(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            tools = self.tool_map(service)

            for name in ("raster_mosaic", "raster_reproject", "raster_algebra", "dem_terrain_derivatives"):
                self.assertIn(name, tools)

    def test_downloaded_nested_raster_archives_are_loaded_and_mosaicked(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raw_dir = service.manager.workdir / "domestic_downloads" / "gscloud"
            raw_dir.mkdir(parents=True, exist_ok=True)
            left = self.write_tile(raw_dir / "ASTGTM_N30E102T.img", west=0.0, values=np.array([[1, 2], [3, 4]]))
            right = self.write_tile(raw_dir / "ASTGTM_N30E103Y.img", west=2.0, values=np.array([[5, 6], [7, 8]]))
            left_zip = raw_dir / "ASTGTM_N30E102.img.zip"
            right_zip = raw_dir / "ASTGTM_N30E103.img.zip"
            with zipfile.ZipFile(left_zip, "w") as archive:
                archive.write(left, left.name)
            with zipfile.ZipFile(right_zip, "w") as archive:
                archive.write(right, right.name)
            batch_zip = raw_dir / "chengdu_dem_gscloud_batch.zip"
            with zipfile.ZipFile(batch_zip, "w") as archive:
                archive.write(left_zip, f"batch/{left_zip.name}")
                archive.write(right_zip, f"batch/{right_zip.name}")

            result = standardize_raster_download_result(
                service.manager,
                {"zip_path": str(batch_zip)},
                output_name="chengdu_dem",
                fail_on_mosaic_error=True,
            )

            self.assertEqual(result["dataset_name"], "chengdu_dem_mosaic")
            self.assertEqual(result["raster_standardization"]["action"], "mosaicked")
            self.assertEqual(len(result["raster_standardization"]["source_datasets"]), 2)
            self.assertTrue(Path(result["final_output_path"]).exists())
            self.assertTrue(service.manager.get(result["dataset_name"]).meta["map_ready"])

    def test_raster_mosaic_tool_merges_dem_tiles_and_marks_map_ready(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = self.write_tile(Path(tmp) / "left.tif", west=0.0, values=np.array([[1, 2], [3, 4]]))
            right = self.write_tile(Path(tmp) / "right.tif", west=2.0, values=np.array([[5, 6], [7, 8]]))
            left_name = service.manager.put_raster_path("left_tile", left, meta={"crs": "EPSG:4326"})
            right_name = service.manager.put_raster_path("right_tile", right, meta={"crs": "EPSG:4326"})
            service.manager.put_vector("boundary", gpd.GeoDataFrame({"id": [1], "geometry": [box(0.5, 0.1, 3.5, 1.9)]}, crs="EPSG:4326"))

            raw = self.tool_map(service)["raster_mosaic"].invoke(
                {"raster_names": f"{left_name},{right_name}", "output_name": "merged_dem", "vector_name": "boundary"}
            )
            result = parse_tool_result(raw)

            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "raster_mosaic")
            self.assertEqual(result["outputs"]["dataset_name"], "merged_dem")
            self.assertTrue(service.manager.get("merged_dem").meta["map_ready"])

    def test_raster_mosaic_prompt_builds_and_executes_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = self.write_tile(Path(tmp) / "left.tif", west=0.0, values=np.array([[1, 2], [3, 4]]))
            right = self.write_tile(Path(tmp) / "right.tif", west=2.0, values=np.array([[5, 6], [7, 8]]))
            left_name = service.manager.put_raster_path("dem_left", left, meta={"crs": "EPSG:4326"})
            right_name = service.manager.put_raster_path("dem_right", right, meta={"crs": "EPSG:4326"})
            context = self.raster_context((left_name, str(left)), (right_name, str(right)))
            intent = {"intent": "data_processing", "confidence": 0.9, "secondary_intents": []}

            plan = build_task_plan("\u628a\u8fd9\u4e24\u4e2a DEM \u5206\u5e45\u62fc\u63a5\u6210\u4e00\u4e2a\u6807\u51c6\u5f71\u50cf", intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            args = plan["validated_tool_args"]["raster_mosaic"]
            self.assertEqual(args["raster_names"], "dem_left,dem_right")
            execution = execute_workflow_plan(service.manager, plan)

            self.assertTrue(execution["ok"])
            self.assertIn("dem_mosaic", service.manager.datasets)

    def test_dem_tile_plan_supports_srtm_utm_scheme(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            result = plan_gscloud_dem_tiles(
                service.manager,
                region="Chengdu",
                output_name="chengdu_srtm90_tiles",
                product_key="srtmdemutm_90m",
            )

            self.assertEqual(result["product_key"], "srtmdemutm_90m")
            self.assertEqual(result["dataset_id"], "306")
            self.assertEqual(result["pid"], "302")
            self.assertEqual(result["tile_scheme"], "srtm_utm_5deg")
            self.assertEqual(result["tile_ids"], ["utm_srtm_57_06"])

    def test_dem_tile_plan_dataset_id_overrides_default_product_key(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            result = plan_gscloud_dem_tiles(
                service.manager,
                region="Chengdu",
                output_name="chengdu_srtm90_tiles",
                dataset_id="306",
            )

            self.assertEqual(result["product_key"], "srtmdemutm_90m")
            self.assertEqual(result["tile_scheme"], "srtm_utm_5deg")

    def test_gcp_prompt_builds_and_executes_uncertainty_workflow_from_recent_model(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            recent_model = self.seed_gcp_prediction_table(service)
            context = {
                "workspace": {"dataset_count": 2},
                "active_dataset": {"name": "xgb_sm_demo", "type": "table"},
                "available_fields": ["soil_moisture", "xgb_sm_demo_xgb", "date", "lon", "lat"],
                "numeric_fields": ["soil_moisture", "xgb_sm_demo_xgb", "lon", "lat"],
                "recent_model_result": recent_model,
            }
            intent = {"intent": "modeling", "confidence": 0.86, "secondary_intents": []}

            plan = build_task_plan("做 GCP 不确定性分析。", intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            self.assertIn("geographical_conformal_prediction", plan["validated_tool_args"])
            args = plan["validated_tool_args"]["geographical_conformal_prediction"]
            self.assertEqual(args["calibration_dataset"], "xgb_sm_demo")
            self.assertEqual(args["observed_col"], "soil_moisture")
            self.assertEqual(args["predicted_cols"], "xgb_sm_demo_xgb")
            self.assertEqual(args["date_col"], "date")

            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            gcp_step = next(step for step in result["steps"] if step["step_id"] == "run_gcp")
            self.assertEqual(gcp_step["tool_result"]["tool_name"], "geographical_conformal_prediction")
            self.assertEqual(gcp_step["tool_result"]["outputs"]["metrics_dataset"], "xgb_sm_demo_gcp_gcp_metrics")

    def test_dem_derivative_prompt_blocks_geographic_crs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            dem_path = self.write_tile(Path(tmp) / "dem.tif", west=0.0, values=np.array([[10, 12], [14, 18]]))
            dem_name = service.manager.put_raster_path("county_dem", dem_path, meta={"crs": "EPSG:4326"})
            context = self.raster_context((dem_name, str(dem_path)))
            intent = {"intent": "data_processing", "confidence": 0.9, "secondary_intents": []}

            plan = build_task_plan("计算这个 DEM 的坡度和坡向", intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            self.assertIn("dem_terrain_derivatives", plan["validated_tool_args"])
            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertFalse(execution["ok"])
            step = next(item for item in result["steps"] if item["tool_name"] == "dem_terrain_derivatives")
            self.assertEqual(step["tool_result"]["error_code"], "DEM_PROJECTED_CRS_REQUIRED")

    def test_dem_derivative_projected_raster_executes_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            dem_path = self.write_projected_tile(Path(tmp) / "dem_3857.tif", values=np.array([[10, 12], [14, 18]], dtype="float32"))
            dem_name = service.manager.put_raster_path("county_dem", dem_path, meta={"crs": "EPSG:3857"})
            context = self.raster_context((dem_name, str(dem_path)))
            intent = {"intent": "data_processing", "confidence": 0.9, "secondary_intents": []}

            plan = build_task_plan("计算这个 DEM 的坡度和坡向", intent, context, manager=service.manager)
            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertTrue(execution["ok"])
            step = next(item for item in result["steps"] if item["tool_name"] == "dem_terrain_derivatives")
            self.assertIn("county_dem_slope", step["tool_result"]["outputs"]["datasets"])
            self.assertIn("county_dem_aspect", step["tool_result"]["outputs"]["datasets"])

    def test_dem_twi_tpi_prompt_routes_to_terrain_derivatives(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            dem_path = self.write_projected_tile(
                Path(tmp) / "dem_3857.tif",
                values=np.array(
                    [
                        [120, 118, 116, 114],
                        [118, 116, 114, 112],
                        [116, 114, 112, 110],
                        [114, 112, 110, 108],
                    ],
                    dtype="float32",
                ),
            )
            dem_name = service.manager.put_raster_path("county_dem", dem_path, meta={"crs": "EPSG:3857"})
            context = self.raster_context((dem_name, str(dem_path)))
            intent = {"intent": "data_processing", "confidence": 0.9, "secondary_intents": []}

            plan = build_task_plan("\u8ba1\u7b97\u8fd9\u4e2a DEM \u7684 TWI \u548c TPI \u5730\u5f62\u56e0\u5b50", intent, context, manager=service.manager)
            execution = execute_workflow_plan(service.manager, plan)
            result = parse_workflow_result(execution["raw_reply"])

            self.assertFalse(plan["should_ask_clarification"])
            self.assertEqual(plan["validated_tool_args"]["dem_terrain_derivatives"]["derivatives"], "tpi,twi")
            self.assertTrue(execution["ok"], result)
            step = next(item for item in result["steps"] if item["tool_name"] == "dem_terrain_derivatives")
            self.assertEqual(set(step["tool_result"]["outputs"]["derivatives"]), {"tpi", "twi"})
            self.assertIn("county_dem_terrain", step["tool_result"]["outputs"]["datasets"])
            self.assertIn("county_dem_twi", step["tool_result"]["outputs"]["datasets"])

    def test_raster_reproject_prompt_builds_and_executes_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_tile(Path(tmp) / "dem.tif", west=0.0, values=np.array([[1, 2], [3, 4]]))
            raster_name = service.manager.put_raster_path("county_dem", raster_path, meta={"crs": "EPSG:4326"})
            context = self.raster_context((raster_name, str(raster_path)))
            intent = {"intent": "data_processing", "confidence": 0.9, "secondary_intents": []}

            plan = build_task_plan("把这个栅格重投影到 EPSG:3857", intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            args = plan["validated_tool_args"]["raster_reproject"]
            self.assertEqual(args["target_crs"], "EPSG:3857")
            execution = execute_workflow_plan(service.manager, plan)

            self.assertTrue(execution["ok"])
            self.assertIn("county_dem_3857", service.manager.datasets)

    def test_raster_algebra_prompt_builds_and_executes_workflow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            nir_path = self.write_tile(Path(tmp) / "nir.tif", west=0.0, values=np.array([[8, 10], [12, 14]]))
            red_path = self.write_tile(Path(tmp) / "red.tif", west=0.0, values=np.array([[2, 4], [5, 7]]))
            nir_name = service.manager.put_raster_path("nir_band", nir_path, meta={"crs": "EPSG:4326"})
            red_name = service.manager.put_raster_path("red_band", red_path, meta={"crs": "EPSG:4326"})
            context = self.raster_context((nir_name, str(nir_path)), (red_name, str(red_path)))
            intent = {"intent": "data_processing", "confidence": 0.9, "secondary_intents": []}

            plan = build_task_plan("计算 NDVI = (nir - red) / (nir + red)", intent, context, manager=service.manager)

            self.assertFalse(plan["should_ask_clarification"])
            args = plan["validated_tool_args"]["raster_algebra"]
            self.assertEqual(args["input_rasters"], "nir=nir_band,red=red_band")
            execution = execute_workflow_plan(service.manager, plan)

            self.assertTrue(execution["ok"])
            self.assertIn("ndvi", service.manager.datasets)


if __name__ == "__main__":
    unittest.main()
