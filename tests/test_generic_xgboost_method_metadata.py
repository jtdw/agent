from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from core.data_manager import DataManager
from core.ml.generic_xgboost import run_generic_xgboost_workflow


def _training_frame(rows: int = 48) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2020-01-01", periods=rows, freq="D")
    ndvi = np.linspace(0.2, 0.85, rows)
    rain = rng.uniform(0.0, 30.0, rows)
    elevation = rng.normal(420.0, 15.0, rows)
    return pd.DataFrame(
        {
            "station_id": [f"S{i % 6}" for i in range(rows)],
            "date": dates.strftime("%Y-%m-%d"),
            "lon": np.linspace(100.0, 101.0, rows),
            "lat": np.linspace(30.0, 31.0, rows),
            "ndvi": ndvi,
            "rain_7d": rain,
            "elevation": elevation,
            "soil_moisture": 0.12 + ndvi * 0.08 + rain * 0.002 - elevation * 0.00005,
        }
    )


def test_generic_xgboost_outputs_gcp_ready_regression_contract() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp))
        manager.put_table("soil_training", _training_frame())

        result = run_generic_xgboost_workflow(
            manager,
            dataset_name="soil_training",
            target_col="soil_moisture",
            feature_cols="ndvi,rain_7d,elevation,lon,lat",
            output_name="soil_xgb",
            task_type="regression",
            split_method="auto",
            date_col="date",
            lon_col="lon",
            lat_col="lat",
        )

        assert result.ok, result.to_dict()
        outputs = result.outputs
        diagnostics = result.diagnostics
        result_df = manager.get_table(outputs["result_dataset"])

        assert outputs["target_column"] == "soil_moisture"
        assert outputs["prediction_column"] == "xgb_prediction"
        assert outputs["cv_prediction_column"] == "xgb_validation_prediction"
        assert outputs["residual_column"] == "xgb_residual"
        assert outputs["cv_fold_column"] == "xgb_validation_fold"
        assert outputs["validation_method"] == "spatiotemporal"
        assert outputs["coordinate_columns"] == {"lon": "lon", "lat": "lat"}
        assert outputs["time_column"] == "date"
        assert outputs["gcp_ready"] is True

        expected_columns = {
            "xgb_prediction",
            "xgb_residual",
            "xgb_validation_prediction",
            "xgb_validation_residual",
            "xgb_validation_fold",
            "xgb_validation_role",
        }
        assert expected_columns.issubset(result_df.columns)
        assert result_df["xgb_validation_prediction"].notna().any()
        assert result_df["xgb_validation_residual"].notna().any()
        assert set(result_df["xgb_validation_role"].dropna().unique()) == {"train", "test"}

        assert diagnostics["method_metadata"]["validation_method"] == "spatiotemporal"
        assert diagnostics["method_metadata"]["prediction_column"] == "xgb_prediction"
        assert diagnostics["method_metadata"]["cv_prediction_column"] == "xgb_validation_prediction"
        assert diagnostics["feature_semantics"]["target"] == "soil_moisture"
        assert diagnostics["feature_semantics"]["coordinate_features"] == ["lon", "lat"]


def test_generic_xgboost_reports_random_validation_limitation_without_space_or_time() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp))
        frame = _training_frame().drop(columns=["lon", "lat", "date", "station_id"])
        manager.put_table("soil_training", frame)

        result = run_generic_xgboost_workflow(
            manager,
            dataset_name="soil_training",
            target_col="soil_moisture",
            feature_cols="ndvi,rain_7d,elevation",
            output_name="soil_xgb_random",
            task_type="regression",
            split_method="auto",
        )

        assert result.ok, result.to_dict()
        assert result.outputs["validation_method"] == "random"
        assert result.outputs["gcp_ready"] is False
        assert "random_split_validation" in result.diagnostics["limitations"]
