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
            "ui_next/src/components/LayerPanel.tsx",
            "ui_next/src/components/ChatMessageRenderer.tsx",
            "ui_next/src/components/MapStage.tsx",
        ]
        clean_terms = [
            "\u4e0b\u8f7d",
            "\u83b7\u53d6",
            "\u51c6\u5907",
            "\u68c0\u7d22",
            "\u667a\u80fd",
            "\u7279\u5f81",
            "\u6b8b\u5dee",
            "\u6682\u672a\u8bc6\u522b\u5230\u8f93\u51fa\u6587\u4ef6",
        ]
        markers = sorted(
            {
                term.encode("utf-8").decode("gbk", errors="ignore")
                for term in clean_terms
                if term.encode("utf-8").decode("gbk", errors="ignore") != term
            }
            | {"\ufffd", "\ufffd".encode("utf-8").decode("gbk", errors="ignore")}
        )
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

    def test_rule_intent_classifier_recognizes_common_chinese_gis_processing_terms(self) -> None:
        from core.conversation_intent import classify_user_intent_rule_based

        prompts = [
            "\u8bf7\u88c1\u526a\u5f53\u524d\u56fe\u5c42",
            "\u63d0\u53d6\u6805\u683c\u503c",
            "\u7f13\u51b2\u533a\u5206\u6790",
            "\u91cd\u6295\u5f71\u5230 EPSG:4326",
            "\u7a7a\u95f4\u53e0\u52a0\u5206\u6790",
        ]

        for prompt in prompts:
            result = classify_user_intent_rule_based(prompt, {}, {"dataset_count": 1})
            self.assertEqual("data_processing", result["intent"], prompt)

    def test_task_planner_has_single_canonical_raster_prompt_helpers(self) -> None:
        text = (PROJECT_ROOT / "core/task_planner.py").read_text(encoding="utf-8")

        for name in (
            "_prompt_requests_dem_derivatives",
            "_prompt_requests_raster_reproject",
            "_prompt_requests_raster_algebra",
            "_target_crs_from_prompt",
            "_dem_derivatives_from_prompt",
        ):
            self.assertEqual(1, text.count(f"def {name}("), name)

    def test_key_runtime_files_do_not_contain_mojibake_markers(self) -> None:
        files = [
            "api_server.py",
            "core/conversation_intent.py",
            "core/task_planner.py",
            "core/admin_boundary.py",
            "core/data_manager.py",
            "core/map_layers.py",
        ]
        markers = [
            "\u6fb6",
            "\u7460",
            "\u93bb",
            "\u9359",
            "\u95c2",
            "\u74a7",
            "\u7f02",
            "\u95c1",
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
