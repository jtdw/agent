from __future__ import annotations

import unittest
from pathlib import Path


class GSCloudCommercialToolsTileCaseTests(unittest.TestCase):
    def test_manual_dem_tile_download_uses_product_aware_identifier_downloader(self) -> None:
        source = Path("core/commercial/tools.py").read_text(encoding="utf-8")

        manual_section = source[source.index("def run_gscloud_dem_auto_tiles_job"):source.index("def index_gscloud_aster_gdem_resources")]
        self.assertIn("resolve_gscloud_dem_product", manual_section)
        self.assertIn("download_gscloud_tiles_by_identifier_search", manual_section)
        self.assertIn('tile_scheme=str(product.get("tile_scheme") or "astgtm_1deg")', manual_section)
        self.assertIn('pid=str(product.get("pid") or "1")', manual_section)
        self.assertNotIn("auto_download_gscloud_tiles(", manual_section)

    def test_region_dem_tile_download_uses_product_aware_plan_and_identifier_downloader(self) -> None:
        source = Path("core/commercial/tools.py").read_text(encoding="utf-8")

        start = source.rindex("def run_gscloud_dem_region_auto_tiles_job")
        end = source.index("user_tools = [", start)
        region_section = source[start:end]
        self.assertIn("plan_gscloud_dem_tiles", region_section)
        self.assertIn("download_gscloud_tiles_by_identifier_search", region_section)
        self.assertIn("dataset_id=str(plan.get(\"dataset_id\") or dataset_id)", region_section)
        self.assertIn("tile_scheme=str(plan.get(\"tile_scheme\") or \"astgtm_1deg\")", region_section)
        self.assertIn("pid=str(plan.get(\"pid\") or \"1\")", region_section)
        self.assertNotIn("plan_aster_gdem_tiles(", region_section)
        self.assertNotIn("download_gscloud_tiles_by_full_scan(", region_section)


if __name__ == "__main__":
    unittest.main()
