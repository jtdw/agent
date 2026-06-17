from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from core.data_manager import DataManager
from core.domestic_sources.raster_postprocess import standardize_raster_download_result


def _write_tile(path: Path, west: float, north: float, value: int) -> None:
    data = np.full((1, 2, 2), value, dtype="uint16")
    transform = from_origin(west, north, 1, 1)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=transform,
        nodata=0,
    ) as dst:
        dst.write(data)


class RasterPostprocessTests(unittest.TestCase):
    def test_mosaics_adjacent_tiles_clips_to_boundary_and_registers_final_raster(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            raw_dir = manager.temp_dir / "raw_tiles"
            raw_dir.mkdir(parents=True, exist_ok=True)
            left = raw_dir / "ASTGTM_N00E000_dem.tif"
            right = raw_dir / "ASTGTM_N00E002_dem.tif"
            _write_tile(left, west=0, north=2, value=10)
            _write_tile(right, west=2, north=2, value=20)
            boundary = gpd.GeoDataFrame({"name": ["county"]}, geometry=[box(0.5, 0, 3.5, 2)], crs="EPSG:4326")
            boundary_name = manager.put_vector("county_boundary", boundary)

            result = standardize_raster_download_result(
                manager,
                {"downloaded_path": str(raw_dir), "downloads": [str(left), str(right)]},
                output_name="county_dem",
                clip_vector=boundary_name,
            )

            final_path = Path(result["final_output_path"])
            self.assertTrue(final_path.exists())
            self.assertEqual(result["output_path"], str(final_path))
            self.assertIn(result["dataset_name"], manager.list_dataset_names())
            self.assertEqual(result["raster_standardization"]["action"], "mosaicked_and_clipped")
            self.assertEqual(result["raster_standardization"]["input_raster_count"], 2)
            self.assertTrue(Path(result["zip_path"]).exists())
            with rasterio.open(final_path) as src:
                self.assertEqual(src.crs.to_string(), "EPSG:4326")
                self.assertGreater(src.width, 0)
                self.assertGreater(src.height, 0)


if __name__ == "__main__":
    unittest.main()
