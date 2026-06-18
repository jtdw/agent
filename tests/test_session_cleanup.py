from pathlib import Path
import tempfile
import unittest

from core.map_layers import MapLayerService
from core.service import GISWorkspaceService
from core.config import Settings


class SessionCleanupTests(unittest.TestCase):
    def test_delete_session_invalidates_artifacts_and_layers(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = GISWorkspaceService(Settings(workdir=Path(tmp)))
            session_id = service.create_new_session("cleanup")
            service.manager.set_runtime_scope(user_id="u_1", session_id=session_id)
            artifact_path = service.manager.derived_dir / "cleanup.txt"
            artifact_path.write_text("ok", encoding="utf-8")
            artifact = service.manager.register_artifact(path=str(artifact_path), type="file", title="cleanup")

            self.assertIsNotNone(service.manager.get_artifact(artifact["artifact_id"]))
            self.assertTrue(service.manager.derived_dir.exists())

            service.delete_session(session_id)

            self.assertIsNone(service.manager.get_artifact(artifact["artifact_id"]))
            layers = MapLayerService(service).workspace_layers(user_id="u_1", session_id=session_id)
            self.assertFalse(any(layer.get("artifact_id") == artifact["artifact_id"] for layer in layers["layers"]))


if __name__ == "__main__":
    unittest.main()
