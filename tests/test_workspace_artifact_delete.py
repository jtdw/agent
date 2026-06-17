from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.data_manager import DataManager


class WorkspaceArtifactDeleteTests(unittest.TestCase):
    def test_delete_scanned_result_file_removes_physical_file_and_dashboard_artifact(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            path = manager.derived_dir / "result.txt"
            path.write_text("result", encoding="utf-8")
            self.assertTrue(any(item["path"] == str(path) for item in manager.list_artifacts()))

            result = manager.delete_result_file(path=str(path))

            self.assertTrue(result["ok"])
            self.assertFalse(path.exists())
            self.assertFalse(any(item["path"] == str(path) for item in manager.list_artifacts()))

    def test_delete_registered_artifact_also_removes_dataset_catalog_for_same_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            dataset_name = manager.put_text_document("report_doc", "report", filename="report.txt")
            path = manager.get(dataset_name).path
            artifact = manager.register_artifact(artifact_id="artifact_report", path=str(path), type="document")

            result = manager.delete_result_file(artifact_id=artifact["artifact_id"])

            self.assertTrue(result["ok"])
            self.assertFalse(path.exists())
            self.assertNotIn(dataset_name, manager.list_dataset_names())
            self.assertIsNone(manager.database.dataset_info(dataset_name))
            self.assertIsNone(manager.database.get_artifact("artifact_report"))

    def test_delete_result_file_rejects_paths_outside_results_folders(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            path = manager.upload_dir / "source.txt"
            path.write_text("source", encoding="utf-8")

            with self.assertRaises(PermissionError):
                manager.delete_result_file(path=str(path))

            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
