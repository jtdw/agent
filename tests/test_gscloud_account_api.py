from __future__ import annotations

import json
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService
from core.config import Settings
from core.service import GISWorkspaceService


class GSCloudAccountApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.workdir = self.root / "workspace"
        self.commercial = CommercialService(self.workdir)
        self.workspace = GISWorkspaceService(Settings(api_key="", workdir=self.workdir))
        self.original_commercial = api_server.commercial_service
        self.original_base_settings = api_server.base_settings
        api_server.commercial_service = self.commercial
        api_server.base_settings = Settings(api_key="", workdir=self.workdir)
        api_server._workspace_services.clear()
        api_server._workspace_services[self.user_id if hasattr(self, "user_id") else "anonymous"] = self.workspace
        self.client = TestClient(api_server.app)
        response = self.client.post(
            "/api/auth/register",
            json={"email": "gscloud-user@example.com", "password": "secret123"},
        )
        self.assertEqual(response.status_code, 200)
        self.user_id = response.json()["user"]["user_id"]
        api_server._workspace_services[self.user_id] = GISWorkspaceService(Settings(api_key="", workdir=self.workdir / "users" / self.user_id))

    def tearDown(self) -> None:
        api_server.commercial_service = self.original_commercial
        api_server.base_settings = self.original_base_settings
        api_server._workspace_services.clear()
        self.tmp.cleanup()

    def test_status_is_public_and_reports_missing_login(self) -> None:
        response = self.client.get("/api/data-sources/gscloud/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["provider"], "gscloud")
        self.assertFalse(payload["logged_in"])
        self.assertFalse(payload["storage_state_exists"])
        self.assertNotIn("storage_state_path", payload)
        self.assertNotIn("cookies", json.dumps(payload).lower())

    def test_login_start_and_complete_save_validated_state(self) -> None:
        state_path = self.workdir / "domestic_auth" / f"user_{self.user_id}_gscloud_storage_state.json"

        def fake_start(**kwargs):
            self.assertEqual(kwargs["subject_id"], self.user_id)
            Path(kwargs["state_path"]).parent.mkdir(parents=True, exist_ok=True)
            Path(kwargs["state_path"]).write_text(
                json.dumps({"cookies": [{"name": "session", "value": "masked", "domain": ".gscloud.cn", "expires": 4102444800}], "origins": []}),
                encoding="utf-8",
            )
            return {"login_job_id": "login_test", "state": "COMPLETED", "message": "ok"}

        with patch("services.data_sources.gscloud_accounts.start_gscloud_login_process", side_effect=fake_start):
            started = self.client.post("/api/data-sources/gscloud/login/start", json={})
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["login_session_id"], "login_test")

        with patch(
            "services.data_sources.gscloud_accounts.read_gscloud_login_job",
            return_value={"login_job_id": "login_test", "subject_type": "customer", "subject_id": self.user_id, "state": "COMPLETED"},
        ):
            completed = self.client.post(
                "/api/data-sources/gscloud/login/complete",
                json={"login_session_id": "login_test"},
            )
        self.assertEqual(completed.status_code, 200)
        self.assertTrue(completed.json()["logged_in"])
        self.assertEqual(self.commercial.get_user_storage_state_path(self.user_id, "gscloud"), str(state_path))

    def test_cookie_file_does_not_complete_login_while_browser_is_open(self) -> None:
        state_path = self.workdir / "domestic_auth" / f"user_{self.user_id}_gscloud_storage_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"cookies": [{"name": "prelogin", "value": "masked", "domain": ".gscloud.cn", "expires": 4102444800}], "origins": []}),
            encoding="utf-8",
        )

        with patch(
            "services.data_sources.gscloud_accounts.read_gscloud_login_job",
            return_value={"login_job_id": "login_test", "subject_type": "customer", "subject_id": self.user_id, "state": "BROWSER_OPEN"},
        ):
            response = self.client.post(
                "/api/data-sources/gscloud/login/complete",
                json={"login_session_id": "login_test"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["pending"])
        self.assertFalse(response.json()["logged_in"])

    def test_logout_removes_state_and_marks_logged_out(self) -> None:
        state_path = self.workdir / "domestic_auth" / f"user_{self.user_id}_gscloud_storage_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
        self.commercial.set_user_credential_storage_state(self.user_id, "gscloud", str(state_path))

        response = self.client.delete("/api/data-sources/gscloud/logout")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(state_path.exists())
        self.assertFalse(self.client.get("/api/data-sources/gscloud/status").json()["logged_in"])

    def test_resume_uses_same_waiting_login_job(self) -> None:
        job = self.commercial.submit_job(
            user_id=self.user_id,
            source_key="gscloud",
            resource_type="dem",
            region="成都",
            account_mode="own",
            request_text="下载成都 DEM",
        )
        self.commercial._update_job(job["job_id"], status="waiting_login", stage="needs_gscloud_login_state")
        state_path = self.workdir / "domestic_auth" / f"user_{self.user_id}_gscloud_storage_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text('{"cookies": [{"name":"session","value":"x","domain":"gscloud.cn","expires":4102444800}], "origins": []}', encoding="utf-8")
        self.commercial.set_user_credential_storage_state(self.user_id, "gscloud", str(state_path))

        with patch("api_server._maybe_start_gscloud_auto_download", return_value={"auto_supported": True, "auto_started": True, "reason": "started"}):
            response = self.client.post(f"/api/download-jobs/{job['job_id']}/resume", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["job"]["job_id"], job["job_id"])
        self.assertTrue(response.json()["auto_started"])

    def test_dem_without_region_requests_clarification_without_creating_job(self) -> None:
        before = len(self.commercial.list_jobs(user_id=self.user_id, limit=100))

        response = self.client.post("/api/chat/ask", json={"prompt": "帮我下载 DEM", "user_id": self.user_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["reason"], "gscloud_intent_clarification")
        self.assertEqual(payload["action_required"]["type"], "clarification_required")
        self.assertIn("region", payload["action_required"]["missing_parameters"])
        self.assertEqual(len(self.commercial.list_jobs(user_id=self.user_id, limit=100)), before)

    def test_dem_with_region_returns_structured_login_required(self) -> None:
        response = self.client.post("/api/chat/ask", json={"prompt": "帮我下载成都 DEM", "user_id": self.user_id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action_required"]["type"], "login_required")
        self.assertEqual(payload["action_required"]["provider"], "gscloud")
        self.assertEqual(payload["job"]["status"], "waiting_login")
        self.assertNotIn("已启动下载", payload["reply"])
        assistant = payload["messages"][-1]
        self.assertEqual(assistant["meta"]["action_required"]["job_id"], payload["job"]["job_id"])

    def test_download_submit_defaults_paid_user_to_platform_but_allows_own(self) -> None:
        self.commercial.grant_plan(self.user_id, plan="pro")
        self.commercial.add_platform_account("gscloud", label="pool", daily_limit=10, monthly_limit=10)

        auto = self.client.post(
            "/api/downloads/submit",
            json={"user_id": self.user_id, "source_key": "gscloud", "resource_type": "dem", "region": "Chengdu"},
        )
        self.assertEqual(auto.status_code, 200)
        self.assertEqual(auto.json()["job"]["account_mode"], "platform")
        self.assertTrue(auto.json()["job"]["account_id"])

        own = self.client.post(
            "/api/downloads/submit",
            json={
                "user_id": self.user_id,
                "source_key": "gscloud",
                "resource_type": "dem",
                "region": "Chengdu",
                "account_mode": "own",
            },
        )
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()["job"]["account_mode"], "own")
        self.assertFalse(own.json()["job"]["account_id"])

    def test_legacy_dem_login_copy_points_to_existing_login_ui(self) -> None:
        source = inspect.getsource(api_server._submit_direct_gscloud_dem_from_chat)

        self.assertNotIn("前台后续", source)
        self.assertIn("设置 → 我的数据源账号", source)
        self.assertIn("继续下载", source)

    def test_completed_job_lists_public_registered_artifacts(self) -> None:
        job = self.commercial.submit_job(
            user_id=self.user_id,
            source_key="gscloud",
            resource_type="dem",
            region="成都",
            account_mode="own",
        )
        result_path = self.workdir / "downloads" / "chengdu_dem.tif"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_bytes(b"fake-tiff")
        self.commercial._update_job(
            job["job_id"],
            status="completed",
            stage="completed",
            progress=100,
            output_path=str(result_path),
        )

        response = self.client.get("/api/downloads/jobs", params={"user_id": self.user_id})

        self.assertEqual(response.status_code, 200)
        completed = next(item for item in response.json()["jobs"] if item["job_id"] == job["job_id"])
        self.assertEqual(len(completed["artifacts"]), 2)
        self.assertTrue(any(item["filename"].endswith(".tif") for item in completed["artifacts"]))
        self.assertTrue(any(item["filename"].endswith(".json") for item in completed["artifacts"]))
        self.assertTrue(all(item.get("download_url") for item in completed["artifacts"]))
        self.assertNotIn(str(self.workdir), json.dumps(completed["artifacts"]))

    def test_storage_state_is_never_exposed_as_download_artifact(self) -> None:
        job = self.commercial.submit_job(
            user_id=self.user_id,
            source_key="gscloud",
            resource_type="dem",
            region="成都",
            account_mode="own",
        )
        state_path = self.workdir / "domestic_auth" / "user_secret_storage_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text('{"cookies":[{"value":"secret"}]}', encoding="utf-8")
        self.commercial._update_job(job["job_id"], status="completed", output_path=str(state_path))

        response = self.client.get("/api/downloads/jobs", params={"user_id": self.user_id})

        completed = next(item for item in response.json()["jobs"] if item["job_id"] == job["job_id"])
        self.assertEqual([item["filename"] for item in completed["artifacts"]], ["metadata.json"])
        self.assertNotIn("secret", json.dumps(completed))

    def test_other_user_cannot_resume_job(self) -> None:
        job = self.commercial.submit_job(
            user_id=self.user_id,
            source_key="gscloud",
            resource_type="dem",
            region="成都",
            account_mode="own",
        )
        self.commercial._update_job(job["job_id"], status="waiting_login")
        other = TestClient(api_server.app)
        registered = other.post("/api/auth/register", json={"email": "other@example.com", "password": "secret123"})
        self.assertEqual(registered.status_code, 200)

        response = other.post(f"/api/download-jobs/{job['job_id']}/resume", json={})

        self.assertEqual(response.status_code, 403)

    def test_login_complete_rejects_path_traversal_session_id(self) -> None:
        response = self.client.post(
            "/api/data-sources/gscloud/login/complete",
            json={"login_session_id": "../storage_state"},
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
