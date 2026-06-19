from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.config import Settings
from core.data_manager import DataManager
from core.service import GISWorkspaceService
from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown


class UploadNamingAndPathTests(unittest.TestCase):
    def test_uploaded_csv_keeps_original_stem_as_dataset_name(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))

            messages = service.upload_bytes_batch(
                [
                    (
                        "demo_xgboost_soil_moisture.csv",
                        b"station_id,lon,lat,date,soil_moisture\nS1,100,30,2024-01-01,0.2\n",
                    )
                ]
            )

            self.assertEqual(service.manager.list_dataset_names(), ["demo_xgboost_soil_moisture"])
            self.assertTrue(messages)
            self.assertIn("demo_xgboost_soil_moisture", messages[0])
            stored = service.manager.get("demo_xgboost_soil_moisture")
            self.assertEqual(stored.meta.get("original_filename"), "demo_xgboost_soil_moisture.csv")

    def test_upload_outcome_is_brief_without_next_step_advice(self) -> None:
        dashboard = {"datasets": [{"name": "demo_xgboost_soil_moisture", "type": "table"}]}

        outcome = build_task_outcome("upload", {"ok": True, "count": 1, "messages": ["上传成功：demo_xgboost_soil_moisture.csv"]}, dashboard=dashboard)
        markdown = format_task_outcome_markdown(outcome)

        self.assertIn("上传成功", outcome["summary"])
        self.assertEqual(outcome["recommendations"], [])
        self.assertNotIn("推荐下一步", markdown)

    def test_register_artifact_normalizes_scoped_relative_paths_to_absolute(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace" / "users" / "u_test")
            manager.set_runtime_scope("u_test", "session_abc")
            path = manager.derived_dir / "xgb_sm_demo_xgb_metrics.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame([{"scope": "overall", "RMSE": 0.1}]).to_csv(path, index=False, encoding="utf-8")

            relative = "workspace/users/u_test/sessions/session_abc/derived/xgb_sm_demo_xgb_metrics.csv"
            artifact = manager.register_artifact(artifact_id="metrics_artifact", path=relative, type="metrics")

            self.assertEqual(Path(artifact["path"]).resolve(strict=False), path.resolve(strict=False))
            self.assertTrue(Path(artifact["path"]).exists())

    def test_register_artifact_normalizes_scoped_relative_paths_before_session_scope_is_set(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace" / "users" / "u_test")
            path = manager.workdir / "sessions" / "session_abc" / "derived" / "xgb_sm_demo_xgb_metrics.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame([{"scope": "overall", "RMSE": 0.1}]).to_csv(path, index=False, encoding="utf-8")

            relative = "workspace/users/u_test/sessions/session_abc/derived/xgb_sm_demo_xgb_metrics.csv"
            artifact = manager.register_artifact(artifact_id="metrics_artifact_no_scope", path=relative, type="metrics")

            self.assertEqual(Path(artifact["path"]).resolve(strict=False), path.resolve(strict=False))
            self.assertNotIn("workspace/users/u_test/workspace/users/u_test", artifact["path"].replace("\\", "/"))
            self.assertTrue(Path(artifact["path"]).exists())

    def test_existing_artifact_with_duplicated_workspace_prefix_is_repaired_when_listed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace" / "users" / "u_test")
            manager.set_runtime_scope("u_test", "session_abc")
            path = manager.derived_dir / "xgb_sm_demo_xgb_metrics.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame([{"scope": "overall", "RMSE": 0.1}]).to_csv(path, index=False, encoding="utf-8")
            bad_path = "workspace/users/u_test/workspace/users/u_test/sessions/session_abc/derived/xgb_sm_demo_xgb_metrics.csv"
            manager.database.upsert_artifact(
                {
                    "artifact_id": "bad_metrics_artifact",
                    "path": bad_path,
                    "type": "metrics",
                    "title": "xgb_sm_demo_xgb_metrics.csv",
                    "owner_user_id": "u_test",
                    "session_id": "session_abc",
                }
            )

            artifact = manager.list_registered_artifacts()[0]

            self.assertEqual(Path(artifact["path"]).resolve(strict=False), path.resolve(strict=False))
            self.assertTrue(Path(artifact["path"]).exists())


if __name__ == "__main__":
    unittest.main()
