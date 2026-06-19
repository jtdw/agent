from __future__ import annotations

import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.routes.data_sources import create_data_sources_router
from api.routes.downloads import create_downloads_router


class RouteModulesBehaviorTests(unittest.TestCase):
    def test_download_resume_route_uses_authenticated_user_service_and_audit(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeResumeService:
            def resume(self, user_id: str, job_id: str) -> dict:
                calls.append(("resume", (user_id, job_id)))
                return {"job": {"job_id": job_id, "user_id": user_id}, "auto_started": True}

        def authenticated_user(request: Request) -> str:
            calls.append(("auth", request.url.path))
            return "u_1"

        def audit(request: Request, **kwargs):
            calls.append(("audit", kwargs))

        app = FastAPI()
        app.include_router(
            create_downloads_router(
                resume_service=lambda: FakeResumeService(),
                authenticated_user=authenticated_user,
                audit=audit,
                guard=lambda fn: fn(),
            )
        )

        response = TestClient(app).post("/api/download-jobs/job_1/resume")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auto_started"], True)
        self.assertIn(("auth", "/api/download-jobs/job_1/resume"), calls)
        self.assertIn(("resume", ("u_1", "job_1")), calls)
        audit_call = next(item for name, item in calls if name == "audit")
        self.assertEqual(audit_call["user_id"], "u_1")
        self.assertEqual(audit_call["action"], "download.resume")
        self.assertEqual(audit_call["resource_id"], "job_1")
        self.assertEqual(audit_call["detail"], {"auto_started": True})

    def test_gscloud_account_routes_use_authenticated_user_service_and_audit(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeAccountService:
            def status(self, user_id: str) -> dict:
                calls.append(("status", user_id))
                return {"provider": "gscloud", "logged_in": True}

            def start_login(self, user_id: str, *, timeout_seconds: int) -> dict:
                calls.append(("start_login", (user_id, timeout_seconds)))
                return {"provider": "gscloud", "login_session_id": "login_1"}

            def complete_login(self, user_id: str, login_session_id: str) -> dict:
                calls.append(("complete_login", (user_id, login_session_id)))
                return {"provider": "gscloud", "logged_in": True, "login_session_id": login_session_id}

            def logout(self, user_id: str) -> dict:
                calls.append(("logout", user_id))
                return {"provider": "gscloud", "logged_in": False}

        def authenticated_user(request: Request) -> str:
            calls.append(("auth", request.url.path))
            return "u_1"

        def audit(request: Request, **kwargs):
            calls.append(("audit", kwargs))

        app = FastAPI()
        app.include_router(
            create_data_sources_router(
                account_service=lambda: FakeAccountService(),
                authenticated_user=authenticated_user,
                audit=audit,
                guard=lambda fn: fn(),
            )
        )
        client = TestClient(app)

        self.assertEqual(client.get("/api/data-sources/gscloud/status").json()["logged_in"], True)
        self.assertEqual(client.post("/api/data-sources/gscloud/login/start", json={"timeout_seconds": 120}).json()["login_session_id"], "login_1")
        self.assertEqual(client.post("/api/data-sources/gscloud/login/complete", json={"login_session_id": "login_1"}).json()["logged_in"], True)
        self.assertEqual(client.delete("/api/data-sources/gscloud/logout").json()["logged_in"], False)

        self.assertIn(("status", "u_1"), calls)
        self.assertIn(("start_login", ("u_1", 120)), calls)
        self.assertIn(("complete_login", ("u_1", "login_1")), calls)
        self.assertIn(("logout", "u_1"), calls)
        audit_actions = [payload["action"] for name, payload in calls if name == "audit"]
        self.assertEqual(
            audit_actions,
            ["data_source.login_start", "data_source.login_complete", "data_source.logout"],
        )


if __name__ == "__main__":
    unittest.main()
