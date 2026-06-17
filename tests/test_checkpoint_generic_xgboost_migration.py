from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.config import Settings
from core.gis_tools import build_tools
from core.service import GISWorkspaceService
from core.tool_contracts import parse_tool_result


class CheckpointGenericXGBoostMigrationTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_generic_xgboost_tool_is_registered(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            names = {tool.name for tool in build_tools(service.manager)}
            self.assertIn("generic_xgboost_workflow", names)

    def test_missing_target_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "samples",
                pd.DataFrame(
                    {
                        "x": [1, 2, 3, 4],
                        "y": [2, 3, 4, 5],
                    }
                ),
            )
            tool = {item.name: item for item in build_tools(service.manager)}["generic_xgboost_workflow"]
            result = parse_tool_result(tool.invoke({"dataset_name": "samples"}))

            self.assertIsNotNone(result)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "TARGET_REQUIRED")
            self.assertIn("target", result["diagnostics"]["required_inputs"])


if __name__ == "__main__":
    unittest.main()
