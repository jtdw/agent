from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from core.commercial.service import CommercialService
from core.config import Settings
from core.data_manager import DataManager
from core.map_layers import MapLayerService
from core.service import GISWorkspaceService
from infrastructure.storage.workspace_paths import workspace_root_for_session


class DownloadStatusMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.workdir = Path(self.tmp.name)
        self.service = CommercialService(self.workdir)
        self.service.register_user("user@example.com", "password1", user_id="u_test")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_raster(self, path: Path, *, west: float, value: int) -> Path:
        data = np.full((2, 2), value, dtype="int16")
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="int16",
            crs="EPSG:4326",
            transform=from_origin(west, 2.0, 1.0, 1.0),
            nodata=-9999,
        ) as dst:
            dst.write(data, 1)
        return path

    def test_failed_job_includes_failure_diagnostic(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="sentinel2_msi")

        failed = self.service.fail_job(job["job_id"], "download timeout")

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["state"], "failed")
        self.assertIn("message", failed)
        self.assertEqual(set(failed["failure_diagnostic"]).issuperset({"code", "title", "user_message", "next_action"}), True)

    def test_completed_job_records_artifact_quality(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="sentinel2_msi")
        result_path = self.workdir / "downloads" / "scene.zip"
        result_path.parent.mkdir()
        with zipfile.ZipFile(result_path, "w") as archive:
            archive.writestr("scene.txt", "ok")

        done = self.service.run_job_with_result(job["job_id"], {"zip_path": str(result_path)})

        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["state"], "success")
        self.assertEqual(done["artifact_quality"][0]["ok"], True)

    def test_invalid_download_result_fails_instead_of_completing(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="sentinel2_msi")
        empty = self.workdir / "downloads" / "empty.zip"
        empty.parent.mkdir()
        empty.write_bytes(b"")

        failed = self.service.run_job_with_result(job["job_id"], {"zip_path": str(empty)})

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["artifact_quality"][0]["ok"], False)
        self.assertIn("failure_diagnostic", failed)

    def test_completed_job_standardizes_multiple_raster_datasets_to_final_mosaic(self) -> None:
        manager = DataManager(self.workdir)
        left = self.write_raster(self.workdir / "left.tif", west=0.0, value=1)
        right = self.write_raster(self.workdir / "right.tif", west=2.0, value=2)
        left_name = manager.put_raster_path("download_left", left, meta={"crs": "EPSG:4326"})
        right_name = manager.put_raster_path("download_right", right, meta={"crs": "EPSG:4326"})
        job = self.service.submit_job(
            user_id="u_test",
            source_key="gscloud",
            resource_type="dem",
            output_name="downloaded_area",
        )

        done = self.service.run_job_with_result(job["job_id"], {"dataset_names": [left_name, right_name]})

        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["dataset_name"], "downloaded_area_mosaic")
        self.assertEqual(done["result"]["raster_standardization"]["action"], "mosaicked")
        self.assertTrue(Path(done["result"]["final_output_path"]).exists())
        self.assertEqual(done["output_path"], done["result"]["final_output_path"])

    def test_completed_path_only_raster_download_becomes_session_map_layer(self) -> None:
        session_id = "session_download_map"
        session_root = workspace_root_for_session(self.workdir, "u_test", session_id)
        raw_dir = session_root / "domestic_downloads" / "gscloud"
        raw_dir.mkdir(parents=True, exist_ok=True)
        left = self.write_raster(raw_dir / "left.tif", west=0.0, value=1)
        right = self.write_raster(raw_dir / "right.tif", west=2.0, value=2)
        job = self.service.submit_job(
            user_id="u_test",
            source_key="gscloud",
            resource_type="dem",
            output_name="session_downloaded_area",
            chat_session_id=session_id,
        )

        done = self.service.run_job_with_result(job["job_id"], {"downloads": [str(left), str(right)]})

        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["dataset_name"], "session_downloaded_area_mosaic")
        session_service = GISWorkspaceService(Settings(api_key="", workdir=session_root))
        layers = MapLayerService(session_service).workspace_layers(user_id="u_test", session_id=session_id)["layers"]
        layer = next(item for item in layers if item["dataset_name"] == "session_downloaded_area_mosaic")
        self.assertEqual(layer["type"], "raster")
        self.assertTrue(layer["map_ready"])

    def test_waiting_parameters_is_preserved_and_not_running(self) -> None:
        job = self.service.submit_job(user_id="u_test", source_key="gscloud", resource_type="dem")
        self.service._update_job(job["job_id"], status="waiting_parameters", stage="needs_region")

        waiting = self.service.get_job(job["job_id"])

        self.assertEqual(waiting["status"], "waiting_parameters")
        self.assertEqual(waiting["state"], "waiting_parameters")
        self.assertNotEqual(waiting["state"], "running")


if __name__ == "__main__":
    unittest.main()
