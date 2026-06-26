from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from core.config import Settings
from core.area_resolver import resolve_area_candidates
from core.commercial.service import CommercialService
from core.data_manager import DataManager
from core.download_request_executor import _start_real_adapter, execute_download_requests
from core.management_views import download_job_to_management_view
from core.service import GISWorkspaceService
from core.task_plan_schema import validate_llm_task_plan
from core.tool_context import ToolRuntimeContext


pytestmark = pytest.mark.slow


def _request(product_id: str, status: str, *, time_range: dict | None = None) -> dict:
    return {
        "area_asset_id": "library:basin:shandianhe",
        "area_source": "user_selected_default_library",
        "product_id": product_id,
        "requested_resolution": "",
        "resolved_resolution": "250m" if "evi" in product_id else "10m",
        "time_range": time_range or {"start": "2010-08-16", "end": "2010-08-16"},
        "download_parameters": {"fixture_status": status, "account_mode": "own"},
        "source_attribution": {"area": "user_selected_default_library", "product": "product_catalog"},
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": False,
    }


class GenericDownloadExecutionTests(unittest.TestCase):
    def test_dynamic_area_resolver_materializes_city_boundary_asset(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            candidates = resolve_area_candidates("下载资阳市30m DEM", manager=manager)

            self.assertTrue(candidates)
            first = candidates[0]
            self.assertEqual(first["area_source"], "local_admin_boundary")
            self.assertEqual(first["admin_level"], "city")
            self.assertEqual(first["name"], "资阳市")
            self.assertTrue(first["geometry_asset_id"])
            self.assertIn(first["geometry_asset_id"], manager.list_dataset_names())
            self.assertGreaterEqual(first["feature_count"], 1)
            self.assertEqual(first["crs"], "EPSG:4326")
            self.assertEqual(first["dissolve_method"], "county_units_dissolve")

    def test_dynamic_area_resolver_returns_real_ambiguous_county_candidates(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            candidates = resolve_area_candidates("市中区", manager=manager, limit=5)

            self.assertGreaterEqual(len(candidates), 2)
            self.assertEqual({item["name"] for item in candidates}, {"市中区"})
            self.assertGreaterEqual(len({item["province"] + item["city"] for item in candidates}), 2)
            self.assertTrue(all(item["geometry_asset_id"] in manager.list_dataset_names() for item in candidates))

    def test_multi_product_executor_returns_independent_canonical_results(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope("u_download", "s_download")
            context = {
                "response_language": "zh-CN",
                "candidate_tool_cards": [{"tool_name": "submit_commercial_download_job"}],
                "area_candidates": resolve_area_candidates("下载闪电河流域EVI和Sentinel", manager=manager),
            }
            plan_payload = {
                "primary_goal": "download_multiple_products",
                "intent": "data_download",
                "operation": "download_data",
                "input_assets": [],
                "asset_roles": {},
                "download_requests": [
                    _request("gscloud_evi_250m_10day", "succeeded"),
                    _request("gscloud_sentinel2_msi", "waiting_login"),
                ],
                "requested_downloads": [
                    _request("gscloud_evi_250m_10day", "succeeded"),
                    _request("gscloud_sentinel2_msi", "waiting_login"),
                ],
                "study_area": "library:basin:shandianhe",
                "time_range": {"start": "2010-08-16", "end": "2010-08-16"},
                "spatial_resolution": "",
                "candidate_tools": ["submit_commercial_download_job"],
                "selected_tools": ["submit_commercial_download_job"],
                "workflow_steps": [],
                "expected_outputs": ["download_job", "artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {"library:basin:shandianhe": "user_selected_default_library"},
                "explicit_history_references": [],
                "response_language": "zh-CN",
            }
            validated = validate_llm_task_plan(plan_payload, context)
            self.assertTrue(validated["ok"], validated.get("errors"))

            result = execute_download_requests(
                manager,
                validated["plan"],
                context=context,
                runtime_context=ToolRuntimeContext(
                    current_user_id="u_download",
                    current_session_id="s_download",
                    workspace_dir=manager.workdir,
                    permission_scope={"workspace:read", "workspace:write"},
                ),
            )

            self.assertTrue(result["executed"])
            self.assertIn("execution_trace", result)
            self.assertEqual(len(result["tool_results"]), 2)
            statuses = {item["outputs"]["product_id"]: item["status"] for item in result["tool_results"]}
            self.assertEqual(statuses["gscloud_evi_250m_10day"], "succeeded")
            self.assertEqual(statuses["gscloud_sentinel2_msi"], "awaiting_confirmation")
            successful = next(item for item in result["tool_results"] if item["status"] == "succeeded")
            self.assertTrue(successful["artifacts"])
            self.assertTrue(manager.get_artifact(successful["artifacts"][0]["artifact_id"]))
            views = [download_job_to_management_view(item["outputs"]["job"], tool_result=item) for item in result["tool_results"]]
            self.assertEqual({view["status"] for view in views}, {"succeeded", "awaiting_confirmation"})
            self.assertTrue(any(view["artifact_refs"] for view in views))

    def test_real_adapter_maps_landsat_and_mod021km_to_scene_workers(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            service = CommercialService(root)
            user = service.register_user("scene@example.com", "password1", plan="pro", user_id="u_scene")
            state_path = root / "domestic_auth" / "fixture_storage_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text('{"cookies":[{"domain":".gscloud.cn","name":"sessionid","value":"ok","expires":9999999999}]}', encoding="utf-8")
            account = service.add_platform_account(
                source_key="gscloud",
                label="fixture",
                daily_limit=10,
                monthly_limit=100,
                storage_state_path=str(state_path),
            )
            area = {"name": "成都市", "asset_id": "admin:city:四川省:成都市"}
            request = {
                "time_range": {"start": "2010-08-16", "end": "2010-08-16"},
                "download_parameters": {"max_scenes": 2, "cloud_max": 25, "headless": True, "auto_load": False},
            }

            landsat_job = service.submit_job(
                user_id=user["user_id"],
                source_key="gscloud",
                resource_type="landsat8_oli_tirs",
                account_mode="platform",
                region="成都市",
                start_date="2010-08-16",
                end_date="2010-08-16",
                request_text="下载 Landsat 8 OLI_TIRS",
                output_name="landsat_fixture",
            )
            service.db.update_dict("download_jobs", {"account_id": account["account_id"]}, "job_id=?", [landsat_job["job_id"]])
            mod021km_job = service.submit_job(
                user_id=user["user_id"],
                source_key="gscloud",
                resource_type="mod021km_surface_reflectance",
                account_mode="platform",
                region="成都市",
                start_date="2010-08-16",
                end_date="2010-08-16",
                request_text="下载 MOD021KM 地表反射率",
                output_name="mod021km_fixture",
            )
            service.db.update_dict("download_jobs", {"account_id": account["account_id"]}, "job_id=?", [mod021km_job["job_id"]])

            with mock.patch("core.download_request_executor.start_gscloud_landsat8_process", return_value={"scene_job_id": "scene_landsat", "product_key": "landsat8_oli_tirs"}) as landsat_start:
                job, scene, tile = _start_real_adapter(
                    service,
                    service.get_job(landsat_job["job_id"]),
                    product={"product_id": "gscloud_landsat8_oli_tirs", "download_adapter": "gscloud_scene_table"},
                    request=request,
                    area=area,
                )
            self.assertEqual(job["status"], "running")
            self.assertEqual(scene["scene_job_id"], "scene_landsat")
            self.assertIsNone(tile)
            landsat_start.assert_called_once()
            self.assertEqual(landsat_start.call_args.kwargs["cloud_max"], 25.0)

            with mock.patch("core.download_request_executor.start_gscloud_mod021km_process", return_value={"scene_job_id": "scene_mod021km", "product_key": "mod021km_1km_surface_reflectance"}) as mod021km_start:
                job, scene, tile = _start_real_adapter(
                    service,
                    service.get_job(mod021km_job["job_id"]),
                    product={"product_id": "gscloud_surface_reflectance_1km", "download_adapter": "gscloud_scene_table"},
                    request=request,
                    area=area,
                )
            self.assertEqual(job["status"], "running")
            self.assertEqual(scene["scene_job_id"], "scene_mod021km")
            self.assertIsNone(tile)
            mod021km_start.assert_called_once()

    def test_download_executor_reuses_idempotent_durable_job(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope("u_download", "s_download")
            context = {
                "response_language": "zh-CN",
                "candidate_tool_cards": [{"tool_name": "submit_commercial_download_job"}],
                "area_candidates": resolve_area_candidates("下载闪电河流域EVI", manager=manager),
            }
            request = _request("gscloud_evi_250m_10day", "succeeded")
            request["download_parameters"]["idempotency_key"] = "same-validated-download"
            plan = {
                "primary_goal": "download_evi",
                "intent": "data_download",
                "operation": "download_data",
                "download_requests": [request],
                "requested_downloads": [request],
            }
            runtime = ToolRuntimeContext(
                current_user_id="u_download",
                current_session_id="s_download",
                workspace_dir=manager.workdir,
                permission_scope={"workspace:read", "workspace:write"},
            )

            first = execute_download_requests(manager, plan, context=context, runtime_context=runtime)
            second = execute_download_requests(manager, plan, context=context, runtime_context=runtime)

            first_job_id = first["tool_results"][0]["outputs"]["job"]["job_id"]
            second_job_id = second["tool_results"][0]["outputs"]["job"]["job_id"]
            self.assertEqual(first_job_id, second_job_id)
            self.assertTrue(second["tool_results"][0]["diagnostics"]["idempotency_reused"])
            jobs = CommercialService(Path(manager.workdir)).list_jobs("u_download", session_id="s_download", limit=10)
            self.assertEqual([job["job_id"] for job in jobs].count(first_job_id), 1)

    def test_real_download_outputs_are_registered_as_session_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope("u_download", "s_download")
            external_dir = Path(tmp) / "shared_outputs"
            external_dir.mkdir(parents=True, exist_ok=True)
            zip_path = external_dir / "chengdu_dem.zip"
            tif_path = external_dir / "chengdu_dem.tif"
            zip_path.write_bytes(b"PK\x03\x04registered zip fixture")
            tif_path.write_bytes(b"II*\x00registered tif fixture")
            context = {
                "response_language": "zh-CN",
                "candidate_tool_cards": [{"tool_name": "submit_commercial_download_job"}],
                "area_candidates": resolve_area_candidates("下载成都市30m DEM", manager=manager),
            }
            request = {
                "area_asset_id": "admin:city:四川省:成都市",
                "area_source": "local_admin_boundary",
                "product_id": "gscloud_dem_30m",
                "requested_resolution": "30m",
                "resolved_resolution": "30m",
                "time_range": {},
                "download_parameters": {"account_mode": "own"},
                "source_attribution": {"area": "local_admin_boundary", "product": "product_catalog"},
                "expected_outputs": ["download_job", "artifact"],
                "requires_confirmation": False,
            }
            plan = {
                "primary_goal": "download_dem",
                "intent": "data_download",
                "operation": "download_data",
                "download_requests": [request],
                "requested_downloads": [request],
            }
            runtime = ToolRuntimeContext(
                current_user_id="u_download",
                current_session_id="s_download",
                workspace_dir=manager.workdir,
                permission_scope={"workspace:read", "workspace:write"},
            )

            def fake_start(service: CommercialService, job: dict, **_: object):
                completed = service.run_job_with_result(
                    str(job["job_id"]),
                    {
                        "zip_path": str(zip_path),
                        "output_path": str(tif_path),
                        "artifact_quality": [{"ok": True, "path": str(tif_path), "reason": "fixture_validated"}],
                    },
                )
                completed["zip_path"] = str(zip_path)
                completed["output_path"] = str(tif_path)
                return completed, None, {"tile_job_id": "tile_fixture", "job_id": job["job_id"], "state": "COMPLETED"}

            with mock.patch("core.download_request_executor._start_real_adapter", side_effect=fake_start):
                result = execute_download_requests(manager, plan, context=context, runtime_context=runtime)
                second = execute_download_requests(manager, plan, context=context, runtime_context=runtime)

            tool_result = result["tool_results"][0]
            self.assertEqual(tool_result["status"], "succeeded")
            self.assertGreaterEqual(len(tool_result["artifacts"]), 2)
            for artifact in tool_result["artifacts"]:
                artifact_id = artifact["artifact_id"]
                self.assertTrue(artifact_id.startswith("artifact_"), artifact)
                self.assertFalse(artifact_id.startswith("download:"), artifact)
                registered = manager.get_artifact(artifact_id)
                self.assertIsNotNone(registered, artifact)
                self.assertEqual(registered["session_id"], "s_download")
                self.assertTrue(Path(registered["path"]).exists())
            view = tool_result["diagnostics"]["management_view"]
            self.assertTrue(view["artifact_refs"])
            self.assertTrue(all(str(item["artifact_id"]).startswith("artifact_") for item in view["artifact_refs"]))
            self.assertEqual(second["tool_results"][0]["status"], "succeeded")
            first_job_id = str(tool_result["outputs"]["job"]["job_id"])
            copied_files = list((manager.derived_dir / "downloads" / first_job_id).glob("*"))
            self.assertLessEqual(len(copied_files), 2)
            listed_titles = [str(item.get("title") or item.get("name") or "") for item in manager.list_artifacts()]
            self.assertFalse(any("_2." in title or "_3." in title for title in listed_titles))

    def test_global_workspace_download_output_is_imported_into_session_scope(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            manager = DataManager(root)
            manager.set_runtime_scope("u_download", "s_download")
            global_derived = root / "derived"
            global_derived.mkdir(parents=True, exist_ok=True)
            zip_path = global_derived / "chengdu_ndvi.zip"
            tif_path = global_derived / "chengdu_ndvi_clipped.tif"
            package_path = global_derived / "chengdu_ndvi_domestic_download.zip"
            zip_path.write_bytes(b"PK\x03\x04ndvi package")
            tif_path.write_bytes(b"II*\x00ndvi raster")
            package_path.write_bytes(b"PK\x03\x04raw ndvi package")
            job = {
                "job_id": "job_ndvi_global",
                "status": "completed",
                "zip_path": str(zip_path),
                "output_path": str(tif_path),
                "result": {"zip_path": str(zip_path), "output_path": str(tif_path), "package_path": str(package_path)},
            }

            from core.download_request_executor import _registered_download_artifacts

            artifacts = _registered_download_artifacts(
                manager,
                job,
                product={"product_id": "gscloud_ndvi_500m_10day", "resource_type": "raster"},
            )

            self.assertEqual(len(artifacts), 3)
            session_download_dir = manager.derived_dir / "downloads" / "job_ndvi_global"
            for artifact in artifacts:
                registered = manager.get_artifact(artifact["artifact_id"])
                self.assertIsNotNone(registered)
                registered_path = Path(str(registered["path"])).resolve(strict=False)
                self.assertTrue(registered_path.is_relative_to(session_download_dir.resolve(strict=False)))
                self.assertEqual(registered["session_id"], "s_download")
                self.assertEqual(registered["owner_user_id"], "u_download")
            self.assertTrue((session_download_dir / zip_path.name).exists())
            self.assertTrue((session_download_dir / tif_path.name).exists())
            self.assertTrue((session_download_dir / package_path.name).exists())

    def test_chat_service_executes_validated_download_requests_with_presentation_result(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            settings = Settings(api_key="", workdir=Path(tmp) / "workspace")
            settings.ensure_dirs()
            service = GISWorkspaceService(settings)
            service.current_user_id = "u_download"
            service.current_session_id = service.create_new_session()
            service.set_interaction_mode("tool_enabled")
            request = _request("gscloud_evi_250m_10day", "succeeded")
            plan_payload = {
                "primary_goal": "download_evi",
                "intent": "data_download",
                "operation": "download_data",
                "input_assets": [],
                "asset_roles": {},
                "download_requests": [request],
                "requested_downloads": [request],
                "study_area": "library:basin:shandianhe",
                "time_range": {"start": "2010-08-16", "end": "2010-08-16"},
                "spatial_resolution": "250m",
                "candidate_tools": ["submit_commercial_download_job"],
                "selected_tools": ["submit_commercial_download_job"],
                "workflow_steps": [],
                "expected_outputs": ["download_job", "artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {"library:basin:shandianhe": "user_selected_default_library"},
                "explicit_history_references": [],
                "response_language": "zh-CN",
            }

            with mock.patch(
                "core.service.build_llm_task_plan",
                return_value={"status": "ready", "mode": "active", "executes_tools": True, "plan": plan_payload},
            ):
                result = service.ask("下载闪电河流域2010年8月16日的EVI数据")

            self.assertEqual(result["mode"], "validated_download_executor")
            self.assertIn("presentation_result", result)
            self.assertTrue(result["download_management_views"])
            assistant = [item for item in service.manager.database.list_messages(service.current_session_id) if item["role"] == "assistant"][-1]
            self.assertEqual(assistant["meta"]["mode"], "validated_download_executor")
            self.assertIn("execution_trace", assistant["meta"])
            self.assertFalse(assistant["meta"]["deprecated_raw_job_api_used"])


if __name__ == "__main__":
    unittest.main()
