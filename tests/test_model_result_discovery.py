from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.config import Settings
from core.service import GISWorkspaceService


class ModelResultDiscoveryTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_dashboard_discovers_standalone_xgboost_outputs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            derived = service.manager.derived_dir
            pd.DataFrame([{"scope": "overall", "n": 48, "R": 0.91, "RMSE": 0.12, "NSE": 0.8}]).to_csv(
                derived / "soil_demo_xgb_metrics.csv",
                index=False,
            )
            pd.DataFrame([{"feature": "ndvi", "importance": 0.61}]).to_csv(
                derived / "soil_demo_xgb_importance.csv",
                index=False,
            )
            (derived / "soil_demo_xgb_summary.json").write_text(
                json.dumps({"dataset": "soil_demo", "target_col": "soil_moisture", "prediction_column": "soil_demo_xgb"}),
                encoding="utf-8",
            )
            (derived / "soil_demo_xgb_model.joblib").write_bytes(b"model")

            dashboard = service.dashboard()

            self.assertIn("model_results", dashboard)
            result = dashboard["model_results"][0]
            self.assertEqual(result["model"], "XGBoost")
            self.assertRegex(result["model_result_id"], r"^legacy_model_")
            self.assertEqual(result["metrics_dataset"], "soil_demo_xgb_metrics")
            self.assertEqual(result["importance_dataset"], "soil_demo_xgb_importance")
            self.assertAlmostEqual(result["metrics"]["RMSE"], 0.12)
            self.assertTrue(any("RMSE" in item for item in result["recommendations"]))

    def test_registered_model_result_takes_priority_over_legacy_discovery(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            metrics_path = service.manager.derived_dir / "soil_demo_xgb_metrics.csv"
            metrics_path.write_text("scope,R,RMSE,NSE\noverall,0.1,9,0.0\n", encoding="utf-8")
            service.manager.register_model_result(
                model_result_id="model_result_registered",
                task_id="task_registered",
                dataset_id="soil_points",
                model_name="XGBoost",
                output_prefix="soil_demo",
                result_dataset="soil_demo",
                metrics_dataset="soil_demo_xgb_metrics",
                metrics_path=str(metrics_path),
                metrics={"R": 0.9, "RMSE": 0.1, "NSE": 0.8},
            )

            results = service.discover_model_results()

            self.assertEqual(results[0]["model_result_id"], "model_result_registered")
            self.assertEqual(results[0]["metrics"]["RMSE"], 0.1)

    def test_dashboard_skips_stale_model_metric_artifact_instead_of_failing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            missing_path = service.manager.derived_dir / "stale_demo_xgb_metrics.csv"
            service.manager.register_artifact(
                artifact_id="stale_metrics",
                path=str(missing_path),
                type="metrics",
                title="stale_demo_xgb_metrics.csv",
            )

            dashboard = service.dashboard()

            self.assertIn("model_results", dashboard)
            self.assertFalse(any(result.get("metrics_dataset") == "stale_demo_xgb_metrics" for result in dashboard["model_results"]))


if __name__ == "__main__":
    unittest.main()
