from __future__ import annotations

import unittest
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

import api_server
from core.config import Settings
from core.data_manager import DataManager
from core.domestic_sources.gscloud_adapter import plan_gscloud_dem_tiles
from core.task_planner import build_task_plan


class GSCloudDemRegionRoutingTests(unittest.TestCase):
    def test_extracts_admin_region_before_compact_90m_dem_product_text(self) -> None:
        prompt = "\u5e2e\u6211\u4e0b\u8f7d\u8d44\u9633\u5e02\u768490mdem\u6570\u636e"

        self.assertEqual(api_server._extract_region_from_prompt(prompt), "\u8d44\u9633\u5e02")

    def test_90m_dem_prompt_selects_srtm_dataset(self) -> None:
        prompt = "\u4e0b\u8f7d\u8d44\u9633\u5e02\u7684 SRTM 90M DEM"

        self.assertEqual(api_server._extract_gscloud_dem_dataset_id_from_prompt(prompt), "306")

    def test_extracts_admin_region_after_processing_verb_prefix(self) -> None:
        prompt = "\u8bf7\u5e2e\u6211\u8fdb\u884c\u8d44\u9633\u5e02\u768490mdem\u4e0b\u8f7d"

        self.assertEqual(api_server._extract_region_from_prompt(prompt), "\u8d44\u9633\u5e02")

    def test_data_download_plan_includes_standardized_dem_slots(self) -> None:
        prompt = "\u5e2e\u6211\u83b7\u53d6\u56db\u5ddd\u8d44\u9633 90m DEM"
        plan = build_task_plan(prompt, {"intent": "data_download", "confidence": 0.9}, {"workspace": {"dataset_count": 0}})

        self.assertEqual(plan["semantic_parse"]["intent"], "data_download")
        self.assertEqual(plan["semantic_parse"]["region"], "\u8d44\u9633\u5e02")
        self.assertEqual(plan["semantic_parse"]["region_standard"], "\u56db\u5ddd\u7701\u8d44\u9633\u5e02")
        self.assertEqual(plan["download_plan"]["source_key"], "gscloud")
        self.assertEqual(plan["download_plan"]["resource_type"], "dem")
        self.assertEqual(plan["download_plan"]["region"], "\u8d44\u9633\u5e02")
        self.assertEqual(plan["download_plan"]["dataset_id"], "306")
        self.assertFalse(plan["should_ask_clarification"])

    def test_explicit_dem_download_with_active_boundary_does_not_route_upload_profile(self) -> None:
        prompt = "\u5e2e\u6211\u4e0b\u8f7d\u6210\u90fd\u5e0230m\u7684dem\u6570\u636e"
        context = {
            "workspace": {"dataset_count": 1},
            "active_dataset": {"name": "\u56db\u5ddd\u7701_\u6210\u90fd\u5e02_\u6210\u90fd\u5e02_city_boundary", "type": "vector"},
        }

        plan = build_task_plan(prompt, {"intent": "data_download", "confidence": 0.98}, context)

        self.assertEqual(plan["task_type"], "data_download")
        self.assertEqual(plan["semantic_parse"]["region"], "\u6210\u90fd\u5e02")
        self.assertEqual(plan["download_plan"]["resource_type"], "dem")
        self.assertNotEqual(plan.get("workflow_template", {}).get("workflow_id"), "upload_raster_profile")
        self.assertFalse(plan.get("executable_workflow"))
        self.assertFalse(plan.get("workflow_plan"))

    def test_download_followup_inherits_previous_dem_slots(self) -> None:
        prompt = "\u6211\u5df2\u7ecf\u5b8c\u6210\u767b\u5f55\uff0c\u5e2e\u6211\u4e0b\u8f7d"
        context = {
            "workspace": {"dataset_count": 1},
            "user_goal": "\u5e2e\u6211\u4e0b\u8f7d\u6210\u90fd\u5e0230m\u7684dem\u6570\u636e",
            "active_task": {
                "task_type": "data_download",
                "download_plan": {
                    "source_key": "gscloud",
                    "resource_type": "dem",
                    "region": "\u6210\u90fd\u5e02",
                    "region_standard": "\u56db\u5ddd\u7701\u6210\u90fd\u5e02",
                    "admin_level": "prefecture_city",
                    "resolution": "30m",
                    "dataset_id": "310",
                    "output_name": "\u6210\u90fd\u5e02_dem",
                },
            },
        }

        plan = build_task_plan(prompt, {"intent": "data_download", "confidence": 0.9}, context)

        self.assertEqual(plan["task_type"], "data_download")
        self.assertEqual(plan["download_plan"]["resource_type"], "dem")
        self.assertEqual(plan["download_plan"]["region"], "\u6210\u90fd\u5e02")
        self.assertEqual(plan["download_plan"]["resolution"], "30m")
        self.assertEqual(plan["download_plan"]["dataset_id"], "310")
        self.assertFalse(plan["should_ask_clarification"])

    def test_dem_tile_plan_ignores_prior_tile_grid_dataset_for_admin_region(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            settings = Settings(api_key="", workdir=Path(tmp) / "workspace")
            settings.ensure_dirs()
            manager = DataManager(settings.workdir)
            stale_grid = gpd.GeoDataFrame(
                {"tile_id": ["utm_srtm_56_05"]},
                geometry=[box(100.0, 25.0, 110.0, 35.0)],
                crs="EPSG:4326",
            )
            manager.put_vector("\u8d44\u9633\u5e02_dem_tile_plan_grid", stale_grid)

            plan = plan_gscloud_dem_tiles(
                manager,
                region="\u8d44\u9633\u5e02",
                dataset_id="306",
                save_preview=False,
            )

            self.assertEqual(plan["region_dataset"], "\u8d44\u9633\u5e02_boundary")
            self.assertEqual(plan["region_source"], "local_library_admin_boundary")
            self.assertEqual(
                plan["tile_ids"],
                ["utm_srtm_57_06", "utm_srtm_58_06", "utm_srtm_57_07", "utm_srtm_58_07"],
            )

    def test_dem_tile_plan_uses_local_shandian_boundary_library(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            settings = Settings(api_key="", workdir=root / "workspace")
            settings.ensure_dirs()
            manager = DataManager(settings.workdir)

            boundary_dir = manager.workdir / "local_library" / "data" / "boundary"
            boundary_dir.mkdir(parents=True, exist_ok=True)
            zip_path = boundary_dir / "shandianhe_basin_boundary_full.zip"

            source_dir = root / "source_boundary"
            source_dir.mkdir(parents=True, exist_ok=True)
            gdf = gpd.GeoDataFrame(
                {"name": ["shandianhe"]},
                geometry=[box(115.2, 41.1, 116.6, 42.4)],
                crs="EPSG:4326",
            )
            shp_path = source_dir / "shandianhe_basin_boundary.shp"
            gdf.to_file(shp_path, driver="ESRI Shapefile")
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in source_dir.glob("shandianhe_basin_boundary.*"):
                    archive.write(path, arcname=path.name)

            plan = plan_gscloud_dem_tiles(
                manager,
                region="\u95ea\u7535\u6cb3\u6d41\u57df",
                dataset_id="310",
                save_preview=False,
            )

            self.assertEqual(plan["region_dataset"], "shandianhe_basin_boundary")
            self.assertEqual(plan["region_source"], "local_library_boundary")
            self.assertEqual(
                plan["tile_ids"],
                ["ASTGTM_N41E115", "ASTGTM_N41E116", "ASTGTM_N42E115", "ASTGTM_N42E116"],
            )


if __name__ == "__main__":
    unittest.main()
