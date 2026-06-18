from pathlib import Path
import tempfile
import unittest

from core.data_manager import DataManager


class ArtifactAccessTests(unittest.TestCase):
    def test_artifact_access_requires_current_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope(user_id="u_1", session_id="s_1")
            artifact_path = manager.derived_dir / "result.txt"
            artifact_path.write_text("ok", encoding="utf-8")
            artifact = manager.register_artifact(
                path=str(artifact_path),
                type="file",
                title="result",
                source_tool="test",
            )

            self.assertTrue(manager.assert_artifact_access("u_1", "s_1", artifact["artifact_id"]))
            with self.assertRaises(PermissionError):
                manager.assert_artifact_access("u_1", "s_2", artifact["artifact_id"])


if __name__ == "__main__":
    unittest.main()
