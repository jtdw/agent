from __future__ import annotations

import tempfile
import unittest
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from core.data_manager import DataManager
from core.domestic_sources.base import DomesticSource
from core.domestic_sources.downloader import postprocess_download
from core.domestic_sources.gscloud_adapter import _postprocess_gscloud_files
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
    def test_download_postprocess_references_raster_without_upload_copy_or_timestamp_extracts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            source_dir = manager.temp_dir / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            tif = source_dir / "dem.tif"
            _write_tile(tif, west=0, north=2, value=7)
            archive = source_dir / "dem.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(tif, tif.name)

            first = postprocess_download(manager, archive, source_key="fixture", output_name="chengdu_dem", auto_load=True)
            second = postprocess_download(manager, archive, source_key="fixture", output_name="chengdu_dem", auto_load=True)

            extract_dirs = [path for path in manager.derived_dir.glob("chengdu_dem_extracted*") if path.is_dir()]
            self.assertEqual([path.name for path in extract_dirs], ["chengdu_dem_extracted"])
            self.assertEqual(list(manager.upload_dir.glob("*.tif")), [])
            self.assertEqual(first.dataset_name, second.dataset_name)
            dataset = manager.get(str(second.dataset_name))
            self.assertEqual(dataset.path.resolve(), (manager.derived_dir / "chengdu_dem_extracted" / "dem.tif").resolve())

    def test_download_postprocess_selectively_extracts_loadable_raster_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            source_dir = manager.temp_dir / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            tif = source_dir / "dem.tif"
            _write_tile(tif, west=0, north=2, value=7)
            archive = source_dir / "dem_with_noise.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(tif, "data/dem.tif")
                zf.writestr("docs/readme.txt", "metadata")
                zf.writestr("unneeded/blob.bin", b"x" * 1024)

            result = postprocess_download(manager, archive, source_key="fixture", output_name="chengdu_dem", auto_load=True)

            extracted_files = sorted(path.relative_to(result.extracted_dir).as_posix() for path in Path(result.extracted_dir).rglob("*") if path.is_file())
            self.assertEqual(extracted_files, ["data/dem.tif"])
            self.assertEqual(list(manager.upload_dir.glob("*")), [])

    def test_download_postprocess_references_table_without_upload_copy(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            source_dir = manager.temp_dir / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            archive = source_dir / "table_download.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("tables/points.csv", "lon,lat,value\n104.1,30.2,1\n")
                zf.writestr("unneeded/blob.bin", b"x" * 1024)

            result = postprocess_download(manager, archive, source_key="fixture", output_name="points", auto_load=True)

            extracted_files = sorted(path.relative_to(result.extracted_dir).as_posix() for path in Path(result.extracted_dir).rglob("*") if path.is_file())
            self.assertEqual(extracted_files, ["tables/points.csv"])
            self.assertEqual(list(manager.upload_dir.glob("*")), [])
            dataset = manager.get(str(result.dataset_name))
            self.assertEqual(dataset.data_type, "table")
            self.assertEqual(dataset.path.resolve(), (Path(result.extracted_dir) / "tables" / "points.csv").resolve())

    def test_gscloud_batch_postprocess_references_selected_rasters_without_raw_zip_copies(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            source_dir = manager.temp_dir / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            archives: list[Path] = []
            for idx, value in enumerate((7, 8), start=1):
                tif = source_dir / f"tile_{idx}.tif"
                _write_tile(tif, west=idx, north=2, value=value)
                archive = source_dir / f"tile_{idx}.zip"
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.write(tif, f"data/tile_{idx}.tif")
                    zf.writestr(f"unneeded/blob_{idx}.bin", b"x" * 1024)
                archives.append(archive)

            result = _postprocess_gscloud_files(
                manager,
                archives,
                DomesticSource(key="gscloud", name="GSCloud", home_url=""),
                output_name="chengdu_dem",
                auto_load=True,
            )

            batch_dir = Path(result["extracted_dir"])
            batch_files = sorted(path.relative_to(batch_dir).as_posix() for path in batch_dir.rglob("*") if path.is_file())
            self.assertEqual(batch_files, ["tile_1/data/tile_1.tif", "tile_2/data/tile_2.tif"])
            self.assertEqual(list(manager.upload_dir.glob("*")), [])
            for item in result["meta"]["items"]:
                dataset = manager.get(item["dataset_name"])
                self.assertTrue(str(dataset.path).startswith(str(batch_dir)))

    def test_duplicate_raster_dataset_entries_are_deduplicated_before_clipping(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            raw_dir = manager.temp_dir / "duplicate_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            source = raw_dir / "MODND1D.20160517.CN.NDVI.V2.TIF"
            _write_tile(source, west=0, north=2, value=100)
            copied_a = raw_dir / "11111111111111111111111111111111_MODND1D.20160517.CN.NDVI.V2.tif"
            copied_b = raw_dir / "22222222222222222222222222222222_MODND1D.20160517.CN.NDVI.V2.tif"
            shutil.copy2(source, copied_a)
            shutil.copy2(source, copied_b)
            first = manager.put_raster_path("ndvi_first", copied_a)
            second = manager.put_raster_path("ndvi_second", copied_b)
            boundary = gpd.GeoDataFrame({"name": ["study_area"]}, geometry=[box(0, 0, 1, 2)], crs="EPSG:4326")
            boundary_name = manager.put_vector("study_area_boundary", boundary)

            result = standardize_raster_download_result(
                manager,
                {"dataset_names": [first, second]},
                output_name="study_area_ndvi",
                clip_vector=boundary_name,
            )

            self.assertEqual(result["raster_standardization"]["action"], "single_raster_clipped")
            self.assertEqual(result["raster_standardization"]["source_dataset"], first)
            with rasterio.open(result["final_output_path"]) as src:
                self.assertEqual(src.width, 1)
                self.assertEqual(src.height, 2)

    def test_single_raster_is_clipped_when_clip_vector_is_available(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            raw_dir = manager.temp_dir / "single_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            source = raw_dir / "MODND1D.20160517.CN.NDVI.V2.TIF"
            _write_tile(source, west=0, north=2, value=100)
            boundary = gpd.GeoDataFrame({"name": ["study_area"]}, geometry=[box(0, 0, 1, 2)], crs="EPSG:4326")
            boundary_name = manager.put_vector("study_area_boundary", boundary)

            result = standardize_raster_download_result(
                manager,
                {"downloads": [str(source)]},
                output_name="study_area_ndvi",
                clip_vector=boundary_name,
            )

            final_path = Path(result["final_output_path"])
            self.assertTrue(final_path.exists())
            self.assertNotEqual(final_path.resolve(), source.resolve())
            self.assertEqual(result["raster_standardization"]["action"], "single_raster_clipped")
            self.assertEqual(result["raster_standardization"]["clip_vector"], boundary_name)
            self.assertTrue(Path(result["zip_path"]).exists())
            with rasterio.open(final_path) as src:
                self.assertEqual(src.width, 1)
                self.assertEqual(src.height, 2)

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
