from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.chat_response import build_chat_response
from core.config import Settings
from core.service import GISWorkspaceService


class ChatResponseContractTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_build_chat_response_persists_exchange_and_returns_authoritative_state(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            response = build_chat_response(
                service,
                user_prompt="检查下载任务状态",
                result={"reply": "没有正在运行的下载任务。", "model": "direct-router", "reason": "download_status", "job": {"job_id": "job_1"}},
                meta_keys=("model", "reason", "job"),
            )

            self.assertEqual(response["reply"], "没有正在运行的下载任务。")
            self.assertEqual(response["model"], "direct-router")
            self.assertEqual(response["reason"], "download_status")
            self.assertEqual(response["current_session_id"], service.current_session_id)
            self.assertGreaterEqual(len(response["sessions"]), 1)
            self.assertEqual([item["role"] for item in response["messages"]], ["user", "assistant"])
            self.assertEqual(response["messages"][0]["content"], "检查下载任务状态")
            self.assertEqual(response["messages"][1]["content"], "没有正在运行的下载任务。")
            self.assertEqual(response["messages"][1]["meta"]["job"]["job_id"], "job_1")

    def test_build_chat_response_does_not_swallow_persistence_errors(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.database.add_message = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down"))  # type: ignore[method-assign]

            with self.assertRaises(RuntimeError):
                build_chat_response(
                    service,
                    user_prompt="检查下载任务状态",
                    result={"reply": "ok", "model": "direct-router"},
                    meta_keys=("model",),
                )

    def test_download_requires_login_reply_is_regular_chat_result(self) -> None:
        from core.api_helpers import _download_requires_login_result

        result = _download_requires_login_result("下载成都市 DEM")

        self.assertEqual(result["model"], "direct-router")
        self.assertEqual(result["reason"], "download_requires_login")
        self.assertIn("登录", result["reply"])
        self.assertIn("DEM", result["reply"])


if __name__ == "__main__":
    unittest.main()
