from __future__ import annotations

import json
import os
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point
from starlette.exceptions import StarletteDeprecationWarning

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=StarletteDeprecationWarning)
    from starlette.testclient import TestClient

import api_server
from core.agent import GISAgent
from core.commercial.service import CommercialService
from core.commercial.tools import build_commercial_tools
from core.data_manager import DataManager
from core.domestic_sources.tools import build_domestic_tools
from core.gis_tools import build_tools
from core.tool_contracts import parse_tool_result
from core.workflow_executor import execute_workflow_plan, parse_workflow_result


class SecurityHardeningTests(unittest.TestCase):
    def test_export_dataset_rejects_output_path_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            import pandas as pd

            root = Path(tmp)
            manager = DataManager(root / "workspace")
            manager.put_table("safe_table", pd.DataFrame([{"x": 1}]))
            outside = root / "outside.csv"
            tools = {tool.name: tool for tool in build_tools(manager)}

            result = parse_tool_result(tools["export_dataset"].invoke({"dataset_name": "safe_table", "output_path": str(outside)}))

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "OUTPUT_PATH_UNSAFE")
            self.assertFalse(outside.exists())

    def test_workflow_export_artifact_rejects_output_path_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            manager = DataManager(root / "workspace")
            source = manager.plot_dir / "map.png"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"png")
            outside = root / "outside.png"
            plan = {
                "workflow_plan": [
                    {
                        "step_id": "export_map",
                        "tool_name": "export_artifact",
                        "step_type": "export_map",
                        "validated_tool_args": {"source_path": str(source), "output_path": str(outside)},
                    }
                ]
            }

            result = parse_workflow_result(execute_workflow_plan(manager, plan)["raw_reply"])

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["failed_step"], "export_map")
            self.assertEqual(result["steps"][0]["tool_result"]["error_code"], "OUTPUT_PATH_UNSAFE")
            self.assertFalse(outside.exists())

    def test_artifact_download_rejects_cross_user_workspace_access(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "server"
                root.mkdir(parents=True, exist_ok=True)
                api_server._workspace_services.clear()
                api_server.base_settings.workdir = root
                api_server.base_settings.ensure_dirs()
                api_server.commercial_service = CommercialService(root)
                alice = TestClient(api_server.app)
                bob = TestClient(api_server.app)
                alice_user = alice.post("/api/auth/register", json={"email": "alice.sec@example.com", "password": "password1"}).json()["user"]["user_id"]
                bob.post("/api/auth/register", json={"email": "bob.sec@example.com", "password": "password1"})
                alice_service = api_server.workspace_for(alice_user)
                artifact = alice_service.manager.plot_dir / "alice_map.png"
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_bytes(b"png")

                alice_service.manager.set_runtime_scope(alice_user, alice_service.current_session_id)
                registered = alice_service.manager.register_artifact(path=str(artifact), type="image", title="alice map")

                alice_ok = alice.get(
                    f"/api/artifacts/{registered['artifact_id']}/download",
                    params={"user_id": alice_user, "session_id": alice_service.current_session_id},
                )
                bob_no_user = bob.get("/api/files/artifact", params={"path": "plots/alice_map.png"})
                bob_claims_alice = bob.get(
                    f"/api/artifacts/{registered['artifact_id']}/download",
                    params={"user_id": alice_user, "session_id": alice_service.current_session_id},
                )

                self.assertEqual(alice_ok.status_code, 200)
                self.assertEqual(bob_no_user.status_code, 410)
                self.assertEqual(bob_claims_alice.status_code, 403)
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_artifact_download_rejects_url_encoded_path_escape(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "server"
                root.mkdir(parents=True, exist_ok=True)
                api_server._workspace_services.clear()
                api_server.base_settings.workdir = root
                api_server.base_settings.ensure_dirs()
                api_server.commercial_service = CommercialService(root)
                client = TestClient(api_server.app)
                outside = root / "outside.txt"
                outside.write_text("secret", encoding="utf-8")

                response = client.get("/api/files/artifact?path=%2e%2e%2Foutside.txt")

                self.assertEqual(response.status_code, 410)
                self.assertNotEqual(response.text, "secret")
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_upload_rejects_unsupported_file_extension(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "server"
                root.mkdir(parents=True, exist_ok=True)
                api_server._workspace_services.clear()
                api_server.base_settings.workdir = root
                api_server.base_settings.ensure_dirs()
                api_server.commercial_service = CommercialService(root)
                client = TestClient(api_server.app)
                user_id = client.post("/api/auth/register", json={"email": "upload.sec@example.com", "password": "password1"}).json()["user"]["user_id"]

                response = client.post(
                    "/api/files/upload",
                    data={"user_id": user_id},
                    files={"files": ("payload.exe", b"MZ", "application/octet-stream")},
                )

                self.assertEqual(response.status_code, 400)
                self.assertNotIn("payload", api_server.workspace_for(user_id).manager.datasets)
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_upload_filename_path_traversal_is_sanitized_to_uploads_dir(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "server"
                root.mkdir(parents=True, exist_ok=True)
                api_server._workspace_services.clear()
                api_server.base_settings.workdir = root
                api_server.base_settings.ensure_dirs()
                api_server.commercial_service = CommercialService(root)
                client = TestClient(api_server.app)
                user_id = client.post("/api/auth/register", json={"email": "upload-traversal.sec@example.com", "password": "password1"}).json()["user"]["user_id"]

                response = client.post(
                    "/api/files/upload",
                    data={"user_id": user_id},
                    files={"files": ("../evil.csv", b"x,y\n1,2\n", "text/csv")},
                )
                service = api_server.workspace_for(user_id)

                self.assertEqual(response.status_code, 200)
                self.assertFalse((root / "evil.csv").exists())
                uploaded = list(service.manager.upload_dir.glob("*evil.csv"))
                self.assertEqual(len(uploaded), 1)
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_load_path_rejects_file_outside_allowed_roots_by_default(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            workdir = root / "workspace"
            outside = root / "outside.csv"
            outside.write_text("x,y\n1,2\n", encoding="utf-8")

            manager = DataManager(workdir)

            with self.assertRaises(PermissionError):
                manager.load_path(str(outside))

    def test_load_path_allows_file_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp) / "workspace"
            manager = DataManager(workdir)
            inside = manager.upload_dir / "inside.csv"
            inside.parent.mkdir(parents=True, exist_ok=True)
            inside.write_text("x,y\n1,2\n", encoding="utf-8")

            dataset_name = manager.load_path(str(inside))

            self.assertIn(dataset_name, manager.datasets)

    def test_raster_algebra_rejects_unsafe_expression_calls(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            raster_path = Path(tmp) / "source.tif"
            arr = np.ones((3, 3), dtype="float32")
            with rasterio.open(
                raster_path,
                "w",
                driver="GTiff",
                height=3,
                width=3,
                count=1,
                dtype="float32",
                crs="EPSG:3857",
                transform=from_origin(0, 90, 30, 30),
            ) as dst:
                dst.write(arr, 1)
            manager.put_raster_path("r", raster_path, meta={"crs": "EPSG:3857"})
            tools = {tool.name: tool for tool in build_tools(manager)}

            result = parse_tool_result(
                tools["raster_algebra"].invoke(
                    {"expression": "__import__('os').system('echo bad')", "input_rasters": "r=r", "output_name": "bad"}
                )
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["tool_name"], "raster_algebra")

    def test_vector_filter_rejects_unsafe_expression_and_returns_tool_result(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            manager.put_vector(
                "points",
                gpd.GeoDataFrame({"value": [1, 3]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326"),
            )
            tools = {tool.name: tool for tool in build_tools(manager)}

            ok = parse_tool_result(tools["vector_filter"].invoke({"dataset_name": "points", "expression": "value > 1", "output_name": "points_gt1"}))
            blocked = parse_tool_result(
                tools["vector_filter"].invoke(
                    {"dataset_name": "points", "expression": "__import__('os').system('echo bad')", "output_name": "bad"}
                )
            )

            self.assertTrue(ok["ok"])
            self.assertEqual(ok["status"], "succeeded")
            self.assertEqual(ok["outputs"]["feature_count"], 1)
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["error_code"], "VECTOR_FILTER_EXPRESSION_INVALID")

    def test_zip_import_rejects_symlink_entries(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            archive = manager.upload_dir / "unsafe.zip"
            info = zipfile.ZipInfo("linked.txt")
            info.external_attr = (0o120777 << 16)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(info, "target.txt")

            with self.assertRaises(ValueError):
                manager.load_path(str(archive))

    def test_domestic_zip_extract_rejects_symlink_entries(self) -> None:
        from core.domestic_sources.downloader import safe_extract_zip

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            archive = root / "unsafe.zip"
            info = zipfile.ZipInfo("linked.txt")
            info.external_attr = (0o120777 << 16)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(info, "target.txt")

            with zipfile.ZipFile(archive, "r") as zf:
                with self.assertRaises(RuntimeError):
                    safe_extract_zip(zf, root / "out")

    def test_domestic_archive_member_guard_rejects_path_escape(self) -> None:
        from core.domestic_sources.downloader import _assert_archive_members_safe

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)

            with self.assertRaises(RuntimeError):
                _assert_archive_members_safe(["../escape.txt"], root / "out")

            with self.assertRaises(RuntimeError):
                _assert_archive_members_safe(["/tmp/escape.txt"], root / "out")

    def test_domestic_archive_member_guard_allows_nested_members(self) -> None:
        from core.domestic_sources.downloader import _assert_archive_members_safe

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)

            _assert_archive_members_safe(["nested/result.tif", "nested/table.csv"], root / "out")

    def test_admin_boundary_zip_extract_rejects_symlink_entries(self) -> None:
        from core.admin_boundary import _safe_extract_zip

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            archive = root / "unsafe_admin.zip"
            info = zipfile.ZipInfo("linked.txt")
            info.external_attr = (0o120777 << 16)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(info, "target.txt")

            with self.assertRaises(ValueError):
                _safe_extract_zip(archive, root / "out")

    def test_domestic_tools_do_not_return_storage_state_paths(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            tools = {tool.name: tool for tool in build_domestic_tools(manager)}

            sources = tools["list_domestic_data_sources"].invoke({"category": ""})
            status = tools["domestic_login_status"].invoke({"source_key": ""})

            self.assertNotIn("storage_state_path", sources)
            self.assertNotIn("storage_state_path", status)

    def test_domestic_manual_import_rejects_outside_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            manager = DataManager(root / "workspace")
            outside = root / "outside.csv"
            outside.write_text("x,y\n1,2\n", encoding="utf-8")
            tools = {tool.name: tool for tool in build_domestic_tools(manager)}

            with self.assertRaises(PermissionError):
                tools["import_domestic_downloaded_file"].invoke({"file_path": str(outside)})

    def test_put_table_filename_cannot_escape_derived_dir(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            import pandas as pd

            manager = DataManager(Path(tmp) / "workspace")
            dataset = manager.put_table("safe_table", pd.DataFrame([{"x": 1}]), filename="../escape.csv")
            path = manager.get(dataset).path.resolve()

            path.relative_to(manager.derived_dir.resolve())
            self.assertEqual(path.name, "escape.csv")

    def test_commercial_tools_do_not_expose_admin_tools_by_default(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            tool_names = {tool.name for tool in build_commercial_tools(manager)}

            self.assertNotIn("grant_commercial_plan", tool_names)
            self.assertNotIn("add_platform_source_account", tool_names)
            self.assertNotIn("open_gscloud_platform_login_window", tool_names)
            self.assertIn("submit_commercial_download_job", tool_names)

    def test_commercial_tools_can_explicitly_include_admin_tools(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))

            tool_names = {tool.name for tool in build_commercial_tools(manager, include_admin_tools=True)}

            self.assertIn("grant_commercial_plan", tool_names)
            self.assertIn("add_platform_source_account", tool_names)
            self.assertIn("open_gscloud_platform_login_window", tool_names)

    def test_admin_tools_require_admin_token_internally(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            tools = {tool.name: tool for tool in build_commercial_tools(manager, include_admin_tools=True)}

            with patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "expected"}):
                with self.assertRaises(PermissionError):
                    tools["commercial_system_status"].invoke({})

                result = json.loads(tools["commercial_system_status"].invoke({"admin_token": "expected"}))

            self.assertIn("db_path", result)

    def test_browser_automation_tools_require_confirmation_before_execution(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            service = CommercialService(manager.workdir)
            service.register_user("user@example.com", "password1", user_id="u_1")
            job = service.submit_job(
                user_id="u_1",
                source_key="gscloud",
                resource_type="dem",
                account_mode="own",
            )
            tools = {tool.name: tool for tool in build_commercial_tools(manager)}

            first = json.loads(tools["run_gscloud_dem_capture_job"].invoke({"job_id": job["job_id"]}))

            self.assertTrue(first["requires_confirmation"])
            self.assertEqual(first["action"], "run_gscloud_dem_capture_job")
            self.assertEqual(service.get_job(job["job_id"])["status"], "queued")

            second = json.loads(
                tools["run_gscloud_dem_capture_job"].invoke(
                    {"job_id": job["job_id"], "confirmed_action_id": first["confirmed_action_id"]}
                )
            )

            self.assertFalse(second.get("requires_confirmation", False))
            self.assertEqual(second["status"], "failed")

    def test_commercial_local_file_job_rejects_outside_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            manager = DataManager(root / "workspace")
            outside = root / "outside.csv"
            outside.write_text("x,y\n1,2\n", encoding="utf-8")
            service = CommercialService(manager.workdir)
            service.register_user("user@example.com", "password1", user_id="u_1")
            job = service.submit_job(
                user_id="u_1",
                source_key="manual",
                resource_type="table",
                account_mode="own",
                local_file_path=str(outside),
            )
            tools = {tool.name: tool for tool in build_commercial_tools(manager)}

            result = json.loads(tools["run_commercial_download_job"].invoke({"job_id": job["job_id"], "auto_load": False}))

            self.assertEqual(result["status"], "failed")
            self.assertIn("restricted", result["error_message"].lower())

    def test_commercial_gscloud_job_status_tools_hide_internal_paths(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            tools = {tool.name: tool for tool in build_commercial_tools(manager)}
            secret_root = Path(tmp) / "secret"
            raw_job = {
                "job_id": "job_1",
                "login_job_id": "login_1",
                "capture_job_id": "capture_1",
                "tile_job_id": "tile_1",
                "state": "FAILED",
                "status": "failed",
                "stage": "waiting_login",
                "message": "Traceback at storage_state.json",
                "status_path": str(secret_root / "status.json"),
                "log_path": str(secret_root / "worker.log"),
                "storage_state_path": str(secret_root / "storage_state.json"),
                "state_path": str(secret_root / "state.json"),
                "output_path": str(secret_root / "output.tif"),
                "zip_path": str(secret_root / "result.zip"),
                "download_url": "/api/downloads/artifact?path=secret/result.zip",
            }
            for subdir, filename in (
                ("login_jobs", "login_1.json"),
                ("capture_jobs", "capture_1.json"),
                ("tile_jobs", "tile_1.json"),
            ):
                path = manager.workdir / "domestic_auth" / subdir / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(raw_job, ensure_ascii=False), encoding="utf-8")

            payloads = [
                tools["list_gscloud_login_window_jobs"].invoke({"limit": 5}),
                tools["get_gscloud_login_window_job"].invoke({"login_job_id": "login_1"}),
                tools["list_gscloud_capture_window_jobs"].invoke({"limit": 5}),
                tools["get_gscloud_capture_window_job"].invoke({"capture_job_id": "capture_1"}),
                tools["list_gscloud_auto_tile_jobs"].invoke({"limit": 5}),
                tools["get_gscloud_auto_tile_job"].invoke({"tile_job_id": "tile_1"}),
            ]

            rendered = "\n".join(payloads)
            self.assertNotIn("status_path", rendered)
            self.assertNotIn("log_path", rendered)
            self.assertNotIn("storage_state_path", rendered)
            self.assertNotIn("state_path", rendered)
            self.assertNotIn("output_path", rendered)
            self.assertNotIn("zip_path", rendered)
            self.assertNotIn("download_url", rendered)
            self.assertNotIn("storage_state", rendered.lower())
            self.assertNotIn("traceback", rendered.lower())
            self.assertNotIn(str(secret_root), rendered)
            self.assertNotIn("/api/downloads/artifact", rendered)

    def test_commercial_download_job_tools_return_public_projection(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            manager = DataManager(root / "workspace")
            service = CommercialService(manager.workdir)
            service.register_user("user@example.com", "password1", user_id="u_1")
            outside = root / "secret" / "manual.csv"
            outside.parent.mkdir(parents=True, exist_ok=True)
            outside.write_text("x,y\n1,2\n", encoding="utf-8")
            job = service.submit_job(
                user_id="u_1",
                source_key="manual",
                resource_type="table",
                account_mode="own",
                direct_url="https://example.invalid/private.csv?token=secret",
                local_file_path=str(outside),
                request_text=f"load {outside}",
            )
            service._update_job(
                job["job_id"],
                status="completed",
                output_path=str(outside),
                zip_path=str(root / "secret" / "package.zip"),
                error_message="Traceback at storage_state.json",
            )
            tools = {tool.name: tool for tool in build_commercial_tools(manager)}

            payloads = [
                tools["get_commercial_download_job"].invoke({"job_id": job["job_id"]}),
                tools["list_commercial_download_jobs"].invoke({"user_id": "u_1", "limit": 5}),
            ]

            rendered = "\n".join(payloads)
            self.assertIn("tool_result", rendered)
            self.assertIn(job["job_id"], rendered)
            self.assertNotIn("direct_url", rendered)
            self.assertNotIn("local_file_path", rendered)
            self.assertNotIn("request_text", rendered)
            self.assertNotIn("output_path", rendered)
            self.assertNotIn("zip_path", rendered)
            self.assertNotIn("token=secret", rendered)
            self.assertNotIn("storage_state", rendered.lower())
            self.assertNotIn("traceback", rendered.lower())
            self.assertNotIn(str(outside), rendered)

    def test_agent_direct_router_blocks_platform_login_by_default(self) -> None:
        agent = object.__new__(GISAgent)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            agent.manager = DataManager(Path(tmp))

            with patch("core.agent.start_gscloud_login_thread") as start_login:
                result = agent._try_direct_gscloud_login_command("打开地理空间数据云平台账号 pa_test 登录")

            self.assertIsNotNone(result)
            self.assertIn("forbidden", result or "")
            start_login.assert_not_called()

    def test_agent_direct_submit_auto_tiles_reply_uses_public_projection(self) -> None:
        agent = object.__new__(GISAgent)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            agent.manager = DataManager(root / "workspace")
            service = CommercialService(agent.manager.workdir)
            service.register_user("user@example.com", "password1", user_id="u_1")
            state_path = agent.manager.workdir / "domestic_auth" / "user_state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{}", encoding="utf-8")
            service.set_user_credential_storage_state("u_1", "gscloud", str(state_path))
            agent._direct_confirmation_reply = lambda *args, **kwargs: None

            with patch(
                "core.agent.start_gscloud_tile_process",
                return_value={
                    "tile_job_id": "tile_1",
                    "job_id": "job_1",
                    "state": "STARTING",
                    "status_path": str(root / "secret" / "tile_status.json"),
                    "log_path": str(root / "secret" / "tile.log"),
                    "storage_state_path": str(state_path),
                    "message": "Traceback at storage_state.json",
                },
            ):
                result = agent._try_direct_gscloud_submit_auto_tiles_command(
                    "为 user@example.com 提交一个地理空间数据云 DEM 下载任务，区域为四川省，使用自己的账号，输出名为 sichuan_dem_paid。"
                )

            self.assertIsNotNone(result)
            rendered = result or ""
            self.assertIn("tool_result", rendered)
            self.assertIn("auto_tile_job", rendered)
            self.assertNotIn("storage_state_path", rendered)
            self.assertNotIn("status_path", rendered)
            self.assertNotIn("log_path", rendered)
            self.assertNotIn("output_path", rendered)
            self.assertNotIn("zip_path", rendered)
            self.assertNotIn("direct_url", rendered)
            self.assertNotIn("local_file_path", rendered)
            self.assertNotIn("traceback", rendered.lower())
            self.assertNotIn(str(root / "secret"), rendered)
            self.assertNotIn("/api/downloads/artifact", rendered)

    def test_agent_direct_tile_status_reply_uses_public_projection(self) -> None:
        agent = object.__new__(GISAgent)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            agent.manager = DataManager(root / "workspace")
            status_path = agent.manager.workdir / "domestic_auth" / "tile_jobs" / "tile_1.json"
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(
                json.dumps(
                    {
                        "tile_job_id": "tile_1",
                        "job_id": "job_1",
                        "state": "FAILED",
                        "message": "Traceback at storage_state.json",
                        "status_path": str(status_path),
                        "log_path": str(root / "secret" / "tile.log"),
                        "storage_state_path": str(root / "secret" / "storage_state.json"),
                        "download_url": "/api/downloads/artifact?path=secret/result.zip",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = agent._try_direct_gscloud_tile_status_command("列出地理空间数据云 DEM 自动分幅下载后台任务状态")

            self.assertIsNotNone(result)
            rendered = result or ""
            self.assertIn("tile_1", rendered)
            self.assertNotIn("storage_state_path", rendered)
            self.assertNotIn("status_path", rendered)
            self.assertNotIn("log_path", rendered)
            self.assertNotIn("download_url", rendered)
            self.assertNotIn("traceback", rendered.lower())
            self.assertNotIn(str(root / "secret"), rendered)
            self.assertNotIn("/api/downloads/artifact", rendered)

    def test_agent_direct_confirmation_reply_requires_token_round_trip(self) -> None:
        agent = object.__new__(GISAgent)
        first = agent._direct_confirmation_reply("start_gscloud_dem_capture_job", "start", job_id="job_1")

        self.assertIsNotNone(first)
        payload = json.loads(first or "{}")
        self.assertTrue(payload["requires_confirmation"])

        second = agent._direct_confirmation_reply(
            "start_gscloud_dem_capture_job",
            f"start {payload['confirmed_action_id']}",
            job_id="job_1",
        )

        self.assertIsNone(second)

    def test_agent_system_prompt_does_not_recommend_admin_tools(self) -> None:
        from core.agent import SYSTEM_PROMPT

        for tool_name in (
            "commercial_system_status",
            "create_commercial_customer",
            "grant_commercial_plan",
            "add_platform_source_account",
            "open_gscloud_platform_login_window",
        ):
            self.assertNotIn(tool_name, SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
