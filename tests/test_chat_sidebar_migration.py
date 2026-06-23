from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api_server import _build_workspace_mentions
from core.chat_tasks import cancel_chat_task, start_chat_task
from core.config import Settings
from core.service import GISWorkspaceService


class ChatSidebarMigrationTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(
            api_key="test-key",
            workdir=root / "workspace",
            supported_models=("glm-4.5-air", "glm-4.7", "glm-4.6v"),
            model="glm-4.5-air",
        )
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_chat_model_selection_is_scoped_to_conversation_state(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            first = service.create_new_session("default")
            second = service.create_new_session("analysis")

            service.select_chat_model("glm-4.7", second)
            selected = service.chat_model_state(second)
            original = service.chat_model_state(first)

            self.assertEqual(selected["route_mode"], "manual")
            self.assertEqual(selected["selected_model"], "glm-4.7")
            self.assertEqual(original["selected_model"], "auto")
            self.assertIn({"id": "glm-4.6v", "capability": "vision"}, selected["models"])

    def test_workspace_mentions_expose_stable_at_tokens(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table("stations", pd.DataFrame({"lon": [1.0], "lat": [2.0], "value": [3.0]}))

            payload = _build_workspace_mentions(service.manager.list_datasets())

            self.assertEqual(payload["count"], 1)
            item = payload["items"][0]
            self.assertEqual(item["name"], "stations")
            self.assertEqual(item["mention"], "@{stations}")
            self.assertEqual(item["type"], "table")
            self.assertEqual(item["filename"], "stations.csv")

    def test_chat_cancel_task_reports_cancel_requested(self) -> None:
        start_chat_task("task_chat_sidebar", user_id="u_1", session_id="s_1")

        result = cancel_chat_task("task_chat_sidebar", user_id="u_1", reason="stop")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "cancel_requested")
        self.assertEqual(result["task_id"], "task_chat_sidebar")


if __name__ == "__main__":
    unittest.main()
