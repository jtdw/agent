from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService


class CheckpointArtifactApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_workdir = api_server.base_settings.workdir
        self.original_commercial = api_server.commercial_service
        self.original_services = dict(api_server._workspace_services)
        root = Path(self.tmp.name) / "workspace"
        api_server._workspace_services.clear()
        api_server.base_settings.workdir = root
        api_server.base_settings.ensure_dirs()
        api_server.commercial_service = CommercialService(root)
        self.client = TestClient(api_server.app)
        self.user_id = self.client.post("/api/auth/register", json={"email": "artifact@example.com", "password": "password1"}).json()["user"]["user_id"]
        self.service = api_server.workspace_for(self.user_id)
        self.service.set_request_context(self.user_id, self.service.current_session_id)

    def tearDown(self) -> None:
        api_server._workspace_services.clear()
        api_server._workspace_services.update(self.original_services)
        api_server.base_settings.workdir = self.original_workdir
        api_server.commercial_service = self.original_commercial
        self.tmp.cleanup()

    def test_artifact_metadata_and_download_use_artifact_id(self) -> None:
        path = self.service.manager.derived_dir / "result.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_csv_result",
            path=str(path),
            type="csv",
            title="result.csv",
            meta={"tool_name": "export_dataset", "workflow_id": "workflow_1", "message_id": 9},
        )

        meta_response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}")
        download = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(meta_response.status_code, 200)
        payload = meta_response.json()
        self.assertEqual(payload["artifact_id"], "artifact_csv_result")
        self.assertEqual(payload["filename"], "result.csv")
        self.assertEqual(payload["source"]["tool_name"], "export_dataset")
        self.assertNotIn(str(self.service.manager.workdir), str(payload))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content.replace(b"\r\n", b"\n"), b"a,b\n1,2\n")

    def test_artifact_download_blocks_sensitive_files(self) -> None:
        secret = self.service.manager.workdir / "workspace.db"
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_db",
            path=str(secret),
            type="db",
            title="workspace.db",
        )

        response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(response.status_code, 403)

    def test_artifact_download_reports_cleaned_or_empty_file_in_chinese(self) -> None:
        empty = self.service.manager.derived_dir / "empty.csv"
        empty.write_text("", encoding="utf-8")
        artifact = self.service.manager.register_artifact(
            artifact_id="artifact_empty",
            path=str(empty),
            type="csv",
            title="empty.csv",
        )

        response = self.client.get(f"/api/artifacts/{artifact['artifact_id']}/download")

        self.assertEqual(response.status_code, 404)
        self.assertIn("文件已清理、无访问权限或下载链接已失效", str(response.json()))

    def test_delete_artifact_removes_registered_file(self) -> None:
        path = self.service.manager.derived_dir / "delete_me.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        self.service.manager.register_artifact(
            artifact_id="artifact_delete_me",
            path=str(path),
            type="csv",
            title="delete_me.csv",
        )

        response = self.client.delete("/api/artifacts/artifact_delete_me?delete_file=true")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["file_deleted"])
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
