from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.data_manager import DataManager
from domain.artifacts.policies import content_disposition_attachment


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ChineseEncodingTests(unittest.TestCase):
    def test_text_source_files_decode_as_utf8(self) -> None:
        suffixes = {".py", ".ts", ".tsx", ".js", ".json", ".md", ".ps1", ".bat", ".html"}
        ignored_parts = {
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".venv",
            "node_modules",
            "dist",
            "build",
            "workspace",
        }
        bad_files: list[str] = []
        for path in PROJECT_ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part in ignored_parts for part in path.parts):
                continue
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                bad_files.append(str(path.relative_to(PROJECT_ROOT)))

        self.assertEqual([], bad_files)

    def test_key_user_facing_files_do_not_contain_high_confidence_mojibake(self) -> None:
        files = [
            "api_server.py",
            "core/data_manager.py",
            "core/agent.py",
            "core/tools/map_tools.py",
            "core/tools/table_tools.py",
            "core/conversation_intent.py",
            "core/result_interpreter.py",
            "ui_next/index.html",
            "ui_next/src/lib/api.ts",
        ]
        markers = ["涓嬭浇", "鑾峰彇", "鍑嗗", "妫€绱", "鏅鸿兘", "鐗瑰緛", "娈嬪樊", "暂未识别到输出文件", "锟斤拷", "�"]
        hits: list[str] = []
        for rel in files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            for marker in markers:
                if marker in text:
                    hits.append(f"{rel}: {marker}")

        self.assertEqual([], hits)

    def test_semantic_routing_files_do_not_depend_on_mojibake_keywords(self) -> None:
        files = [
            "core/conversation_intent.py",
            "core/task_planner.py",
            "core/object_resolver.py",
            "core/followup_resolver.py",
            "core/domestic_sources/intent_router.py",
            "core/tools/map_tools.py",
            "core/tools/raster_tools.py",
            "core/tools/vector_tools.py",
        ]
        markers = [
            "\u7441\u4f78\u58c0",
            "\u9359\u72b2\u59de",
            "\u93bb\u612c\u5f47",
            "\u9352\u8dfa\u6d58",
            "\u9422\u8bf2\u6d58",
            "\u7459\uff49\u5674",
            "\u5be4\u70d8\u0101",
            "\u6769\u6b0e\u91dc",
            "\u9366\u677f\u6d58",
            "\u6fca\u8fa9\u89e6",
            "\u6d93\u5b29\u7af4\u59dd",
            "\u7f01\u64b4\u7049",
            "\u93b8\u56e8\u7223",
            "\u6a48",
            "\u68f0\u52ec\u7974",
            "\u5a13\u546e\u7902",
            "\u9429\u9550\u6c26",
            "\u9365\u53e5\u6b22",
            "\u9422\u7193\u6d5c\u9366\u677f\u6d58",
            "\u93cd\u545f\u725c\u7441\u4f78\u58c0",
            "\u942d\uffa4\u567a\u7441\u4f78\u58c0",
            "\u942d\uffa4\u567a\u9359\u72b2\u59de",
            "\ue160",
            "\ue18c",
        ]
        hits: list[str] = []
        for rel in files:
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            for marker in markers:
                if marker in text:
                    hits.append(f"{rel}: {marker.encode('unicode_escape').decode('ascii')}")

        self.assertEqual([], hits)

    def test_data_manager_csv_roundtrip_preserves_chinese_headers_values_and_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="资阳路径_", ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            df = pd.DataFrame([{"站点": "雁江", "高程": 350.5}])

            saved_name = manager.put_table("资阳市站点.csv", df)
            saved = manager.get(saved_name)
            roundtrip = pd.read_csv(saved.path, encoding="utf-8-sig")

            self.assertEqual(["站点", "高程"], list(roundtrip.columns))
            self.assertEqual("雁江", roundtrip.loc[0, "站点"])
            self.assertIn("资阳市站点", saved.path.name)

    def test_uploaded_chinese_csv_filename_uses_safe_storage_and_loads_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="资阳上传_", ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            uploaded = manager.save_uploaded_bytes(
                "资阳站点.csv",
                "站点,经度,纬度\n雁江,104.65,30.12\n".encode("utf-8-sig"),
            )

            self.assertIn("资阳站点", uploaded.name)
            self.assertNotEqual("资阳站点.csv", uploaded.name)

            dataset_name = manager.load_path(str(uploaded))
            table = manager.get_table(dataset_name)
            self.assertEqual(["站点", "经度", "纬度"], list(table.columns))
            self.assertEqual("雁江", table.loc[0, "站点"])

    def test_chinese_artifact_download_filename_uses_rfc5987_filename_star(self) -> None:
        header = content_disposition_attachment("资阳市90米DEM结果.csv")

        self.assertIn("attachment;", header)
        self.assertIn("filename=", header)
        self.assertIn("filename*=UTF-8''", header)
        self.assertIn("%E8%B5%84%E9%98%B3%E5%B8%8290%E7%B1%B3DEM%E7%BB%93%E6%9E%9C.csv", header)

    def test_powershell_entrypoints_set_utf8_console_and_python_env(self) -> None:
        for rel in ("start_backend_api.ps1", "start_web_ui.ps1", "scripts/doctor.ps1"):
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("[Console]::InputEncoding", text, rel)
            self.assertIn("[Console]::OutputEncoding", text, rel)
            self.assertIn("$OutputEncoding", text, rel)
            self.assertIn("PYTHONUTF8", text, rel)
            self.assertIn("PYTHONIOENCODING", text, rel)

    def test_python_child_process_launches_force_utf8_environment(self) -> None:
        for rel in (
            "core/commercial/capture_jobs.py",
            "core/commercial/login_jobs.py",
            "core/commercial/scene_jobs.py",
            "core/commercial/tile_jobs.py",
        ):
            text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn('env.setdefault("PYTHONUTF8", "1")', text, rel)
            self.assertIn('env.setdefault("PYTHONIOENCODING", "utf-8")', text, rel)


if __name__ == "__main__":
    unittest.main()
