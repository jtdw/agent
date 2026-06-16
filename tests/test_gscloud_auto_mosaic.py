from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from core.commercial.gscloud_tile_worker import _mosaic_loaded_tiles
from core.config import Settings
from core.service import GISWorkspaceService


class GSCloudAutoMosaicTests(unittest.TestCase):
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

    def test_loaded_gscloud_dem_tiles_are_mosaicked_and_promoted_to_final_output(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            left = self.write_tile(Path(tmp) / "left.tif", west=0.0, values=np.array([[1, 2], [3, 4]]))
            right = self.write_tile(Path(tmp) / "right.tif", west=2.0, values=np.array([[5, 6], [7, 8]]))
            left_name = service.manager.put_raster_path("left_tile", left, meta={"crs": "EPSG:4326"})
            right_name = service.manager.put_raster_path("right_tile", right, meta={"crs": "EPSG:4326"})
            service.manager.put_vector("basin_boundary", gpd.GeoDataFrame({"id": [1], "geometry": [box(0.5, 0.1, 3.5, 1.9)]}, crs="EPSG:4326"))

            result = _mosaic_loaded_tiles(
                service.manager,
                {"dataset_names": [left_name, right_name]},
                output_name="basin_dem",
                vector_name="basin_boundary",
            )

            self.assertEqual(result["dataset_name"], "basin_dem_mosaic")
            self.assertEqual(result["mosaic_dataset_name"], "basin_dem_mosaic")
            self.assertTrue(Path(result["mosaic_path"]).exists())
            self.assertEqual(result["path"], result["mosaic_path"])
            with rasterio.open(result["path"]) as src:
                self.assertEqual(src.dtypes[0], "int16")
                self.assertEqual(src.nodata, -9999)
                self.assertFalse(np.isnan(src.read(1, masked=True).filled(src.nodata)).any())


if __name__ == "__main__":
    unittest.main()
