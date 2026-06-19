from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.api_helpers import relative_artifact_url
from core.data_manager import DataManager


class WorkspaceArtifactContractTests(unittest.TestCase):
    def test_anonymous_workspace_artifact_url_does_not_invent_user_id(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp) / "workspace"
            target = workdir / "exports" / "result.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("ok", encoding="utf-8")

            url = relative_artifact_url(workdir, str(target))
            query = parse_qs(urlparse(url).query)

            self.assertEqual(query.get("path"), ["exports/result.txt"])
            self.assertNotIn("user_id", query)

    def test_authenticated_workspace_artifact_url_uses_explicit_user_id(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp) / "workspace"
            target = workdir / "exports" / "result.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("ok", encoding="utf-8")

            url = relative_artifact_url(workdir, str(target), user_id="u_alice")
            query = parse_qs(urlparse(url).query)

            self.assertEqual(query.get("user_id"), ["u_alice"])
            self.assertEqual(query.get("path"), ["exports/result.txt"])

    def test_register_artifact_normalizes_project_relative_user_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            project_workspace = Path(tmp) / "workspace"
            manager = DataManager(project_workspace / "users" / "u_alice")
            manager.set_runtime_scope("u_alice", "session_a")
            target = manager.derived_dir / "xgb_sm_demo_metrics.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("metric,value\nR,0.9\n", encoding="utf-8")
            project_relative = target.relative_to(project_workspace)

            artifact = manager.register_artifact(
                artifact_id="artifact_metrics",
                path=str(Path(project_workspace.name) / project_relative),
                type="metrics",
            )

            self.assertEqual(Path(artifact["path"]).resolve(strict=False), target.resolve(strict=False))
            self.assertNotIn(
                "workspace/users/u_alice/workspace/users/u_alice",
                artifact["relative_path"].replace("\\", "/"),
            )

    def test_model_results_are_scoped_to_current_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace" / "users" / "u_alice")
            manager.set_runtime_scope("u_alice", "session_a")
            manager.register_model_result(
                model_result_id="model_xgb_session_a",
                model_name="XGBoost",
                output_prefix="xgb_a",
            )

            manager.set_runtime_scope("u_alice", "session_b")

            self.assertEqual(manager.list_model_results(), [])


if __name__ == "__main__":
    unittest.main()
