from __future__ import annotations

import tempfile
import unittest
import zipfile
from importlib.util import find_spec
from pathlib import Path


@unittest.skipIf(find_spec("fastapi") is None, "fastapi is not installed in this Python environment")
class ApiUtilsTest(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import HTTPException
        from core.api_utils import api_guard, resolve_child_path

        self.HTTPException = HTTPException
        self.api_guard = api_guard
        self.resolve_child_path = resolve_child_path

    def test_resolve_child_path_allows_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "exports" / "result.txt"
            target.parent.mkdir()
            target.write_text("ok", encoding="utf-8")

            self.assertEqual(self.resolve_child_path(root, "exports/result.txt"), target.resolve())

    def test_resolve_child_path_blocks_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "outside.txt"
            outside.write_text("no", encoding="utf-8")
            try:
                with self.assertRaises(PermissionError):
                    self.resolve_child_path(root, "../outside.txt")
            finally:
                outside.unlink(missing_ok=True)

    def test_read_vector_for_map_rejects_zip_path_escape(self) -> None:
        from api_server import _read_vector_for_map

        with tempfile.TemporaryDirectory() as tmp:
            archive_path = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as zf:
                zf.writestr("../evil.shp", b"not a real shapefile")

            with self.assertRaises(ValueError):
                _read_vector_for_map(archive_path)

            self.assertFalse((Path(tmp).parent / "evil.shp").exists())

    def test_api_guard_maps_unhandled_error_to_error_id(self) -> None:
        def fail() -> None:
            raise RuntimeError("boom")

        with self.assertRaises(self.HTTPException) as caught:
            self.api_guard(fail, context="test")

        self.assertEqual(caught.exception.status_code, 500)
        self.assertIsInstance(caught.exception.detail, dict)
        self.assertIn("error_id", caught.exception.detail)

    @unittest.skipIf(find_spec("rasterio") is None, "rasterio is not installed in this Python environment")
    def test_raster_preview_handles_integer_masked_nodata(self) -> None:
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        from api_server import _ensure_raster_preview
        from core.config import Settings
        from core.service import GISWorkspaceService

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            raster_path = root / "int16_dem.tif"
            data = np.array([[1, -9999], [3, 4]], dtype=np.int16)
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=2,
                width=2,
                count=1,
                dtype="int16",
                crs="EPSG:4326",
                transform=from_origin(115.0, 41.0, 0.01, 0.01),
                nodata=-9999,
            ) as dst:
                dst.write(data, 1)

            settings = Settings(api_key="", workdir=root / "workspace")
            settings.ensure_dirs()
            service = GISWorkspaceService(settings)
            dataset_name = service.manager.put_raster_path("int16_dem", raster_path, meta={"crs": "EPSG:4326"})

            preview = _ensure_raster_preview(service, dataset_name, user_id="u_test")

            self.assertTrue(Path(preview["preview_path"]).exists())
            self.assertIn("dataset_name=", preview["preview_url"])
            self.assertEqual(len(preview["bounds"]), 4)


if __name__ == "__main__":
    unittest.main()
