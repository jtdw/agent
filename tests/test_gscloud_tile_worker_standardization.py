from __future__ import annotations

import unittest
from pathlib import Path


class GSCloudTileWorkerStandardizationTests(unittest.TestCase):
    def test_dem_tile_worker_runs_raster_standardization_before_completion(self) -> None:
        source = Path("core/commercial/gscloud_tile_worker.py").read_text(encoding="utf-8")

        self.assertIn("standardize_raster_download_result", source)
        self.assertLess(source.index("standardize_raster_download_result("), source.index("run_job_with_result"))
        self.assertIn("clip_vector=str(plan.get(\"region_dataset\") or \"\")", source)


if __name__ == "__main__":
    unittest.main()
