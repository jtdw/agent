from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from domain.artifacts.policies import assert_artifact_path_allowed, safe_download_filename


class ArtifactDomainPolicyTests(unittest.TestCase):
    def test_sensitive_and_outside_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "workspace"
            root.mkdir()
            secret = root / "storage_state.json"
            secret.write_text("{}", encoding="utf-8")
            outside = Path(temp_dir) / "outside.tif"
            outside.write_bytes(b"data")

            with self.assertRaises(PermissionError):
                assert_artifact_path_allowed(root, secret)
            with self.assertRaises(PermissionError):
                assert_artifact_path_allowed(root, outside)

    def test_download_filename_removes_path_and_header_characters(self) -> None:
        self.assertEqual(safe_download_filename("../report\r\n.tif"), "report.tif")


if __name__ == "__main__":
    unittest.main()
