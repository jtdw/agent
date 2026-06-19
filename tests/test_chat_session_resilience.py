from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import Settings
from core.service import GISWorkspaceService


class ChatSessionResilienceTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="test-key", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_missing_chat_session_is_rejected_without_switching_current_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            original = service.current_session_id

            with self.assertRaises(FileNotFoundError):
                service.use_session_or_current("session_missing")

            self.assertEqual(service.current_session_id, original)
            self.assertIn(original, {item["session_id"] for item in service.list_sessions()})

    def test_existing_chat_session_is_selected(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            first = service.current_session_id
            second = service.create_new_session("第二个会话")

            recovered = service.use_session_or_current(first)

            self.assertTrue(recovered)
            self.assertNotEqual(first, second)
            self.assertEqual(service.current_session_id, first)

    def test_clear_current_chat_persists_after_service_restart(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            session_id = service.current_session_id
            service.manager.database.add_message(session_id, "user", "hello")
            service.manager.database.add_message(session_id, "assistant", "world")

            service.clear_current_chat()

            self.assertEqual(service.current_messages(), [])
            self.assertEqual(service.list_sessions()[0]["title"], "新对话")

            restarted = self.make_service(root)
            self.assertEqual(restarted.current_session_id, session_id)
            self.assertEqual(restarted.current_messages(), [])


if __name__ == "__main__":
    unittest.main()
