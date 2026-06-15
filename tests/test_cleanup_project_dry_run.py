from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "cleanup_project_dry_run.py"


class CleanupProjectDryRunTests(unittest.TestCase):
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("cleanup_project_dry_run", SCRIPT_PATH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_build_plan_preserves_unsure_items_and_redacts_sensitive_metadata(self) -> None:
        module = self._load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            destination = Path(temp_dir) / "archive"
            (root / "secrets").mkdir(parents=True)
            (root / "secrets" / "token.txt").write_text("do-not-print", encoding="utf-8")
            (root / "local_library").mkdir()

            plan = module.build_plan(root, destination)

        sensitive = next(item for item in plan if item.source == Path("secrets"))
        unsure = next(item for item in plan if item.source == Path("local_library"))
        self.assertEqual(sensitive.category, "C")
        self.assertTrue(sensitive.sensitive)
        self.assertNotIn("do-not-print", sensitive.reason)
        self.assertEqual(unsure.category, "D")
        self.assertFalse(unsure.move)

    def test_cli_is_read_only_and_prints_no_sensitive_content(self) -> None:
        secret = PROJECT_ROOT / "secrets" / "gscloud_platform_state.json"
        before = secret.stat() if secret.exists() else None

        completed = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("DRY RUN ONLY", completed.stdout)
        self.assertNotIn("do-not-print", completed.stdout)
        after = secret.stat() if secret.exists() else None
        self.assertEqual(before, after)

    def test_print_plan_expands_files_inside_movable_directories(self) -> None:
        module = self._load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            destination = Path(temp_dir) / "archive"
            (root / ".streamlit").mkdir(parents=True)
            (root / ".streamlit" / "config.toml").write_text("theme = 'light'", encoding="utf-8")
            output = io.StringIO()

            with redirect_stdout(output):
                result = module.print_plan(root, destination)

        self.assertEqual(result, 0)
        self.assertIn("move-file=.streamlit\\config.toml", output.getvalue())


if __name__ == "__main__":
    unittest.main()
