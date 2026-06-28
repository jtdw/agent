from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.conversation_intent import classify_user_intent
from core.gcp_uncertainty import run_gcp_uncertainty_analysis
from core.task_planner import build_task_plan


def _prediction_frame(rows: int = 40) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "y_true": [float(i) for i in range(rows)],
            "y_pred": [float(i) + (0.4 if i % 3 == 0 else -0.2) for i in range(rows)],
            "lon": [100.0 + (i % 10) * 0.05 for i in range(rows)],
            "lat": [30.0 + (i // 10) * 0.05 for i in range(rows)],
            "fold": [i % 5 for i in range(rows)],
            "cv_available": [True for _ in range(rows)],
        }
    )


class GCPUncertaintyCoreTests(unittest.TestCase):
    def test_standard_conformal_outputs_intervals_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            result = run_gcp_uncertainty_analysis(
                data=_prediction_frame(),
                observed_col="y_true",
                predicted_col="y_pred",
                output_name="gcp_demo",
                output_dir=Path(tmp),
                alpha=0.1,
                spatial_weighting=False,
            )

            predictions = result["predictions"]
            metrics = result["metrics"]
            self.assertTrue((predictions["prediction_interval_lower"] <= predictions["y_pred"]).all())
            self.assertTrue((predictions["prediction_interval_upper"] >= predictions["y_pred"]).all())
            self.assertTrue((predictions["interval_width"] > 0).all())
            self.assertGreaterEqual(metrics["empirical_coverage"], 0.0)
            self.assertLessEqual(metrics["empirical_coverage"], 1.0)
            self.assertEqual(metrics["target_coverage"], 0.9)
            self.assertIn("interval_score", metrics)

            image_names = {Path(item["path"]).name for item in result["images"]}
            self.assertIn("gcp_demo_gcp_prediction_intervals.png", image_names)
            self.assertIn("gcp_demo_gcp_coverage.png", image_names)
            self.assertIn("gcp_demo_gcp_interval_width_distribution.png", image_names)
            self.assertIn("gcp_demo_gcp_residual_vs_width.png", image_names)

    def test_spatial_weighting_changes_width_and_missing_coordinates_degrade(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            spatial = run_gcp_uncertainty_analysis(
                data=_prediction_frame(),
                observed_col="y_true",
                predicted_col="y_pred",
                output_name="gcp_spatial",
                output_dir=Path(tmp),
                lon_col="lon",
                lat_col="lat",
                alpha=0.1,
                spatial_weighting=True,
                spatial_bandwidth=0.05,
            )
            widths = spatial["predictions"]["interval_width"]
            self.assertGreater(widths.max() - widths.min(), 0.0)
            self.assertEqual(spatial["metrics"]["method"], "spatially_weighted_gcp")
            self.assertTrue(any(str(item["path"]).endswith("_gcp_interval_width_spatial.png") for item in spatial["images"]))

            no_coords = run_gcp_uncertainty_analysis(
                data=_prediction_frame().drop(columns=["lon", "lat"]),
                observed_col="y_true",
                predicted_col="y_pred",
                output_name="gcp_no_coords",
                output_dir=Path(tmp),
                lon_col="lon",
                lat_col="lat",
                alpha=0.1,
                spatial_weighting=True,
            )
            self.assertEqual(no_coords["metrics"]["method"], "global_split_conformal_fallback")
            self.assertTrue(no_coords["warnings"])

    def test_invalid_alpha_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with self.assertRaises(ValueError):
                run_gcp_uncertainty_analysis(
                    data=_prediction_frame(),
                    observed_col="y_true",
                    predicted_col="y_pred",
                    output_name="bad_alpha",
                    output_dir=Path(tmp),
                    alpha=1.5,
                )


class GCPSemanticRoutingTests(unittest.TestCase):
    def test_gcp_phrases_are_recognized_for_uncertainty_workflow(self) -> None:
        phrases = [
            "perform GCP uncertainty analysis",
            "generate conformal prediction interval and uncertainty map",
            "\u505a\u5730\u7406\u5171\u5f62\u9884\u6d4b",
            "\u751f\u6210\u9884\u6d4b\u533a\u95f4\u548c\u4e0d\u786e\u5b9a\u6027\u56fe",
        ]
        for phrase in phrases:
            intent = classify_user_intent(phrase, {"active_dataset": "xgb_out"}, {"dataset_count": 1}, enable_llm=False)
            self.assertEqual(intent["intent"], "modeling", phrase)
            plan = build_task_plan(phrase, intent, {"workspace": {"dataset_count": 1}, "recent_model_result": {}}, manager=None)
            self.assertTrue(plan["should_ask_clarification"] or "geographical_conformal_prediction" in plan["recommended_tools"], phrase)


if __name__ == "__main__":
    unittest.main()
