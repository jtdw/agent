from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXECUTE_SCRIPT = PROJECT_ROOT / "scripts" / "cleanup_project_migrate.py"
ROLLBACK_SCRIPT = PROJECT_ROOT / "scripts" / "cleanup_project_rollback.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CleanupProjectMigrationTests(unittest.TestCase):
    def test_execute_writes_manifest_moves_paths_and_preserves_unsure(self) -> None:
        migrate = load_module("cleanup_project_migrate", EXECUTE_SCRIPT)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            batch = Path(temp_dir) / "archive" / "batch"
            (root / ".streamlit").mkdir(parents=True)
            (root / ".streamlit" / "config.toml").write_text("legacy", encoding="utf-8")
            (root / "local_library").mkdir()
            (root / "local_library" / "keep.txt").write_text("keep", encoding="utf-8")
            (root / "requirements.txt").write_text("fastapi\nstreamlit>=1.55.0\n", encoding="utf-8")

            result = migrate.execute_migration(root, batch, only_sources={Path(".streamlit")})

            manifest_path = batch / "moved_files_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(result, manifest_path)
            self.assertFalse((root / ".streamlit").exists())
            self.assertTrue((batch / ".streamlit" / "config.toml").exists())
            self.assertTrue((root / "local_library" / "keep.txt").exists())
            self.assertNotIn("streamlit", (root / "requirements.txt").read_text(encoding="utf-8"))
            self.assertTrue((batch / "backups" / "requirements.txt").exists())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["entries"][0]["status"], "moved")

    def test_rollback_restores_moved_paths_and_requirements(self) -> None:
        migrate = load_module("cleanup_project_migrate_rollback_setup", EXECUTE_SCRIPT)
        rollback = load_module("cleanup_project_rollback", ROLLBACK_SCRIPT)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            batch = Path(temp_dir) / "archive" / "batch"
            (root / "web_app.py").parent.mkdir(parents=True)
            (root / "web_app.py").write_text("legacy", encoding="utf-8")
            original_requirements = "fastapi\nstreamlit>=1.55.0\n"
            (root / "requirements.txt").write_text(original_requirements, encoding="utf-8")
            manifest_path = migrate.execute_migration(root, batch, only_sources={Path("web_app.py")})

            rollback.rollback_migration(manifest_path)

            self.assertEqual((root / "web_app.py").read_text(encoding="utf-8"), "legacy")
            self.assertEqual((root / "requirements.txt").read_text(encoding="utf-8"), original_requirements)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "rolled_back")

    def test_cli_only_moves_selected_generated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            archive = Path(temp_dir) / "archive"
            (root / "artifacts").mkdir(parents=True)
            (root / "artifacts" / "report.txt").write_text("generated", encoding="utf-8")
            (root / ".superpowers").mkdir()
            (root / ".superpowers" / "state.txt").write_text("scratch", encoding="utf-8")
            (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(EXECUTE_SCRIPT),
                    "--project-root",
                    str(root),
                    "--archive-root",
                    str(archive),
                    "--timestamp",
                    "batch",
                    "--only",
                    "artifacts",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "artifacts").exists())
            self.assertTrue((archive / "project" / "batch" / "artifacts" / "report.txt").exists())
            self.assertTrue((root / ".superpowers" / "state.txt").exists())


if __name__ == "__main__":
    unittest.main()
