from __future__ import annotations

import tempfile
import json
from pathlib import Path

import pandas as pd

from core.config import Settings
from core.data_manager import DataManager
from core.ml.generic_xgboost import _split_indices, run_generic_xgboost_workflow
from core.ml.modeling_advisor import build_zhipu_modeling_advice
from core.ml.modeling_profile import build_modeling_profile
from core.tools.ml_tools import build_ml_tools


def test_modeling_profile_is_desensitized_and_identifies_task_hints() -> None:
    df = pd.DataFrame(
        {
            "plot_id": ["a", "b", "c", "d"],
            "lon": [100.0, 100.1, 100.2, 100.3],
            "lat": [30.0, 30.1, 30.2, 30.3],
            "date": pd.date_range("2024-01-01", periods=4),
            "crop_yield": [10.0, 12.0, 11.0, 13.0],
            "ndvi": [0.3, 0.4, 0.35, 0.5],
            "soil_type": ["a", "b", "a", "b"],
        }
    )

    profile = build_modeling_profile(df, dataset_name="crop_table", data_type="table")

    assert profile["dataset_name"] == "crop_table"
    assert profile["sample_count"] == 4
    assert profile["contains_raw_rows"] is False
    assert "sample_rows" not in profile
    assert "path" not in profile
    assert profile["spatial"]["is_spatial"] is True
    assert profile["temporal"]["is_temporal"] is True
    assert profile["target_candidates"][0]["field"] == "crop_yield"
    assert "ndvi" in profile["feature_candidates"]


def test_auto_split_selects_spatiotemporal_when_date_and_coordinates_exist() -> None:
    df = pd.DataFrame(
        {
            "lon": [100 + i * 0.01 for i in range(30)],
            "lat": [30 + (i % 5) * 0.01 for i in range(30)],
            "date": pd.date_range("2024-01-01", periods=30),
        }
    )

    train, test, info = _split_indices(
        df,
        split_method="auto",
        test_size=0.2,
        random_state=7,
        lon_col="lon",
        lat_col="lat",
        date_col="date",
    )

    assert len(train) > 0
    assert len(test) > 0
    assert info["method"] == "spatiotemporal"
    assert info["date_col"] == "date"
    assert info["lon_col"] == "lon"
    assert info["lat_col"] == "lat"


def test_auto_split_selects_spatial_when_only_coordinates_exist() -> None:
    df = pd.DataFrame({"lon": [100 + i * 0.01 for i in range(30)], "lat": [30 + (i % 5) * 0.01 for i in range(30)]})

    train, test, info = _split_indices(
        df,
        split_method="auto",
        test_size=0.2,
        random_state=7,
        lon_col="lon",
        lat_col="lat",
    )

    assert len(train) > 0
    assert len(test) > 0
    assert info["method"] == "spatial"


def test_zhipu_modeling_advisor_sends_only_desensitized_profile() -> None:
    captured = {}

    class FakeClient:
        def invoke(self, messages):
            captured["messages"] = messages
            return '{"target_col":"crop_yield","feature_cols":["ndvi"],"task_type":"regression","split_method":"spatial"}'

    profile = {
        "dataset_name": "crop_table",
        "path": "E:/secret/workspace/uploads/crop.csv",
        "sample_rows": [{"lon": 100.1, "lat": 30.1, "crop_yield": 10.5}],
        "fields": [{"name": "crop_yield", "dtype": "float64"}, {"name": "ndvi", "dtype": "float64"}],
        "target_candidates": [{"field": "crop_yield"}],
        "feature_candidates": ["ndvi"],
        "spatial": {"is_spatial": True, "lon_col": "lon", "lat_col": "lat"},
    }

    advice = build_zhipu_modeling_advice(profile, client=FakeClient())

    payload_text = str(captured["messages"])
    assert advice["status"] == "ok"
    assert advice["advice"]["target_col"] == "crop_yield"
    assert "sample_rows" not in payload_text
    assert "E:/secret" not in payload_text
    assert "100.1" not in payload_text
    assert "30.1" not in payload_text


def test_settings_exposes_modeling_advisor_switch() -> None:
    settings = Settings(enable_modeling_advisor=True)

    assert settings.enable_modeling_advisor is True


def test_settings_reads_modeling_advisor_switch_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("GIS_AGENT_ENABLE_MODELING_ADVISOR", "1")

    settings = Settings()

    assert settings.enable_modeling_advisor is True


def test_crop_yield_fixture_runs_generic_xgboost_regression_workflow() -> None:
    fixture = Path("tests/fixtures/generic_xgboost/crop_yield_regression.csv")
    df = pd.read_csv(fixture, encoding="utf-8")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp))
        manager.put_table("crop_yield_regression", df)
        tool = {item.name: item for item in build_ml_tools(manager)}["generic_xgboost_workflow"]

        raw = tool.invoke(
            {
                "dataset_name": "crop_yield_regression",
                "target_col": "crop_yield",
                "feature_cols": "ndvi,rainfall,temperature,elevation,lon,lat",
                "output_name": "crop_yield_xgb_fixture",
                "task_type": "regression",
                "split_method": "auto",
                "lon_col": "lon",
                "lat_col": "lat",
                "date_col": "date",
                "auto_tune": True,
                "tuning_budget": "small",
                "enable_shap": True,
            }
        )

    result = json.loads(raw)
    assert result["status"] == "succeeded"
    assert result["outputs"]["model_type"] == "regression"
    assert result["diagnostics"]["split"]["method"] == "spatiotemporal"
    assert result["diagnostics"]["tuning"]["enabled"] is True
    assert result["diagnostics"]["shap"]["enabled"] is True


def test_forest_cover_fixture_runs_generic_xgboost_classification_workflow() -> None:
    fixture = Path("tests/fixtures/generic_xgboost/forest_cover_classification.csv")
    df = pd.read_csv(fixture, encoding="utf-8")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp))
        manager.put_table("forest_cover_classification", df)
        tool = {item.name: item for item in build_ml_tools(manager)}["generic_xgboost_workflow"]

        raw = tool.invoke(
            {
                "dataset_name": "forest_cover_classification",
                "target_col": "forest_cover",
                "feature_cols": "ndvi,elevation,slope,canopy_height,lon,lat",
                "output_name": "forest_cover_xgb_fixture",
                "task_type": "classification",
                "split_method": "auto",
                "lon_col": "lon",
                "lat_col": "lat",
                "date_col": "date",
            }
        )

    result = json.loads(raw)
    assert result["status"] == "succeeded"
    assert result["outputs"]["model_type"] == "classification"
    assert result["diagnostics"]["split"]["method"] == "spatiotemporal"
    assert "F1" in result["outputs"]["metrics"]


def test_generic_xgboost_records_enabled_modeling_advisor_status() -> None:
    class FakeAdvisorClient:
        def invoke(self, messages):
            return '{"target_col":"crop_yield","feature_cols":["ndvi","rainfall"],"task_type":"regression","split_method":"spatiotemporal"}'

    fixture = Path("tests/fixtures/generic_xgboost/crop_yield_regression.csv")
    df = pd.read_csv(fixture, encoding="utf-8")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        manager = DataManager(Path(tmp))
        manager.put_table("crop_yield_regression", df)

        result = run_generic_xgboost_workflow(
            manager,
            dataset_name="crop_yield_regression",
            target_col="crop_yield",
            feature_cols="ndvi,rainfall,temperature,elevation,lon,lat",
            output_name="crop_yield_xgb_advised",
            task_type="regression",
            lon_col="lon",
            lat_col="lat",
            date_col="date",
            enable_modeling_advisor=True,
            modeling_advisor_client=FakeAdvisorClient(),
        )

    assert result.ok
    assert result.diagnostics["modeling_advisor"]["status"] == "ok"
    assert result.diagnostics["modeling_advisor"]["advice"]["target_col"] == "crop_yield"
