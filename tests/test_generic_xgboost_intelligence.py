from __future__ import annotations

import tempfile
import json
import os
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from core.config import Settings
from core.conversation_intent import classify_user_intent
from core.data_manager import DataManager
from core.model_results import generate_model_result_id
from core.service import GISWorkspaceService
from core.task_planner import build_task_plan
from core.ml.generic_xgboost import _split_indices, run_generic_xgboost_workflow
from core.ml.modeling_advisor import build_zhipu_modeling_advice
from core.ml.modeling_profile import build_modeling_profile
from core.tool_contracts import tool_result_ok
from core.tools.ml_tools import build_ml_tools


FIXTURE_DIR = Path("tests/fixtures/generic_xgboost")


def _make_service(root: Path) -> GISWorkspaceService:
    settings = Settings(api_key="", workdir=root / "workspace")
    settings.ensure_dirs()
    service = GISWorkspaceService(settings)
    service.set_interaction_mode("tool_enabled")
    return service


def _active_rule_plan(service: GISWorkspaceService):
    def active_plan(prompt_text: str, context: dict, **kwargs):
        intent = context.get("intent")
        if not isinstance(intent, dict) or not intent:
            intent = classify_user_intent(prompt_text, {}, service.manager.workspace_summary(), enable_llm=False)
        plan = build_task_plan(prompt_text, intent, context, manager=service.manager)
        return {"status": "ready", "mode": "active", "planner_source": "test", "executes_tools": False, "plan": plan}

    return active_plan


def _fake_generic_xgboost_workflow(expected_model_type: str):
    def fake_run(manager: DataManager, **kwargs):
        dataset_name = str(kwargs.get("dataset_name") or "")
        target_col = str(kwargs.get("target_col") or "")
        output_name = str(kwargs.get("output_name") or "service_xgboost")
        model_result_id = generate_model_result_id("generic_xgboost", output_name)
        task_id = "generic_xgboost_workflow_test"
        diagnostics = {
            "model_type": expected_model_type,
            "split": {
                "method": "spatiotemporal",
                "date_col": str(kwargs.get("date_col") or ""),
                "lon_col": str(kwargs.get("lon_col") or ""),
                "lat_col": str(kwargs.get("lat_col") or ""),
            },
        }
        metrics = {"R2": 0.91, "RMSE": 0.12} if expected_model_type == "regression" else {"Accuracy": 0.9, "F1": 0.89}
        summary_path = manager.workdir / f"{output_name}_summary.json"
        summary_path.write_text(json.dumps({"metrics": metrics, "diagnostics": diagnostics}, ensure_ascii=False), encoding="utf-8")
        artifacts = [
            {
                "path": str(summary_path),
                "type": "summary",
                "title": f"{output_name}_summary.json",
                "source_tool": "generic_xgboost_workflow",
            }
        ]
        registered = manager.register_model_result(
            model_result_id=model_result_id,
            task_id=task_id,
            dataset_id=dataset_name,
            model_name="generic_xgboost",
            output_prefix=output_name,
            result_dataset=f"{output_name}_predictions",
            artifacts=artifacts,
            metrics=metrics,
            diagnostics=diagnostics,
        )
        return tool_result_ok(
            "generic_xgboost_workflow",
            task_id=task_id,
            inputs=dict(kwargs),
            outputs={
                "model_result_id": registered["model_result_id"],
                "model_type": expected_model_type,
                "result_dataset": f"{output_name}_predictions",
                "metrics": metrics,
            },
            artifacts=artifacts,
            summary=f"Generic XGBoost {expected_model_type} test workflow completed for {target_col}.",
            diagnostics=diagnostics,
        )

    return fake_run


def _fake_presentation_bundle(**kwargs):
    raw_results = kwargs.get("raw_results") if isinstance(kwargs.get("raw_results"), dict) else {}
    workflow_result = raw_results.get("workflow_result") if isinstance(raw_results.get("workflow_result"), dict) else {}
    steps = workflow_result.get("steps") if isinstance(workflow_result.get("steps"), list) else []
    tool_result = {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        candidate = step.get("tool_result") if isinstance(step.get("tool_result"), dict) else {}
        if candidate.get("tool_name") == "generic_xgboost_workflow":
            tool_result = candidate
            break
    if not tool_result:
        first_step = steps[0] if steps and isinstance(steps[0], dict) else {}
        tool_result = first_step.get("tool_result") if isinstance(first_step.get("tool_result"), dict) else {}
    outputs = tool_result.get("outputs") if isinstance(tool_result.get("outputs"), dict) else {}
    metrics = outputs.get("metrics") if isinstance(outputs.get("metrics"), dict) else {}
    model_result_id = str(outputs.get("model_result_id") or "")
    result_dataset = str(outputs.get("result_dataset") or "")
    metric_text = ", ".join(f"{key}={value}" for key, value in metrics.items())
    reply = f"Completed generic XGBoost workflow. {metric_text} result_dataset={result_dataset} model_result_id={model_result_id}"
    return {
        "schema_version": "presentation-bundle/v1",
        "normalized_results": [tool_result] if tool_result else [],
        "presentation_result": {
            "status": "succeeded",
            "concise_summary": reply,
            "key_results": [{"label": key, "value": value} for key, value in metrics.items()],
        },
        "execution_summary": {"status": "succeeded", "key_results": metrics},
        "reply": reply,
        "presentation_source": "test",
        "result_rendering_path": "presentation_result",
    }


def _run_service_xgboost_dialog(fixture_name: str, prompt: str, expected_model_type: str) -> dict:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = _make_service(Path(tmp))
        fixture_path = FIXTURE_DIR / fixture_name
        upload_message = service.upload_bytes(fixture_name, fixture_path.read_bytes())
        assert "上传成功" in upload_message or "涓婁紶鎴愬姛" in upload_message

        env = {**os.environ, "GIS_AGENT_ENABLE_MODELING_ADVISOR": "0"}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("core.service.build_llm_task_plan", side_effect=_active_rule_plan(service)):
                with mock.patch("core.service.run_coordinated_execution", return_value={"executed": False, "blocked_reason": "NO_EXECUTABLE_STEPS"}):
                    with mock.patch("core.service.build_presentation_bundle_from_raw_execution", side_effect=_fake_presentation_bundle):
                        with mock.patch("core.ml.generic_xgboost.run_generic_xgboost_workflow", side_effect=_fake_generic_xgboost_workflow(expected_model_type)):
                            response = service.ask(prompt)

        dashboard = service.dashboard()
        assert response["mode"] == "validated_workflow_executor"
        assert response.get("artifacts")
        assert "model_result_generic_xgboost" in response["reply"]
        assert dashboard["model_results"]
        model_result = dashboard["model_results"][0]
        diagnostics = model_result.get("diagnostics") or (model_result.get("summary") or {}).get("diagnostics") or {}
        assert diagnostics["model_type"] == expected_model_type
        return response


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


@pytest.mark.slow
def test_service_upload_then_dialog_runs_crop_yield_xgboost_workflow() -> None:
    response = _run_service_xgboost_dialog(
        "crop_yield_regression.csv",
        (
            "Use generic XGBoost regression on current data. "
            "target_col=crop_yield feature_cols=ndvi,rainfall,temperature,elevation,lon,lat "
            "date_col=date output_name=service_crop_yield_xgb"
        ),
        "regression",
    )

    assert "service_crop_yield_xgb" in response["reply"]


@pytest.mark.slow
def test_service_upload_then_dialog_runs_forest_cover_xgboost_workflow() -> None:
    response = _run_service_xgboost_dialog(
        "forest_cover_classification.csv",
        (
            "Use generic XGBoost classification on current data. "
            "target_col=forest_cover feature_cols=ndvi,elevation,slope,canopy_height,lon,lat "
            "date_col=date output_name=service_forest_cover_xgb"
        ),
        "classification",
    )

    assert "service_forest_cover_xgb" in response["reply"]


@pytest.mark.slow
def test_service_upload_then_dialog_runs_soil_moisture_xgboost_workflow() -> None:
    response = _run_service_xgboost_dialog(
        "soil_moisture_regression.csv",
        (
            "Use generic XGBoost regression on current data. "
            "target_col=soil_moisture feature_cols=elevation,slope,precip_7d,ndvi,lst,lon,lat "
            "date_col=date output_name=service_soil_moisture_xgb"
        ),
        "regression",
    )

    assert "service_soil_moisture_xgb" in response["reply"]
