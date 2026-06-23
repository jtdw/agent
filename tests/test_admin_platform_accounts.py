from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService


class AdminPlatformAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_workdir = api_server.base_settings.workdir
        self.original_commercial = api_server.commercial_service
        self.original_services = dict(api_server._workspace_services)
        self.tmp = tempfile.TemporaryDirectory(prefix="admin_platform_account_", ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        api_server._workspace_services.clear()
        api_server.base_settings.workdir = root
        api_server.base_settings.ensure_dirs()
        api_server.commercial_service = CommercialService(root)
        self.client = TestClient(api_server.app)

    def tearDown(self) -> None:
        api_server._workspace_services.clear()
        api_server._workspace_services.update(self.original_services)
        api_server.base_settings.workdir = self.original_workdir
        api_server.commercial_service = self.original_commercial
        self.tmp.cleanup()

    def test_platform_account_management_is_admin_only_and_sanitized(self) -> None:
        headers = {"x-admin-token": "secret"}
        with mock.patch.dict(os.environ, {"GIS_AGENT_ADMIN_TOKEN": "secret"}, clear=False):
            denied = self.client.get("/api/admin/platform-accounts")
            self.assertEqual(403, denied.status_code)

            created = self.client.post(
                "/api/admin/platform-accounts",
                headers=headers,
                json={
                    "source_key": "gscloud",
                    "label": "测试平台账号",
                    "username": "demo_user",
                    "password": "demo_password",
                    "daily_limit": 3,
                    "monthly_limit": 20,
                },
            )
            self.assertEqual(200, created.status_code, created.text)
            account = created.json()["account"]
            self.assertEqual("测试平台账号", account["label"])
            self.assertTrue(account["has_password"])
            self.assertNotIn("password", account)
            self.assertNotIn("encrypted_password", account)
            self.assertNotIn("storage_state_path", account)

            account_id = account["account_id"]
            listed = self.client.get("/api/admin/platform-accounts?include_inactive=true", headers=headers)
            self.assertEqual(200, listed.status_code, listed.text)
            listed_account = listed.json()["accounts"][0]
            self.assertEqual(account_id, listed_account["account_id"])
            self.assertFalse(listed_account["login_health"]["ok"])
            self.assertNotIn("path", listed_account["login_health"])

            with mock.patch.object(api_server, "start_gscloud_login_process", return_value={
                "login_job_id": "login_test",
                "state": "BROWSER_OPENING",
                "message": "已打开登录窗口。",
                "timeout_seconds": 300,
                "created_at": "2026-06-24 12:00:00",
                "updated_at": "2026-06-24 12:00:00",
                "status_path": "E:/should/not/leak.json",
                "log_path": "E:/should/not/leak.log",
            }):
                login = self.client.post(f"/api/admin/platform-accounts/{account_id}/login", headers=headers, json={"timeout_seconds": 300})
            self.assertEqual(200, login.status_code, login.text)
            login_job = login.json()["login_job"]
            self.assertEqual("login_test", login_job["login_job_id"])
            self.assertNotIn("status_path", login_job)
            self.assertNotIn("log_path", login_job)

            disabled = self.client.post(f"/api/admin/platform-accounts/{account_id}/status", headers=headers, json={"status": "disabled"})
            self.assertEqual(200, disabled.status_code, disabled.text)
            self.assertEqual("disabled", disabled.json()["account"]["status"])


if __name__ == "__main__":
    unittest.main()
