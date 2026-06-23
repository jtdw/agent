from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.data_manager import DataManager


class WorkspaceArtifactContractTests(unittest.TestCase):
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
