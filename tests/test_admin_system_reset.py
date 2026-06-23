from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService


class AdminSystemResetTests(unittest.TestCase):
    def _with_temp_api(self):
        return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

    def _seed_workspace(self, root: Path) -> dict[str, Path]:
        api_server.base_settings.workdir = root
        api_server.base_settings.ensure_dirs()
        api_server._workspace_services.clear()
        api_server.commercial_service = CommercialService(root)
        user = api_server.commercial_service.register_user("reset@example.com", "password1", plan="pro", user_id="u_reset")
        service = api_server.workspace_for("u_reset")
        service.manager.set_runtime_scope("u_reset", "s_reset")
        upload = service.manager.upload_dir / "input.csv"
        upload.write_text("x,y\n1,2\n", encoding="utf-8")
        artifact_path = service.manager.derived_dir / "result.txt"
        artifact_path.write_text("result", encoding="utf-8")
        service.manager.register_artifact(path=str(artifact_path), type="file", title="result.txt")
        service.manager.database.create_conversation("s_reset", "会话")
        service.manager.database.add_message("s_reset", "user", "hello", {})
        capability_dir = root / "capability_config"
        capability_dir.mkdir(parents=True, exist_ok=True)
        (capability_dir / "knowledge.json").write_text('{"schema_version":"keep"}', encoding="utf-8")
        return {"upload": upload, "artifact": artifact_path, "capability": capability_dir / "knowledge.json"}

    def test_system_reset_requires_admin_token(self) -> None:
        with self._with_temp_api() as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "workspace"
                self._seed_workspace(root)
                with mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
                    response = TestClient(api_server.app).post(
                        "/api/admin/system-reset",
                        json={"mode": "keep_accounts", "confirm_text": "清除用户数据"},
                    )
                self.assertEqual(response.status_code, 403)
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_keep_accounts_reset_removes_workspace_data_but_preserves_user_account_and_config(self) -> None:
        with self._with_temp_api() as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "workspace"
                seeded = self._seed_workspace(root)
                with mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
                    response = TestClient(api_server.app).post(
                        "/api/admin/system-reset",
                        headers={"x-admin-token": "secret"},
                        json={"mode": "keep_accounts", "confirm_text": "清除用户数据"},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertTrue(payload["ok"], payload)
                self.assertEqual(payload["mode"], "keep_accounts")
                self.assertFalse(seeded["upload"].exists())
                self.assertFalse(seeded["artifact"].exists())
                self.assertTrue(seeded["capability"].exists())
                user = api_server.commercial_service.get_user("u_reset")
                self.assertEqual(user["email"], "reset@example.com")
                self.assertEqual(user["plan"], "pro")
                self.assertEqual(api_server.commercial_service.db.fetch_one("SELECT COUNT(*) AS n FROM download_jobs")["n"], 0)
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_full_reset_removes_accounts_and_workspace_data_but_preserves_config(self) -> None:
        with self._with_temp_api() as tmp:
            original_workdir = api_server.base_settings.workdir
            original_commercial = api_server.commercial_service
            original_services = dict(api_server._workspace_services)
            try:
                root = Path(tmp) / "workspace"
                seeded = self._seed_workspace(root)
                with mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
                    response = TestClient(api_server.app).post(
                        "/api/admin/system-reset",
                        headers={"x-admin-token": "secret"},
                        json={"mode": "full_reset", "confirm_text": "全部删除"},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["mode"], "full_reset")
                self.assertFalse(seeded["upload"].exists())
                self.assertFalse(seeded["artifact"].exists())
                self.assertTrue(seeded["capability"].exists())
                self.assertIsNone(api_server.commercial_service.db.fetch_one("SELECT * FROM commercial_users WHERE user_id=?", ["u_reset"]))
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial


if __name__ == "__main__":
    unittest.main()
