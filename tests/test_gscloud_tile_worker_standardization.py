from __future__ import annotations

import unittest
from pathlib import Path


class GSCloudTileWorkerStandardizationTests(unittest.TestCase):
    def test_dem_tile_worker_runs_raster_standardization_before_completion(self) -> None:
        source = Path("core/commercial/gscloud_tile_worker.py").read_text(encoding="utf-8")

        self.assertIn("standardize_raster_download_result", source)
        self.assertLess(source.index("standardize_raster_download_result("), source.index("run_job_with_result"))
        self.assertIn("clip_vector=str(plan.get(\"region_dataset\") or \"\")", source)

    def test_dem_tile_worker_uses_product_aware_tile_planner(self) -> None:
        source = Path("core/commercial/gscloud_tile_worker.py").read_text(encoding="utf-8")

        self.assertIn("plan_gscloud_dem_tiles", source)
        self.assertIn("dataset_id=str(current.get(\"dataset_id\") or \"310\")", source)

    def test_dem_tile_worker_passes_product_tile_scheme_and_pid_to_downloader(self) -> None:
        source = Path("core/commercial/gscloud_tile_worker.py").read_text(encoding="utf-8")

        self.assertIn("tile_scheme=str(plan.get(\"tile_scheme\") or \"astgtm_1deg\")", source)
        self.assertIn("pid=str(plan.get(\"pid\") or \"1\")", source)


if __name__ == "__main__":
    unittest.main()
