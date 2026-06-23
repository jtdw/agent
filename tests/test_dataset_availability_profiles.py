from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from core.dataset_availability import DatasetAvailabilityStore, availability_for_product
from core.plan_validator import validate_task_plan_before_execution
from core.product_catalog import product_by_id


class DatasetAvailabilityProfileTests(unittest.TestCase):
    def test_active_availability_profile_blocks_out_of_range_download(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = DatasetAvailabilityStore(Path(tmp))
            store.upsert_profile(
                {
                    "product_id": "gscloud_ndvi_500m_10day",
                    "source_product_key": "modnd1t_china_500m_ndvi_10day",
                    "display_name_zh": "MODND1T 中国 500M NDVI 旬合成产品",
                    "source_url": "https://www.gscloud.cn/sources/accessdata/346?pid=333",
                    "temporal_coverage": {"start": "2000-02-01", "end": "2016-05-31"},
                    "supported_formats": ["zip"],
                    "verification_method": "scene_table_scan",
                    "status": "active",
                    "version": "fixture-v1",
                }
            )
            plan = {
                "primary_goal": "下载成都市2022年NDVI",
                "intent": "data_download",
                "operation": "download_data",
                "selected_tools": ["submit_commercial_download_job"],
                "workflow_steps": [{"step_id": "submit_ndvi", "tool_name": "submit_commercial_download_job", "args": {}}],
                "requested_downloads": [
                    {
                        "area_asset_id": "admin:city:四川省:成都市",
                        "product_id": "gscloud_ndvi_500m_10day",
                        "resolved_resolution": "500m",
                        "time_range": {"start": "2022-01-01", "end": "2022-01-31"},
                    }
                ],
            }

            with mock.patch("core.plan_validator.availability_for_product", side_effect=lambda product_id: store.get_active_profile(product_id)):
                result = validate_task_plan_before_execution(plan, {"confirmed_action_id": "confirmed"})

            self.assertFalse(result["ok"])
            self.assertEqual(result["errors"][0]["code"], "DOWNLOAD_TIME_RANGE_OUT_OF_AVAILABILITY")
            self.assertIn("2016-05-31", result["errors"][0]["message"])
            self.assertIn("submit_commercial_download_job", result["blocked_tools"])

    def test_product_catalog_exposes_active_availability_profile_metadata(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            store = DatasetAvailabilityStore(Path(tmp))
            store.upsert_profile(
                {
                    "product_id": "gscloud_ndvi_500m_10day",
                    "source_product_key": "modnd1t_china_500m_ndvi_10day",
                    "display_name_zh": "MODND1T 中国 500M NDVI 旬合成产品",
                    "source_url": "https://www.gscloud.cn/sources/accessdata/346?pid=333",
                    "temporal_coverage": {"start": "2000-02-01", "end": "2016-05-31"},
                    "supported_formats": ["zip", "hdf"],
                    "verification_method": "scene_table_scan",
                    "status": "active",
                    "version": "fixture-v1",
                }
            )

            with mock.patch("core.product_catalog.availability_for_product", side_effect=lambda product_id: store.get_active_profile(product_id)):
                product = product_by_id("gscloud_ndvi_500m_10day")

            self.assertEqual(product["availability_profile"]["temporal_coverage"]["end"], "2016-05-31")
            self.assertEqual(product["availability_profile"]["verification_method"], "scene_table_scan")

    def test_default_availability_store_returns_empty_when_unverified(self) -> None:
        self.assertEqual(availability_for_product("unknown_product"), {})

    def test_admin_api_manages_dataset_availability_profiles(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with mock.patch.dict(
                os.environ,
                {"GIS_AGENT_CAPABILITY_CONFIG_DIR": str(Path(tmp)), "GIS_AGENT_ADMIN_TOKEN": "secret"},
                clear=False,
            ):
                import api_server

                client = TestClient(api_server.app)
                denied = client.get("/api/admin/dataset-availability")
                self.assertEqual(denied.status_code, 403)

                created = client.post(
                    "/api/admin/dataset-availability",
                    headers={"x-admin-token": "secret"},
                    json={
                        "product_id": "gscloud_ndvi_500m_10day",
                        "source_product_key": "modnd1t_china_500m_ndvi_10day",
                        "display_name_zh": "MODND1T 中国 500M NDVI 旬合成产品",
                        "source_url": "https://www.gscloud.cn/sources/accessdata/346?pid=333",
                        "temporal_coverage": {"start": "2000-02-01", "end": "2016-05-31"},
                        "supported_formats": ["zip"],
                        "verification_method": "scene_table_scan",
                        "status": "draft",
                        "version": "admin-fixture-v1",
                    },
                )
                self.assertEqual(created.status_code, 200, created.text)

                listed = client.get("/api/admin/dataset-availability", headers={"x-admin-token": "secret"})
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()["items"], [])

                activated = client.post(
                    "/api/admin/dataset-availability/gscloud_ndvi_500m_10day/status",
                    headers={"x-admin-token": "secret"},
                    json={"status": "active", "actor": "reviewer", "summary": "verified from scene table"},
                )
                self.assertEqual(activated.status_code, 200, activated.text)
                self.assertEqual(activated.json()["item"]["status"], "active")

                listed = client.get("/api/admin/dataset-availability", headers={"x-admin-token": "secret"})
                self.assertEqual(listed.json()["items"][0]["product_id"], "gscloud_ndvi_500m_10day")
                self.assertEqual(listed.json()["items"][0]["temporal_coverage"]["end"], "2016-05-31")

    def test_admin_api_scans_product_availability_as_draft(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with mock.patch.dict(
                os.environ,
                {"GIS_AGENT_CAPABILITY_CONFIG_DIR": str(Path(tmp)), "GIS_AGENT_ADMIN_TOKEN": "secret"},
                clear=False,
            ):
                import api_server

                client = TestClient(api_server.app)
                with mock.patch(
                    "core.dataset_availability_scanner._query_gscloud_boundary",
                    side_effect=["2000-02-01", "2016-05-31"],
                ):
                    response = client.post(
                        "/api/admin/dataset-availability/gscloud_ndvi_500m_10day/scan",
                        headers={"x-admin-token": "secret"},
                        json={"scan_method": "catalog_metadata", "actor": "admin", "summary": "front-end scan"},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertTrue(payload["ok"])
                item = payload["item"]
                self.assertEqual(item["product_id"], "gscloud_ndvi_500m_10day")
                self.assertEqual(item["status"], "draft")
                self.assertEqual(item["verification_method"], "catalog_metadata_scan:public_scene_table")
                self.assertEqual(item["temporal_coverage"], {"start": "2000-02-01", "end": "2016-05-31"})
                self.assertEqual(item["source_url"], "https://www.gscloud.cn/sources/accessdata/346?pid=333")
                self.assertIn("500m", item["supported_resolutions"])
                self.assertIn("时间范围来自数据源公开场景表", " ".join(item.get("warnings") or []))

                runtime_list = client.get("/api/admin/dataset-availability", headers={"x-admin-token": "secret"})
                self.assertEqual(runtime_list.json()["items"], [])

                all_profiles = client.get("/api/admin/dataset-availability?include_inactive=true", headers={"x-admin-token": "secret"})
                self.assertEqual(all_profiles.json()["items"][0]["status"], "draft")


if __name__ == "__main__":
    unittest.main()
