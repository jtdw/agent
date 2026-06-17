from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from domain.downloads.policies import is_active, is_retryable, is_terminal
from domain.downloads.status import DownloadJobStatus, normalize_status, storage_status
from infrastructure.storage.workspace_paths import WorkspacePaths, workspace_root_for_user


class CheckpointDomainInfrastructureTests(unittest.TestCase):
    def test_legacy_database_values_normalize_to_public_states(self) -> None:
        self.assertEqual(normalize_status("completed"), DownloadJobStatus.SUCCESS)
        self.assertEqual(normalize_status("canceled"), DownloadJobStatus.CANCELLED)
        self.assertEqual(storage_status(DownloadJobStatus.SUCCESS), "completed")
        self.assertEqual(storage_status(DownloadJobStatus.CANCELLED), "canceled")

    def test_waiting_states_are_active_and_retryable(self) -> None:
        for status in (DownloadJobStatus.WAITING_LOGIN, DownloadJobStatus.WAITING_PARAMETERS):
            self.assertTrue(is_active(status))
            self.assertTrue(is_retryable(status))
            self.assertNotEqual(status, DownloadJobStatus.RUNNING)

    def test_terminal_statuses_include_legacy_values(self) -> None:
        self.assertTrue(is_terminal("success"))
        self.assertTrue(is_terminal("completed"))
        self.assertTrue(is_terminal("failed"))
        self.assertTrue(is_terminal("cancelled"))

    def test_workspace_paths_create_expected_runtime_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = WorkspacePaths(Path(temp_dir) / "workspace").ensure()

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
