from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService
from core.config import Settings
from core.data_manager import DataManager
from core.service import GISWorkspaceService
from domain.artifacts.policies import shapefile_zip_path


class MultiSessionDownloadSecurityTests(unittest.TestCase):
    def test_session_filtered_jobs_include_same_user_legacy_unscoped_failures(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = CommercialService(Path(tmp) / "workspace")
            user = service.register_user("legacy-job@example.com", "password1")
            legacy = service.submit_job(
                user_id=user["user_id"],
                source_key="gscloud",
                resource_type="modnd1t_ndvi_10day",
                region="闪电河流域",
                account_mode="direct_url",
                request_text="下载闪电河流域的ndvi数据",
                output_name="shandianhe_modnd1t_ndvi",
            )
            service.fail_job(legacy["job_id"], "selected scene could not be relocated")

            jobs = service.list_jobs(user_id=user["user_id"], session_id="session_current")

            self.assertTrue(any(job["job_id"] == legacy["job_id"] for job in jobs))

    def test_artifact_download_rejects_sensitive_names_extensions_and_markers(self) -> None:
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
                user_id = client.post("/api/auth/register", json={"email": "sensitive@example.com", "password": "password1"}).json()["user"]["user_id"]
                service = api_server.workspace_for(user_id)
                service.set_request_context(user_id, service.current_session_id)

                cases = [
                    (service.manager.derived_dir / ".env", "artifact_env"),
                    (service.manager.derived_dir / "result.sqlite", "artifact_sqlite"),
                    (service.manager.derived_dir / "token_report.txt", "artifact_token"),
                    (service.manager.derived_dir / "storage_state" / "state.json", "artifact_storage_state"),
                ]
                for path, artifact_id in cases:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("secret", encoding="utf-8")
                    service.manager.register_artifact(artifact_id=artifact_id, path=str(path), type="file", title=path.name)
                    response = client.get(
                        f"/api/artifacts/{artifact_id}/download",
                        params={"user_id": user_id, "session_id": service.current_session_id},
                    )
                    self.assertEqual(response.status_code, 403, artifact_id)
                    self.assertNotEqual(response.text, "secret")
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_shapefile_zip_path_uses_artifact_id_to_avoid_collisions(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            first = root / "sessions" / "s1" / "derived" / "same.shp"
            second = root / "sessions" / "s2" / "derived" / "same.shp"
            for path, content in ((first, "one"), (second, "two")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                path.with_suffix(".dbf").write_text(content, encoding="utf-8")

            first_zip = shapefile_zip_path(root, first, "artifact_first")
            second_zip = shapefile_zip_path(root, second, "artifact_second")

            self.assertNotEqual(first_zip, second_zip)
            self.assertIn("artifact_first", first_zip.name)
            self.assertIn("artifact_second", second_zip.name)
            self.assertTrue(first_zip.exists())
            self.assertTrue(second_zip.exists())

    def test_zip_import_requires_explicit_member_when_multiple_dataset_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            archive = manager.upload_dir / "multi.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("a.csv", "x,y\n1,2\n")
                zf.writestr("b.csv", "x,y\n3,4\n")

            with self.assertRaises(ValueError) as ctx:
                manager.load_path(str(archive))

            message = str(ctx.exception)
            self.assertIn("multiple dataset candidates", message)
            self.assertIn("a.csv", message)
            self.assertIn("b.csv", message)

            loaded = manager.load_path(str(archive), zip_member="b.csv")
            self.assertIn(loaded, manager.datasets)
            self.assertEqual(manager.preview_table_rows(loaded, rows=1)[0]["x"], 3)

    def test_upload_streaming_limit_removes_partial_files(self) -> None:
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
                user_id = client.post("/api/auth/register", json={"email": "stream@example.com", "password": "password1"}).json()["user"]["user_id"]

                with patch.object(api_server, "MAX_UPLOAD_BYTES", 12):
                    response = client.post(
                        "/api/files/upload",
                        data={"user_id": user_id},
                        files={"files": ("large.csv", b"x,y\n1234567890\n", "text/csv")},
                    )

                service = api_server.workspace_for(user_id)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(list(service.manager.upload_dir.glob("*large.csv")), [])
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_explicit_missing_session_returns_404_for_workspace_api(self) -> None:
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
                user_id = client.post("/api/auth/register", json={"email": "missing-session@example.com", "password": "password1"}).json()["user"]["user_id"]
                service = api_server.workspace_for(user_id)
                original = service.current_session_id

                response = client.get("/api/workspace/dashboard", params={"user_id": user_id, "session_id": "session_missing"})

                self.assertEqual(response.status_code, 404)
                self.assertEqual(service.current_session_id, original)
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial


if __name__ == "__main__":
    unittest.main()
