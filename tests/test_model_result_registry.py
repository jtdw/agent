from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import Settings
from core.service import GISWorkspaceService


class ModelResultRegistryTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_register_model_result_round_trips_to_dashboard(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            metrics_path = service.manager.derived_dir / "xgb_metrics.csv"
            figure_path = service.manager.plot_dir / "xgb_residual_map.png"
            metrics_path.write_text("scope,R,RMSE,NSE\noverall,0.8,0.12,0.7\n", encoding="utf-8")
            figure_path.write_text("png", encoding="utf-8")

            registered = service.manager.register_model_result(
                model_result_id="model_result_xgb_001",
                task_id="task_xgb_001",
                dataset_id="soil_points",
                model_name="XGBoost",
                output_prefix="soil_xgb",
                result_dataset="soil_xgb",
                metrics_dataset="soil_xgb_metrics",
                metrics_path=str(metrics_path),
                figure_path=str(figure_path),
                artifact_ids=["metrics_1", "map_1"],
                artifacts=[{"artifact_id": "metrics_1", "path": str(metrics_path), "type": "metrics"}],
                metrics={"R": 0.8, "RMSE": 0.12, "NSE": 0.7},
                diagnostics={"target_col": "sm"},
            )

            self.assertEqual(registered["model_result_id"], "model_result_xgb_001")
            fetched = service.manager.get_model_result("model_result_xgb_001")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched["task_id"], "task_xgb_001")
            self.assertEqual(fetched["dataset_id"], "soil_points")
            self.assertEqual(fetched["metrics_path"], str(metrics_path))

            result = service.dashboard()["model_results"][0]
            self.assertEqual(result["model_result_id"], "model_result_xgb_001")
            self.assertEqual(result["task_id"], "task_xgb_001")
            self.assertEqual(result["metrics"]["RMSE"], 0.12)
            self.assertEqual(result["artifacts"][0]["artifact_id"], "metrics_1")

            artifact = service.manager.get_artifact("metrics_1")
            self.assertIsNotNone(artifact)
            self.assertEqual(artifact["model_result_id"], "model_result_xgb_001")

    def test_register_model_result_applies_version_contract_to_result_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.set_runtime_scope("u_model", "s_model")
            metrics_path = service.manager.derived_dir / "versioned_metrics.csv"
            metrics_path.write_text("scope,RMSE\noverall,0.12\n", encoding="utf-8")

            registered = service.manager.register_model_result(
                model_result_id="model_result_versioned",
                task_id="task_versioned",
                dataset_id="dataset_versioned",
                model_name="XGBoost",
                output_prefix="versioned",
                artifacts=[
                    {
                        "artifact_id": "artifact_versioned_metrics",
                        "path": str(metrics_path),
                        "type": "metrics",
                    }
                ],
            )

            self.assertEqual(registered["schema_version"], "model-result/v1")
            self.assertEqual(registered["artifact_version"], "model-artifact/v1")
            self.assertEqual(registered["owner_user_id"], "u_model")
            self.assertEqual(registered["session_id"], "s_model")

            fetched = service.manager.get_model_result("model_result_versioned")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched["schema_version"], "model-result/v1")
            self.assertEqual(fetched["artifact_version"], "model-artifact/v1")
            self.assertEqual(fetched["artifacts"][0]["meta"]["schema_version"], "model-artifact/v1")
            self.assertEqual(fetched["artifacts"][0]["meta"]["model_result_schema_version"], "model-result/v1")
            self.assertEqual(fetched["artifacts"][0]["meta"]["model_result_id"], "model_result_versioned")

    def test_artifact_registry_merges_with_legacy_file_scan(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            registered_path = service.manager.derived_dir / "registered_metrics.csv"
            legacy_path = service.manager.derived_dir / "legacy_plot.txt"
            registered_path.write_text("a,b\n1,2\n", encoding="utf-8")
            legacy_path.write_text("legacy", encoding="utf-8")

            service.manager.register_artifact(
                artifact_id="artifact_registered",
                path=str(registered_path),
                type="metrics",
                title="Registered metrics",
                model_result_id="model_result_1",
            )

            artifacts = service.manager.list_artifacts()
            ids = {item.get("artifact_id") for item in artifacts}
            paths = [item.get("path") for item in artifacts]
            self.assertIn("artifact_registered", ids)
            self.assertIn(str(legacy_path), paths)
            self.assertEqual(paths.count(str(registered_path)), 1)


if __name__ == "__main__":
    unittest.main()
