from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box

from core.config import Settings
from core.plan_validator import validate_task_plan_before_execution
from core.service import GISWorkspaceService
from core.tool_cards import candidate_tool_cards, list_tool_cards
from core.tool_contracts import parse_tool_result
from core.tool_executor import DEFAULT_DETERMINISTIC_TOOLS, execute_validated_tool_plan


class CoreGisWorkflowCompletionTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def write_raster(self, path: Path, *, crs: str = "EPSG:3857", values: np.ndarray | None = None, nodata: float = -9999.0) -> Path:
        arr = values if values is not None else np.arange(25, dtype="float32").reshape(5, 5)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=arr.shape[0],
            width=arr.shape[1],
            count=1,
            dtype="float32",
            crs=crs,
            transform=from_origin(0, arr.shape[0] * 30, 30, 30),
            nodata=nodata,
        ) as dst:
            dst.write(arr.astype("float32"), 1)
        return path

    def tool_map(self, service: GISWorkspaceService):
        from core.tools.registry import build_tools

        return {tool.name: tool for tool in build_tools(service.manager)}

    def test_tool_cards_cover_core_gis_completion_tools(self) -> None:
        cards = {card["tool_name"]: card for card in list_tool_cards()}
        expected = {
            "dem_terrain_derivatives",
            "raster_algebra",
            "raster_reproject",
            "raster_zonal_stats",
            "clip_raster_by_vector",
            "vector_buffer",
            "vector_spatial_join",
            "extract_raster_values_to_points",
            "batch_register_points_to_rasters",
        }
        self.assertTrue(expected.issubset(cards))
        for name in expected:
            self.assertIn("ToolResult/v1", str(cards[name].get("result_schema")))
            self.assertTrue(cards[name].get("preconditions"), name)
            self.assertTrue(cards[name].get("forbidden_uses"), name)
        dem_card_text = str(cards["dem_terrain_derivatives"]).lower()
        self.assertIn("twi", dem_card_text)
        self.assertIn("dem-only", dem_card_text)
        self.assertIn("d8", dem_card_text)

        candidate_names = {card["tool_name"] for card in candidate_tool_cards("DEM 坡度 NDVI 栅格计算 缓冲区 空间连接 站点 栅格 采样", task_type="data_processing", limit=20)}
        self.assertTrue(expected & candidate_names)
        terrain_candidate_names = {card["tool_name"] for card in candidate_tool_cards("soil moisture DEM TWI terrain factor", task_type="modeling", limit=8)}
        self.assertIn("dem_terrain_derivatives", terrain_candidate_names)

    def test_chinese_tool_card_retrieval_includes_sampling_prerequisite_tools(self) -> None:
        names = {
            card["tool_name"]
            for card in candidate_tool_cards("提取每个站点的栅格值并生成可下载表格", task_type="data_processing", limit=8)
        }
        self.assertIn("table_to_points", names)
        self.assertIn("extract_raster_values_to_points", names)

    def test_validator_accepts_core_gis_operations_and_blocks_mismatched_tool(self) -> None:
        context = {"candidate_tool_cards": [{"tool_name": "raster_algebra"}, {"tool_name": "submit_commercial_download_job"}]}
        plan = {
            "primary_goal": "ndvi_calculation",
            "operation": "raster_calculation",
            "selected_tools": ["raster_algebra"],
            "tool_plan": [{"tool_name": "raster_algebra", "args": {"expression": "(nir-red)/(nir+red)", "input_rasters": "nir=nir,red=red", "output_name": "ndvi"}}],
            "requested_downloads": [],
        }
        self.assertTrue(validate_task_plan_before_execution(plan, context)["ok"])

        bad = {**plan, "selected_tools": ["submit_commercial_download_job"], "tool_plan": [{"tool_name": "submit_commercial_download_job", "args": {}}]}
        result = validate_task_plan_before_execution(bad, context)
        self.assertFalse(result["ok"])
        self.assertIn("DOWNLOAD_TOOL_WITHOUT_REQUESTED_DOWNLOADS", {error["code"] for error in result["errors"]})

    def test_default_executor_allows_core_gis_tools(self) -> None:
        expected = {
            "dem_terrain_derivatives",
            "raster_algebra",
            "raster_reproject",
            "clip_raster_by_vector",
            "vector_buffer",
            "vector_spatial_join",
            "extract_raster_values_to_points",
            "batch_register_points_to_rasters",
        }
        self.assertTrue(expected.issubset(DEFAULT_DETERMINISTIC_TOOLS))

    def test_dem_terrain_blocks_geographic_crs_and_creates_slope_aspect_for_projected_dem(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            geo_path = self.write_raster(Path(tmp) / "dem_geo.tif", crs="EPSG:4326")
            service.manager.put_raster_path("dem_geo", geo_path, meta={"crs": "EPSG:4326"})
            tools = self.tool_map(service)

            failed = parse_tool_result(tools["dem_terrain_derivatives"].invoke({"dem_name": "dem_geo", "output_prefix": "bad", "derivatives": "slope"}))
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["error_code"], "DEM_PROJECTED_CRS_REQUIRED")

            dem_path = self.write_raster(Path(tmp) / "dem_3857.tif", crs="EPSG:3857")
            service.manager.put_raster_path("dem_3857", dem_path, meta={"crs": "EPSG:3857"})
            result = parse_tool_result(
                tools["dem_terrain_derivatives"].invoke(
                    {"dem_name": "dem_3857", "output_prefix": "terrain", "derivatives": "slope,aspect", "slope_units": "percent"}
                )
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "dem_terrain_derivatives")
            self.assertEqual(result["outputs"]["slope_units"], "percent")
            self.assertEqual(set(result["outputs"]["derivatives"]), {"slope", "aspect"})
            self.assertGreaterEqual(len(result["artifacts"]), 2)
            for artifact in result["artifacts"]:
                self.assertTrue(Path(artifact["path"]).exists())

    def test_dem_terrain_derivatives_creates_dem_only_twi(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            values = np.array(
                [
                    [120, 118, 116, 114, 112],
                    [118, 116, 114, 112, 110],
                    [116, 114, 112, 110, 108],
                    [114, 112, 110, 108, 106],
                    [112, 110, 108, 106, 104],
                ],
                dtype="float32",
            )
            dem_path = self.write_raster(Path(tmp) / "dem_3857.tif", crs="EPSG:3857", values=values)
            service.manager.put_raster_path("dem_3857", dem_path, meta={"crs": "EPSG:3857"})
            tools = self.tool_map(service)

            result = parse_tool_result(
                tools["dem_terrain_derivatives"].invoke(
                    {"dem_name": "dem_3857", "output_prefix": "terrain", "derivatives": "slope,tpi,twi"}
                )
            )

            self.assertTrue(result["ok"], result)
            self.assertEqual(set(result["outputs"]["derivatives"]), {"slope", "tpi", "twi"})
            self.assertIn("terrain_twi", result["outputs"]["datasets"])
            self.assertEqual(result["diagnostics"]["hydrology_method"], "dem_only_d8")
            self.assertEqual(result["outputs"]["statistics"]["twi"]["valid_count"], 25)
            with rasterio.open(service.manager.get_raster_path("terrain_twi")) as src:
                twi = src.read(1)
                self.assertTrue(np.isfinite(twi[twi != src.nodata]).all())
                self.assertGreater(float(np.nanmax(np.where(twi == src.nodata, np.nan, twi))), 0.0)

    def test_raster_algebra_ndvi_and_point_sampling_return_real_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            red = self.write_raster(Path(tmp) / "red.tif", values=np.full((5, 5), 0.2, dtype="float32"))
            nir = self.write_raster(Path(tmp) / "nir.tif", values=np.full((5, 5), 0.6, dtype="float32"))
            service.manager.put_raster_path("red", red, meta={"crs": "EPSG:3857"})
            service.manager.put_raster_path("nir", nir, meta={"crs": "EPSG:3857"})
            service.manager.put_vector("sites", gpd.GeoDataFrame({"site_id": ["a"]}, geometry=[Point(45, 105)], crs="EPSG:3857"))
            tools = self.tool_map(service)

            ndvi = parse_tool_result(
                tools["raster_algebra"].invoke(
                    {"expression": "(nir - red) / (nir + red)", "input_rasters": "nir=nir,red=red", "output_name": "ndvi"}
                )
            )
            self.assertTrue(ndvi["ok"])
            self.assertAlmostEqual(ndvi["outputs"]["statistics"]["mean"], 0.5, places=5)
            self.assertTrue(Path(ndvi["artifacts"][0]["path"]).exists())

            sampled = parse_tool_result(
                tools["extract_raster_values_to_points"].invoke(
                    {"point_name": "sites", "raster_name": "ndvi", "output_name": "sites_ndvi", "field_name": "ndvi", "method": "nearest"}
                )
            )
            self.assertTrue(sampled["ok"])
            self.assertEqual(sampled["outputs"]["result_dataset"], "sites_ndvi")
            self.assertEqual(sampled["diagnostics"]["missing_count"], 0)

    def test_raster_reproject_accepts_validated_target_resolution(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raster_path = self.write_raster(Path(tmp) / "source.tif", crs="EPSG:3857")
            service.manager.put_raster_path("source_raster", raster_path, meta={"crs": "EPSG:3857"})
            tools = self.tool_map(service)

            result = parse_tool_result(
                tools["raster_reproject"].invoke(
                    {
                        "raster_name": "source_raster",
                        "target_crs": "EPSG:3857",
                        "output_name": "source_60m",
                        "resampling": "nearest",
                        "target_resolution": "60,60",
                    }
                )
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_name"], "raster_reproject")
            self.assertEqual(result["outputs"]["target_resolution"], [60.0, 60.0])
            self.assertEqual(result["diagnostics"]["source_resolution"], [30.0, 30.0])
            self.assertEqual(result["diagnostics"]["target_resolution"], [60.0, 60.0])
            self.assertEqual(result["diagnostics"]["resampling"], "nearest")
            self.assertTrue(Path(result["artifacts"][0]["path"]).exists())

    def test_validator_rejects_invalid_raster_reproject_target_resolution(self) -> None:
        plan = {
            "operation": "raster_reproject",
            "selected_tools": ["raster_reproject"],
            "workflow_plan": [
                {
                    "step_id": "step-reproject",
                    "tool_name": "raster_reproject",
                    "args": {
                        "raster_name": "source_raster",
                        "target_crs": "EPSG:3857",
                        "output_name": "bad_resolution",
                        "resampling": "nearest",
                        "target_resolution": "-30,30",
                    },
                }
            ],
            "requested_downloads": [],
        }
        result = validate_task_plan_before_execution(plan, {"candidate_tool_cards": [{"tool_name": "raster_reproject"}]})
        self.assertFalse(result["ok"])
        self.assertIn("TARGET_RESOLUTION_INVALID", {error["code"] for error in result["errors"]})
        self.assertIn("raster_reproject", result["blocked_tools"])

    def test_vector_buffer_spatial_join_and_executor_use_validated_plan(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_vector("sites", gpd.GeoDataFrame({"site_id": ["a"]}, geometry=[Point(0, 0)], crs="EPSG:4326"))
            service.manager.put_vector("zones", gpd.GeoDataFrame({"zone": ["z1"]}, geometry=[box(-1, -1, 1, 1)], crs="EPSG:4326"))
            plan = {
                "operation": "vector_buffer",
                "selected_tools": ["vector_buffer"],
                "tool_plan": [{"tool_name": "vector_buffer", "args": {"dataset_name": "sites", "distance": 100, "unit": "meter", "output_name": "sites_buffer"}}],
                "validated_tool_args": {"vector_buffer": {"dataset_name": "sites", "distance": 100, "unit": "meter", "output_name": "sites_buffer"}},
                "requested_downloads": [],
            }
            execution = execute_validated_tool_plan(service.manager, plan)
            self.assertTrue(execution["ok"])
            self.assertEqual(execution["executed_tools"], ["vector_buffer"])

            tools = self.tool_map(service)
            joined = parse_tool_result(
                tools["vector_spatial_join"].invoke(
                    {"target_name": "sites", "join_name": "zones", "predicate": "within", "output_name": "sites_joined", "field_conflict_strategy": "suffix"}
                )
            )
            self.assertTrue(joined["ok"])
            self.assertEqual(joined["outputs"]["result_dataset"], "sites_joined")
            self.assertIn("field_conflict_strategy", joined["diagnostics"])


if __name__ == "__main__":
    unittest.main()
