from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.chat_response import build_chat_response
from core.config import Settings
from core.response_postprocess import dedupe_assistant_reply, repair_mojibake_text
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


    def test_response_postprocess_dedupes_result_sections(self) -> None:
        raw = "\n".join(
            [
                "\u5df2\u5b8c\u6210\u64cd\u4f5c\uff1a",
                "- \u5df2\u751f\u6210 DEM \u62fc\u63a5\u7ed3\u679c",
                "\u8f93\u51fa\u6587\u4ef6\uff1a",
                "- derived/county_dem.tif",
                "\u8f93\u51fa\u6587\u4ef6\uff1a",
                "- derived/county_dem.tif",
                "\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a",
                "- \u53ef\u4ee5\u76f4\u63a5\u52a0\u8f7d\u5230\u5730\u56fe\u68c0\u67e5",
                "\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a",
                "- \u53ef\u4ee5\u76f4\u63a5\u52a0\u8f7d\u5230\u5730\u56fe\u68c0\u67e5",
            ]
        )

        cleaned = dedupe_assistant_reply(raw)

        self.assertEqual(cleaned.count("\u8f93\u51fa\u6587\u4ef6\uff1a"), 1)
        self.assertEqual(cleaned.count("\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a"), 1)
        self.assertEqual(cleaned.count("derived/county_dem.tif"), 1)

    def test_build_chat_response_returns_and_persists_cleaned_reply(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            raw_reply = "\u5df2\u5b8c\u6210\u64cd\u4f5c\uff1a\n- A\n\u8f93\u51fa\u6587\u4ef6\uff1a\n- out.tif\n\u8f93\u51fa\u6587\u4ef6\uff1a\n- out.tif"

            response = build_chat_response(
                service,
                user_prompt="\u751f\u6210\u7ed3\u679c",
                result={"reply": raw_reply, "model": "direct-router", "reason": "download_complete"},
                meta_keys=("model", "reason"),
            )

            self.assertEqual(response["reply"].count("\u8f93\u51fa\u6587\u4ef6\uff1a"), 1)
            self.assertEqual(response["reply"].count("out.tif"), 1)
            self.assertEqual(response["messages"][1]["content"], response["reply"])

    def test_workspace_database_cleans_updated_assistant_messages(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            session_id = service._ensure_session()
            message_id = service.manager.database.add_message(session_id, "assistant", "\u8f93\u51fa\u6587\u4ef6\uff1a\n- a.tif\n\u8f93\u51fa\u6587\u4ef6\uff1a\n- a.tif")

            service.manager.database.update_message(message_id, "\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a\n- \u68c0\u67e5\u5730\u56fe\n\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a\n- \u68c0\u67e5\u5730\u56fe")
            messages = service.manager.database.list_messages(session_id)

            self.assertEqual(messages[0]["content"].count("\u4e0b\u4e00\u6b65\u5efa\u8bae\uff1a"), 1)
            self.assertEqual(messages[0]["content"].count("\u68c0\u67e5\u5730\u56fe"), 1)
            self.assertEqual(repair_mojibake_text("\u6b63\u5e38\u6587\u672c"), "\u6b63\u5e38\u6587\u672c")


if __name__ == "__main__":
    unittest.main()
