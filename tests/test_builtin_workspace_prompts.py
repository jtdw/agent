from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.config import Settings
from core.service import GISWorkspaceService


class BuiltinWorkspacePromptTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def seed_table(self, service: GISWorkspaceService) -> None:
        service.manager.put_table(
            "soil_station",
            pd.DataFrame(
                {
                    "station_id": ["S1", "S2", "S3"],
                    "longitude": [115.1, 115.2, 115.3],
                    "latitude": [41.1, 41.2, 41.3],
                    "time": ["2024-01-01", "2024-01-02", "2024-01-03"],
                    "soil_moisture": [0.12, None, 0.18],
                }
            ),
        )

    def test_builtin_summary_prompt_returns_workspace_answer_without_model(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)

            result = service.ask("概括当前工作区数据，并判断哪些数据可直接用于制图、建模或结果分析。")

            self.assertEqual(result["model"], "builtin-workspace")
            self.assertIn("soil_station", result["reply"])
            self.assertIn("可直接用于制图", result["reply"])
            self.assertIn("可用于建模", result["reply"])

    def test_builtin_field_check_prompt_reports_columns_coordinates_time_and_missing_values(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)

            result = service.ask("检查当前上传数据的字段、坐标、时间和缺失值，给出下一步处理计划。")

            self.assertEqual(result["model"], "conversation-coordinator")
            self.assertEqual(result["mode"], "deterministic_tool")
            self.assertIn("字段", result["reply"])
            self.assertIn("longitude", result["reply"])
            self.assertIn("latitude", result["reply"])
            self.assertIn("time", result["reply"])
            self.assertIn("缺失值", result["reply"])
            self.assertIn("下一步", result["reply"])

    def test_builtin_download_readiness_prompt_reports_available_context(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)

            result = service.ask("根据当前工作区数据，检查是否可以下载 DEM、Sentinel-2 或土壤水分相关数据。")

            self.assertEqual(result["model"], "builtin-workspace")
            self.assertIn("下载准备", result["reply"])
            self.assertIn("soil_station", result["reply"])
            self.assertIn("下一步", result["reply"])

    def test_builtin_capability_prompt_is_non_model_answer(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))

            result = service.ask("你能做什么？")

            self.assertEqual(result["model"], "builtin-workspace")
            self.assertIn("数据检查", result["reply"])
            self.assertIn("制图", result["reply"])

    def test_builtin_capability_prompt_does_not_inspect_active_dataset(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            self.seed_table(service)

            result = service.ask("你能做什么？")

            self.assertEqual(result["model"], "builtin-workspace")
            self.assertEqual(result["mode"], "builtin_capability")
            self.assertIn("数据检查", result["reply"])
            self.assertIn("制图", result["reply"])
            self.assertNotIn("已完成操作", result["reply"])
            self.assertNotIn("使用的数据", result["reply"])
            self.assertNotIn("soil_station", result["reply"])
            self.assertNotIn("station_id", result["reply"])
            self.assertNotIn("soil_moisture", result["reply"])


if __name__ == "__main__":
    unittest.main()
