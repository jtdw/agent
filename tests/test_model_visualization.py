from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.model_visualization import generate_model_visualizations


class ModelVisualizationTests(unittest.TestCase):
    def test_generates_base_xgboost_figures(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            output_dir = Path(tmp)
            result = generate_model_visualizations(
                y_true=pd.Series([1.0, 2.0, 3.0, 4.0]),
                y_pred=pd.Series([1.1, 1.9, 3.2, 3.8]),
                residuals=pd.Series([-0.1, 0.1, -0.2, 0.2]),
                feature_importance=pd.DataFrame(
                    {
                        "feature": ["elevation", "ndvi", "lst"],
                        "importance": [0.5, 0.35, 0.15],
                    }
                ),
                metrics={"r2": 0.95, "rmse": 0.2, "mae": 0.15},
                output_name="xgb_sm_demo",
                output_dir=output_dir,
            )

            names = {item["name"] for item in result["images"]}
            self.assertIn("feature_importance", names)
            self.assertIn("pred_vs_actual", names)
            self.assertIn("residual_distribution", names)
            self.assertNotIn("residual_spatial", names)

            for item in result["images"]:
                path = Path(item["path"])
                self.assertTrue(path.exists(), item)
                self.assertGreater(path.stat().st_size, 0, item)
                self.assertEqual(item["mime_type"], "image/png")

            skipped_names = {item["name"] for item in result["skipped_images"]}
            self.assertIn("residual_spatial", skipped_names)
            self.assertIn("prediction_spatial", skipped_names)

    def test_generates_spatial_figures_when_coordinates_exist(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            output_dir = Path(tmp)
            result = generate_model_visualizations(
                y_true=pd.Series([1.0, 2.0, 3.0, 4.0]),
                y_pred=pd.Series([1.1, 1.9, 3.2, 3.8]),
                residuals=pd.Series([-0.1, 0.1, -0.2, 0.2]),
                feature_importance=pd.DataFrame(
                    {
                        "feature": ["elevation", "ndvi", "lst"],
                        "importance": [0.5, 0.35, 0.15],
                    }
                ),
                metrics={"r2": 0.95, "rmse": 0.2, "mae": 0.15},
                output_name="xgb_sm_demo",
                output_dir=output_dir,
                lon=pd.Series([100.0, 100.1, 100.2, 100.3]),
                lat=pd.Series([30.0, 30.1, 30.2, 30.3]),
            )

            names = {item["name"] for item in result["images"]}
            self.assertIn("residual_spatial", names)
            self.assertIn("prediction_spatial", names)
            self.assertEqual(result["skipped_images"], [])

            for image_name in ["residual_spatial", "prediction_spatial"]:
                item = next(item for item in result["images"] if item["name"] == image_name)
                path = Path(item["path"])
                self.assertTrue(path.exists(), item)
                self.assertGreater(path.stat().st_size, 0, item)


if __name__ == "__main__":
    unittest.main()
