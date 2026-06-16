from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import Settings
from core.domestic_sources.gscloud_adapter import plan_aster_gdem_tiles
from core.service import GISWorkspaceService


class GSCloudDemRegionResolutionTests(unittest.TestCase):
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
