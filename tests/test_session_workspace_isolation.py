from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from core.commercial.service import CommercialService
from core.config import Settings
from core.service import GISWorkspaceService
from infrastructure.storage.workspace_paths import workspace_root_for_session, workspace_root_for_user


class SessionWorkspaceIsolationTests(unittest.TestCase):
    def test_session_workspace_paths_are_nested_under_user_workspace(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            base = Path(temp_dir) / "workspace"

            root = workspace_root_for_session(base, "u_1", "session_alpha")
            hostile = workspace_root_for_session(base, "u_1", "../../escape")

            self.assertEqual(root, base.resolve() / "users" / "u_1" / "sessions" / "session_alpha")
            hostile.relative_to(base.resolve() / "users" / "u_1" / "sessions")
            self.assertNotIn("..", hostile.parts)

    def test_session_services_do_not_share_uploaded_datasets(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            base = Path(temp_dir) / "workspace"
            user_root = workspace_root_for_user(base, "u_1")
            alpha_root = workspace_root_for_session(base, "u_1", "session_alpha")
            beta_root = workspace_root_for_session(base, "u_1", "session_beta")

            alpha = GISWorkspaceService(Settings(workdir=alpha_root))
            beta = GISWorkspaceService(Settings(workdir=beta_root))
            alpha.use_session_or_current("session_alpha")
            beta.use_session_or_current("session_beta")

            alpha.upload_bytes("points.csv", b"x,y\n1,2\n")

            self.assertIn("points", alpha.manager.list_dataset_names())
            self.assertNotIn("points", beta.manager.list_dataset_names())
            self.assertTrue((alpha_root / "uploads" / "points.csv").exists())
            self.assertFalse((beta_root / "uploads" / "points.csv").exists())
            self.assertFalse((user_root / "uploads" / "points.csv").exists())

    def test_download_jobs_can_be_filtered_by_chat_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            commercial = CommercialService(Path(temp_dir) / "workspace")
            commercial.register_user("user@example.com", "password1", user_id="u_1")

            alpha = commercial.submit_job(
                user_id="u_1",
                source_key="gscloud",
                resource_type="dem",
                chat_session_id="session_alpha",
            )
            beta = commercial.submit_job(
                user_id="u_1",
                source_key="gscloud",
                resource_type="dem",
                chat_session_id="session_beta",
            )

            alpha_jobs = commercial.list_jobs(user_id="u_1", chat_session_id="session_alpha")

            self.assertEqual([job["job_id"] for job in alpha_jobs], [alpha["job_id"]])
            self.assertEqual(commercial.get_job(beta["job_id"])["chat_session_id"], "session_beta")

    def test_artifact_api_cannot_cross_chat_sessions(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            old_workdir = api_server.base_settings.workdir
            api_server._workspace_services.clear()
            api_server.base_settings.workdir = Path(temp_dir) / "workspace"
            try:
                alpha = api_server.workspace_for("", "session_alpha")
                result_path = alpha.manager.derived_dir / "result.csv"
                result_path.write_text("a,b\n1,2\n", encoding="utf-8")
                alpha.manager.register_artifact(
                    artifact_id="artifact_session_alpha",
                    path=str(result_path),
                    type="csv",
                    title="result.csv",
                )
                client = TestClient(api_server.app)

                ok_response = client.get(
                    "/api/artifacts/artifact_session_alpha",
                    params={"session_id": "session_alpha"},
                )
                blocked_response = client.get(
                    "/api/artifacts/artifact_session_alpha/download",
                    params={"session_id": "session_beta"},
                )

                self.assertEqual(ok_response.status_code, 200)
                self.assertEqual(blocked_response.status_code, 404)
            finally:
                api_server._workspace_services.clear()
                api_server.base_settings.workdir = old_workdir


if __name__ == "__main__":
    unittest.main()
