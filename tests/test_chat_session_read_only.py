from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import Settings
from core.service import GISWorkspaceService


class ChatSessionReadOnlyTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="test-key", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_service_startup_does_not_create_conversation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            self.assertEqual(service.current_session_id, "")
            self.assertEqual(service.list_sessions(), [])
            self.assertEqual(service.current_messages(), [])

    def test_read_only_request_context_does_not_create_conversation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            for _ in range(4):
                service.set_request_context("u_new_user", "")
                self.assertEqual(service.list_sessions(), [])
                self.assertEqual(service.current_messages(), [])

    def test_explicit_create_session_creates_one_conversation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            session_id = service.create_new_session()

            self.assertTrue(session_id.startswith("session_"))
            self.assertEqual(service.current_session_id, session_id)
            self.assertEqual(len(service.list_sessions()), 1)


if __name__ == "__main__":
    unittest.main()
