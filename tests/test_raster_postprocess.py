from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from core.config import Settings
from core.domestic_sources.raster_postprocess import standardize_raster_download_result
from core.service import GISWorkspaceService


class RasterDownloadPostprocessTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

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

    def test_adjacent_raster_download_tiles_are_promoted_to_mosaic_output(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = self.write_tile(Path(tmp) / "left.tif", west=0.0, values=np.array([[1, 2], [3, 4]]))
            right = self.write_tile(Path(tmp) / "right.tif", west=2.0, values=np.array([[5, 6], [7, 8]]))
            left_name = service.manager.put_raster_path("left_tile", left, meta={"crs": "EPSG:4326"})
            right_name = service.manager.put_raster_path("right_tile", right, meta={"crs": "EPSG:4326"})
            service.manager.put_vector("boundary", gpd.GeoDataFrame({"id": [1], "geometry": [box(0.5, 0.1, 3.5, 1.9)]}, crs="EPSG:4326"))

            result = standardize_raster_download_result(
                service.manager,
                {"dataset_names": [left_name, right_name]},
                output_name="standardized_download",
                clip_vector="boundary",
                fail_on_mosaic_error=True,
            )

            self.assertEqual(result["dataset_name"], "standardized_download_mosaic")
            self.assertEqual(result["final_dataset_name"], "standardized_download_mosaic")
            self.assertEqual(result["path"], result["final_output_path"])
            self.assertTrue(Path(result["final_output_path"]).exists())
            self.assertEqual(result["raster_standardization"]["action"], "mosaicked")
            with rasterio.open(result["final_output_path"]) as src:
                self.assertEqual(src.dtypes[0], "int16")
                self.assertFalse(np.isnan(src.read(1, masked=True).filled(src.nodata)).any())

    def test_overlapping_raster_download_scenes_are_not_mosaicked(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            first = self.write_tile(Path(tmp) / "first_date.tif", west=0.0, values=np.array([[1, 2], [3, 4]]))
            second = self.write_tile(Path(tmp) / "second_date.tif", west=0.0, values=np.array([[5, 6], [7, 8]]))
            first_name = service.manager.put_raster_path("scene_20200101", first, meta={"crs": "EPSG:4326"})
            second_name = service.manager.put_raster_path("scene_20200201", second, meta={"crs": "EPSG:4326"})

            result = standardize_raster_download_result(
                service.manager,
                {"dataset_names": [first_name, second_name]},
                output_name="time_series_download",
            )

            self.assertEqual(result["dataset_name"], first_name)
            self.assertNotIn("final_output_path", result)
            self.assertEqual(result["raster_standardization"]["action"], "skipped")
            self.assertEqual(result["raster_standardization"]["reason"], "overlapping_rasters")


if __name__ == "__main__":
    unittest.main()
