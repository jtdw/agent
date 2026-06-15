from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class ApiHelpersLightweightTests(unittest.TestCase):
    def test_api_helpers_import_does_not_load_agent(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import core.api_helpers; print('core.agent' in sys.modules)",
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(proc.stdout.strip(), "False")

    def test_relative_artifact_url_uses_artifact_id_only(self) -> None:
        from core.api_helpers import relative_artifact_url

        url = relative_artifact_url("artifact_result", user_id="u_alice")

        self.assertEqual(url, "/api/artifacts/artifact_result/download?user_id=u_alice")
        self.assertNotIn("path=", url)

    def test_workspace_mentions_are_compact(self) -> None:
        from core.api_helpers import build_workspace_mentions

        result = build_workspace_mentions(
            [
                {
                    "name": "demo_xgboost_soil_moisture",
                    "type": "table",
                    "path": "workspace/users/u_1/uploads/demo_xgboost_soil_moisture.csv",
                    "meta": {"rows": 48, "columns": ["station_id", "lon", "lat", "date"]},
                }
            ]
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "demo_xgboost_soil_moisture")
        self.assertEqual(result["items"][0]["mention"], "@{demo_xgboost_soil_moisture}")
        self.assertEqual(result["items"][0]["filename"], "demo_xgboost_soil_moisture.csv")
        self.assertEqual(result["items"][0]["row_count"], 48)
        self.assertEqual(result["items"][0]["column_count"], 4)
        serialized = str(result)
        self.assertNotIn("workspace/users", serialized)
        self.assertNotIn("uploads/demo_xgboost", serialized)


if __name__ == "__main__":
    unittest.main()
