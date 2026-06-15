from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from infrastructure.storage.workspace_paths import WorkspacePaths, workspace_root_for_user


class WorkspacePathsTests(unittest.TestCase):
    def test_workspace_paths_create_only_expected_runtime_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = WorkspacePaths(Path(temp_dir) / "workspace")

            paths.ensure()

            self.assertTrue(paths.uploads.is_dir())
            self.assertTrue(paths.plots.is_dir())
            self.assertTrue(paths.derived.is_dir())
            self.assertTrue(paths.temp.is_dir())
            self.assertTrue(paths.exports.is_dir())
            self.assertEqual(paths.database, paths.root / "workspace.db")

    def test_user_workspace_cannot_escape_base_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "workspace"

            anonymous = workspace_root_for_user(base, None)
            hostile = workspace_root_for_user(base, "../../outside")

            self.assertEqual(anonymous, base.resolve() / "anonymous")
            hostile.relative_to(base.resolve() / "users")
            self.assertNotIn("..", hostile.parts)


if __name__ == "__main__":
    unittest.main()
