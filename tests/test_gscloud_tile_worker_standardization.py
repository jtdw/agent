from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.commercial import gscloud_scene_worker
from core.commercial import gscloud_tile_worker


class GSCloudTileWorkerStandardizationTests(unittest.TestCase):
    def test_scene_worker_runs_raster_standardization_before_completion(self) -> None:
        source = Path("core/commercial/gscloud_scene_worker.py").read_text(encoding="utf-8")

        self.assertIn("standardize_raster_download_result", source)
        self.assertLess(source.index("standardize_raster_download_result("), source.index("run_job_with_result"))
        self.assertIn("clip_vector=clip_vector", source)

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

    def test_dem_tile_worker_checks_login_health_before_planning(self) -> None:
        source = Path("core/commercial/gscloud_tile_worker.py").read_text(encoding="utf-8")

        self.assertIn("inspect_storage_state", source)
        self.assertLess(source.index("inspect_storage_state"), source.index("plan_gscloud_dem_tiles("))

    def test_dem_tile_worker_executes_standardization_before_completing_job(self) -> None:
        events: list[str] = []

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp)
            status_path = workdir / "domestic_auth" / "tile_jobs" / "job_1.json"
            status_path.parent.mkdir(parents=True)
            cookie_path = workdir / "cookie.json"
            cookie_path.write_text("{}", encoding="utf-8")
            status_path.write_text(
                json.dumps(
                    {
                        "job_id": "job_1",
                        "region": "test region",
                        "dataset_id": "310",
                        "max_tiles": 1,
                    }
                ),
                encoding="utf-8",
            )

            class FakeService:
                def __init__(self, root: Path):
                    self.root = Path(root)

                def get_job(self, job_id: str):
                    return {
                        "job_id": job_id,
                        "region": "test region",
                        "output_name": "dem_out",
                        "account_mode": "platform",
                        "account_id": "acct_1",
                        "source_key": "gscloud",
                    }

                def _update_job(self, job_id: str, **kwargs):
                    events.append(f"update:{kwargs.get('stage') or kwargs.get('status')}")

                def resolve_job_storage_state_path(self, job_id: str) -> str:
                    return str(cookie_path)

                def run_job_with_result(self, job_id: str, result: dict):
                    events.append("complete")
                    self.completed_result = result
                    return {"job_id": job_id, "status": "completed", "result": result}

                def fail_job(self, job_id: str, message: str):
                    events.append(f"fail:{message}")
                    return {"job_id": job_id, "status": "failed", "error_message": message}

            class FakeManager:
                def __init__(self, root: Path):
                    self.root = Path(root)

            def fake_standardize(**kwargs):
                events.append("standardize")
                result = dict(kwargs["result"])
                result["standardized"] = True
                result["output_name"] = kwargs["output_name"]
                result["clip_vector"] = kwargs["clip_vector"]
                return result

            with (
                mock.patch.object(sys, "argv", ["worker", "--status-path", str(status_path)]),
                mock.patch.object(gscloud_tile_worker, "CommercialService", FakeService),
                mock.patch.object(gscloud_tile_worker, "DataManager", FakeManager),
                mock.patch.object(gscloud_tile_worker, "inspect_storage_state", return_value={"ok": True}),
                mock.patch.object(
                    gscloud_tile_worker,
                    "plan_gscloud_dem_tiles",
                    return_value={
                        "tile_ids": ["N00E000"],
                        "tile_count": 1,
                        "dataset_id": "310",
                        "pid": "1",
                        "tile_scheme": "astgtm_1deg",
                        "region_dataset": "boundary",
                    },
                ),
                mock.patch.object(gscloud_tile_worker, "download_gscloud_tiles_by_identifier_search", return_value={"downloads": ["tile.zip"]}),
                mock.patch.object(gscloud_tile_worker, "standardize_raster_download_result", side_effect=fake_standardize),
            ):
                exit_code = gscloud_tile_worker.main()

            final_status = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertLess(events.index("standardize"), events.index("complete"))
        self.assertTrue(final_status["result"]["standardized"])
        self.assertEqual(final_status["result"]["clip_vector"], "boundary")

    def test_scene_worker_executes_standardization_before_completing_job(self) -> None:
        events: list[str] = []

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp)
            status_path = workdir / "domestic_auth" / "scene_jobs" / "scene_1.json"
            status_path.parent.mkdir(parents=True)
            cookie_path = workdir / "cookie.json"
            cookie_path.write_text("{}", encoding="utf-8")
            status_path.write_text(
                json.dumps(
                    {
                        "job_id": "job_1",
                        "product_key": "modnd1t_china_500m_ndvi_10day",
                        "region": "test region",
                        "max_scenes": 1,
                    }
                ),
                encoding="utf-8",
            )

            class FakeService:
                def __init__(self, root: Path):
                    self.root = Path(root)

                def get_job(self, job_id: str):
                    return {
                        "job_id": job_id,
                        "region": "test region",
                        "output_name": "ndvi_out",
                        "account_mode": "platform",
                        "account_id": "acct_1",
                        "source_key": "gscloud",
                    }

                def _update_job(self, job_id: str, **kwargs):
                    events.append(f"update:{kwargs.get('stage') or kwargs.get('status')}")

                def resolve_job_storage_state_path(self, job_id: str) -> str:
                    return str(cookie_path)

                def run_job_with_result(self, job_id: str, result: dict):
                    events.append("complete")
                    return {"job_id": job_id, "status": "completed", "result": result}

                def fail_job(self, job_id: str, message: str):
                    events.append(f"fail:{message}")
                    return {"job_id": job_id, "status": "failed", "error_message": message}

            class FakeManager:
                def __init__(self, root: Path):
                    self.root = Path(root)

            def fake_standardize(**kwargs):
                events.append("standardize")
                result = dict(kwargs["result"])
                result["standardized"] = True
                result["output_name"] = kwargs["output_name"]
                result["clip_vector"] = kwargs["clip_vector"]
                return result

            with (
                mock.patch.object(sys, "argv", ["worker", "--status-path", str(status_path)]),
                mock.patch.object(gscloud_scene_worker, "CommercialService", FakeService),
                mock.patch.object(gscloud_scene_worker, "DataManager", FakeManager),
                mock.patch.object(gscloud_scene_worker, "inspect_storage_state", return_value={"ok": True}),
                mock.patch.object(
                    gscloud_scene_worker,
                    "resolve_download_region",
                    return_value={"ok": True, "region": "test region", "bounds": [0, 0, 2, 2]},
                ),
                mock.patch.object(gscloud_scene_worker, "_resolve_scene_clip_vector", return_value="boundary"),
                mock.patch.object(gscloud_scene_worker, "download_modnd1d_china_ndvi_daily", return_value={"downloads": ["scene.zip"]}),
                mock.patch.object(gscloud_scene_worker, "standardize_raster_download_result", side_effect=fake_standardize),
            ):
                exit_code = gscloud_scene_worker.main()

            final_status = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertLess(events.index("standardize"), events.index("complete"))
        self.assertTrue(final_status["result"]["standardized"])
        self.assertEqual(final_status["result"]["clip_vector"], "boundary")


if __name__ == "__main__":
    unittest.main()
