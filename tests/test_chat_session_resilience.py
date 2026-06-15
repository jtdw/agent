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

    def test_missing_chat_session_falls_back_to_active_session(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            original = service.current_session_id

            recovered = service.use_session_or_current("session_missing")

            self.assertFalse(recovered)
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

    def test_model_selection_is_persisted_per_conversation_without_chat_message(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            service = self.make_service(root)
            first = service.current_session_id

            self.assertEqual(service.chat_model_state(first)["selected_model"], "auto")
            selected = service.select_chat_model("glm-4.7", first)
            self.assertEqual(selected["route_mode"], "manual")
            self.assertEqual(selected["selected_model"], "glm-4.7")
            self.assertEqual(service.current_messages(), [])

            second = service.create_new_session("第二个会话")
            self.assertEqual(service.chat_model_state(second)["selected_model"], "auto")
            self.assertEqual(service.chat_model_state(first)["selected_model"], "glm-4.7")

            restarted = self.make_service(root)
            self.assertEqual(restarted.chat_model_state(first)["selected_model"], "glm-4.7")

    def test_removed_manual_model_falls_back_to_auto(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            session_id = service.current_session_id
            state = service.manager.database.get_conversation_state(session_id)
            state.update({"model_route_mode": "manual", "selected_chat_model": "removed-model"})
            service.manager.database.set_conversation_state(session_id, state)

            normalized = service.chat_model_state(session_id)

            self.assertEqual(normalized["route_mode"], "auto")
            self.assertEqual(normalized["selected_model"], "auto")

    def test_workspace_database_migrates_mojibake_history_text(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            session_id = service.current_session_id
            broken = "特征重要性/\u9417\u7470\u7ddb\u95b2\u5d88\ue6e6\u93ac?\uff1a乱码"
            with service.manager.database._connect() as conn:
                conn.execute(
                    "INSERT INTO conversation_messages (session_id, role, content, meta_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (session_id, "assistant", broken, "{}", "2026-06-14 00:00:00"),
                )

            result = service.manager.database.migrate_mojibake_history()
            messages = service.current_messages()

            self.assertGreaterEqual(result["updated_messages"], 1)
            self.assertIn("特征重要性：乱码", messages[-1]["content"])
            self.assertNotIn("\u9417\u7470\u7ddb", messages[-1]["content"])
            self.assertTrue(result["backup_path"])


if __name__ == "__main__":
    unittest.main()
