from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.downloads.gscloud_auto_start import GSCloudAutoStartService


class FakeCommercialService:
    def __init__(self, state_path: str = "") -> None:
        self.state_path = state_path
        self.updated: list[tuple[str, dict]] = []
        self.released: list[tuple[str, str]] = []

    def resolve_job_storage_state_path(self, job_id: str) -> str:
        return self.state_path

    def _release_platform_reservation(self, job_id: str, reason: str) -> None:
        self.released.append((job_id, reason))

    def _update_job(self, job_id: str, **kwargs) -> None:
        self.updated.append((job_id, kwargs))


class GSCloudAutoStartServiceTests(unittest.TestCase):
    def make_service(self, commercial: FakeCommercialService, **workers) -> GSCloudAutoStartService:
        return GSCloudAutoStartService(
            commercial_service=lambda: commercial,
            workdir=lambda: Path("workdir"),
            products={
                "modl1d": SimpleNamespace(resource_type="modl1d_china_1km_lst_daily"),
                "modnd1d": SimpleNamespace(resource_type="modnd1d_china_500m_ndvi_daily"),
                "modev1f": SimpleNamespace(resource_type="modev1f_china_250m_evi_5day"),
                "mod021km": SimpleNamespace(resource_type="mod021km_1km_surface_reflectance"),
                "sentinel2": SimpleNamespace(resource_type="sentinel2_msi"),
                "landsat8": SimpleNamespace(resource_type="landsat8_oli_tirs"),
            },
            **workers,
        )

    def test_non_gscloud_job_is_not_auto_supported(self) -> None:
        commercial = FakeCommercialService()
        service = self.make_service(commercial)

        result = service.maybe_start({"source_key": "local", "resource_type": "dem", "job_id": "job_1"})

        self.assertEqual(result, {"auto_supported": False, "auto_started": False, "reason": "not_gscloud"})
        self.assertEqual(commercial.updated, [])

    def test_missing_storage_state_moves_job_to_waiting_login(self) -> None:
        commercial = FakeCommercialService()
        service = self.make_service(commercial)

        result = service.maybe_start({"source_key": "gscloud", "resource_type": "dem", "job_id": "job_2"})

        self.assertEqual(result, {"auto_supported": True, "auto_started": False, "reason": "waiting_login"})
        self.assertEqual(commercial.released, [("job_2", "release_waiting_login_platform_download")])
        self.assertEqual(
            commercial.updated,
            [("job_2", {"status": "waiting_login", "progress": 5, "stage": "needs_gscloud_login_state"})],
        )

    def test_dem_job_starts_tile_worker_with_dataset_from_prompt(self) -> None:
        calls: list[dict] = []

        def tile_worker(**kwargs):
            calls.append(kwargs)
            return {"tile_job_id": "tile_1"}

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("{}", encoding="utf-8")
            commercial = FakeCommercialService(str(state_path))
            service = self.make_service(commercial, tile_worker=tile_worker)

            result = service.maybe_start(
                {
                    "source_key": "gscloud",
                    "resource_type": "dem",
                    "job_id": "job_dem",
                    "request_text": "download Ziyang SRTM 90m DEM",
                },
                region="Ziyang",
            )

        self.assertTrue(result["auto_started"])
        self.assertEqual(result["auto_tile_job"], {"tile_job_id": "tile_1"})
        self.assertEqual(calls[0]["dataset_id"], "306")
        self.assertEqual(calls[0]["region"], "Ziyang")
        self.assertEqual(commercial.updated[0][1]["stage"], "starting_auto_tile_worker")

    def test_landsat_job_starts_scene_worker_with_year_cloud_and_scene_limit(self) -> None:
        calls: list[dict] = []

        def landsat_worker(**kwargs):
            calls.append(kwargs)
            return {"scene_job_id": "scene_1"}

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text("{}", encoding="utf-8")
            commercial = FakeCommercialService(str(state_path))
            service = self.make_service(commercial, landsat8_worker=landsat_worker)

            result = service.maybe_start(
                {
                    "source_key": "gscloud",
                    "resource_type": "landsat8_oli_tirs",
                    "job_id": "job_landsat",
                    "request_text": "download 3 scenes in 2022 cloud <= 12.5",
                    "start_date": "2022-01-01",
                    "end_date": "2022-12-31",
                },
                region="Chengdu",
            )

        self.assertTrue(result["auto_started"])
        self.assertEqual(result["scene_job"], {"scene_job_id": "scene_1"})
        self.assertEqual(calls[0]["year"], "2022")
        self.assertEqual(calls[0]["cloud_max"], 12.5)
        self.assertEqual(calls[0]["max_scenes"], 3)
        self.assertEqual(commercial.updated[0][1]["stage"], "starting_landsat8_scene_worker")


if __name__ == "__main__":
    unittest.main()
