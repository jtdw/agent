from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService


class AuthIsolationTests(unittest.TestCase):
    def test_chat_sessions_creates_one_reusable_session_for_new_user(self) -> None:
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
                registered = client.post(
                    "/api/auth/register",
                    json={"email": "new-chat@example.com", "password": "password1"},
                )
                self.assertEqual(registered.status_code, 200)

                first = client.get("/api/chat/sessions")
                second = client.get("/api/chat/sessions")

                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 200)
                first_body = first.json()
                second_body = second.json()
                self.assertEqual(len(first_body["sessions"]), 1)
                self.assertEqual(len(second_body["sessions"]), 1)
                self.assertEqual(first_body["current_session_id"], second_body["current_session_id"])
                self.assertEqual(first_body["sessions"][0]["interaction_mode"], "chat_only")
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial

    def test_missing_user_id_requires_current_session_unless_anonymous_core_access_enabled(self) -> None:
        with (
            mock.patch.dict(os.environ, {"GIS_AGENT_ALLOW_ANONYMOUS": "0"}, clear=False),
            mock.patch.object(api_server, "_require_current_request_user", return_value="u_current") as require_current,
        ):
            self.assertEqual(api_server._require_request_user_if_present(object(), ""), "u_current")
            require_current.assert_called_once()

        with (
            mock.patch.dict(os.environ, {"GIS_AGENT_ALLOW_ANONYMOUS": "1"}, clear=False),
            mock.patch.object(api_server, "_require_current_request_user", return_value="u_current") as require_current,
        ):
            self.assertEqual(api_server._require_request_user_if_present(object(), ""), "")
            require_current.assert_not_called()

    def test_same_user_cannot_download_artifact_from_another_session(self) -> None:
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
                user_id = client.post("/api/auth/register", json={"email": "iso@example.com", "password": "password1"}).json()["user"]["user_id"]
                service = api_server.workspace_for(user_id)
                first = service.create_new_session("first")
                second = service.create_new_session("second")
                service.set_request_context(user_id, first)
                path = service.manager.derived_dir / "first.txt"
                path.write_text("first", encoding="utf-8")
                artifact = service.manager.register_artifact(path=str(path), type="file", title="first")

                ok = client.get(
                    f"/api/artifacts/{artifact['artifact_id']}/download",
                    params={"user_id": user_id, "session_id": first},
                )
                denied = client.get(
                    f"/api/artifacts/{artifact['artifact_id']}/download",
                    params={"user_id": user_id, "session_id": second},
                )

                self.assertEqual(ok.status_code, 200)
                self.assertIn(denied.status_code, {403, 404})
            finally:
                api_server._workspace_services.clear()
                api_server._workspace_services.update(original_services)
                api_server.base_settings.workdir = original_workdir
                api_server.commercial_service = original_commercial


if __name__ == "__main__":
    unittest.main()
