from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import Settings
from core.domestic_sources.gscloud_adapter import GSCLOUD_DEM_DATASETS, plan_aster_gdem_tiles, plan_gscloud_dem_tiles
from core.service import GISWorkspaceService
from api_server import _extract_region_from_prompt


class GSCloudDemRegionResolutionTests(unittest.TestCase):
    def test_chat_dem_region_extraction_accepts_other_china_admin_regions(self) -> None:
        cases = {
            "帮我下载青海省 DEM 数据": "青海省",
            "下载西藏自治区的dem数据": "西藏自治区",
            "使用平台账号下载河北省DEM数据": "河北省",
            "下载云南省DEM数据": "云南省",
        }

        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(_extract_region_from_prompt(prompt), expected)

    def test_srtmdemutm_90m_product_is_registered(self) -> None:
        product = GSCLOUD_DEM_DATASETS["srtmdemutm_90m"]

        self.assertEqual(product["dataset_id"], "306")
        self.assertEqual(product["pid"], "302")
        self.assertIn("accessdata/306?pid=302", product["access_url"])
        self.assertEqual(product["tile_scheme"], "srtm_utm_5deg")

    def test_chengdu_srtmdemutm_90m_uses_five_degree_tile_id(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))

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

    def test_shandianhe_region_uses_builtin_boundary_for_dem_tile_plan(self) -> None:
        boundary_zip = Path(__file__).resolve().parents[1] / "local_library" / "data" / "boundary" / "shandianhe_basin_boundary_full.zip"
        if not boundary_zip.exists():
            self.skipTest("shandianhe builtin boundary archive is not installed")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))

            result = plan_aster_gdem_tiles(service.manager, region="闪电河流域", output_name="shandianhe_dem_tiles")

            self.assertGreater(result["tile_count"], 0)
            self.assertIn(result["region_source"], {"local_library_boundary", "preset_bbox"})
            self.assertTrue(any(str(tile).startswith("ASTGTM_N41E115") or str(tile).startswith("ASTGTM_N41E116") for tile in result["tile_ids"]))


if __name__ == "__main__":
    unittest.main()
