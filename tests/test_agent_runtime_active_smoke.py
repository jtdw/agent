from __future__ import annotations

import json
from pathlib import Path


def test_service_active_smoke_runs_guarded_active_fallback_with_synthetic_vectors(tmp_path, monkeypatch) -> None:
    from core.agent_runtime.active_smoke import run_service_active_smoke

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")
    monkeypatch.setenv("GIS_COORDINATOR_MAX_STEPS", "4")

    def planner_error(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {
            "status": "error",
            "mode": "shadow",
            "planner_source": "test_schema_drift",
            "reason": "force deterministic fallback",
        }

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", planner_error)

    output_path = tmp_path / "active_smoke.json"
    report = run_service_active_smoke(
        output_path=output_path,
        workspace_dir=tmp_path / "workspace",
        coordinator_mode="deterministic",
        case_ids=["active_map_generation"],
    )

    assert output_path.exists()
    persisted = json.loads(output_path.read_text(encoding="utf-8"))
    assert persisted["summary"]["case_count"] == 1
    assert persisted["summary"]["failed"] == 0
    assert report["summary"] == persisted["summary"]

    case = persisted["cases"][0]
    assert case["case_id"] == "active_map_generation"
    assert case["ok"] is True
    assert case["mode"] in {"coordinated_workflow", "validated_workflow_executor"}
    assert "plot_dataset" in case["executed_tools"]
    assert case["llm_planner"]["planner_source"].startswith("runtime_active:deterministic_fallback")
    assert case["safe_tool_execution"]["external_download_tools_executed"] == []


def test_service_active_smoke_cli_writes_report(tmp_path, monkeypatch) -> None:
    from core.agent_runtime.active_smoke import run_active_smoke_cli

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")

    def planner_error(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {"status": "error", "planner_source": "test_error", "reason": "force fallback"}

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", planner_error)

    output_path = tmp_path / "cli_smoke.json"
    exit_code = run_active_smoke_cli(
        [
            "service",
            "--output",
            str(output_path),
            "--workspace",
            str(tmp_path / "workspace"),
            "--coordinator-mode",
            "deterministic",
            "--case",
            "active_map_generation",
        ]
    )

    assert exit_code == 0
    payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    assert payload["summary"]["case_count"] == 1
    assert payload["summary"]["failed"] == 0


def test_service_active_smoke_ignores_percentage_exposure_routing(tmp_path, monkeypatch) -> None:
    from core.agent_runtime.active_smoke import run_service_active_smoke

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_ENV", "staging")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_PERCENT", "0")

    def planner_error(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {"status": "error", "planner_source": "test_error", "reason": "force fallback"}

    def legacy_plan_should_not_run(prompt, context):
        return {"status": "invalid_response", "planner_source": "legacy_route_miss"}

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", planner_error)
    monkeypatch.setattr("core.service.build_llm_task_plan", legacy_plan_should_not_run)

    report = run_service_active_smoke(
        output_path=tmp_path / "active_smoke.json",
        workspace_dir=tmp_path / "workspace",
        coordinator_mode="deterministic",
        case_ids=["active_map_generation"],
    )

    case = report["cases"][0]
    assert case["ok"] is True
    assert case["llm_planner"]["planner_source"].startswith("runtime_active:deterministic_fallback")


def test_service_active_smoke_default_suite_includes_describe_dataset_case(tmp_path, monkeypatch) -> None:
    from core.agent_runtime.active_smoke import run_service_active_smoke

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")

    def planner_error(prompt, context, deterministic_plan, *, client=None, enabled=None):
        return {"status": "error", "planner_source": "test_error", "reason": "force fallback"}

    monkeypatch.setattr("core.agent_runtime.planner.build_shadow_llm_task_plan", planner_error)

    output_path = tmp_path / "default_suite.json"
    report = run_service_active_smoke(
        output_path=output_path,
        workspace_dir=tmp_path / "workspace",
        coordinator_mode="deterministic",
    )

    cases = {case["case_id"]: case for case in report["cases"]}
    assert report["summary"]["case_count"] == 9
    assert report["summary"]["failed"] == 0
    assert "active_describe_vector" in cases
    assert "active_describe_table" in cases
    assert "active_map_generation_secondary_vector" in cases
    assert "active_raster_basic_stats" in cases
    assert "active_raster_clip_by_boundary" in cases
    assert "active_vector_clip_map" in cases
    assert "active_table_to_points_map" in cases
    assert "describe_dataset" in cases["active_describe_vector"]["executed_tools"]
    assert "describe_dataset" in cases["active_describe_table"]["executed_tools"]
    assert "plot_dataset" in cases["active_map_generation_secondary_vector"]["executed_tools"]
    assert "raster_basic_stats" in cases["active_raster_basic_stats"]["executed_tools"]
    assert "clip_raster_by_vector" in cases["active_raster_clip_by_boundary"]["executed_tools"]
    assert "vector_clip_by_vector" in cases["active_vector_clip_map"]["executed_tools"]
    assert "plot_dataset" in cases["active_vector_clip_map"]["executed_tools"]
    assert "table_to_points" in cases["active_table_to_points_map"]["executed_tools"]
    assert "plot_dataset" in cases["active_table_to_points_map"]["executed_tools"]
    assert cases["active_describe_vector"]["llm_planner"]["planner_source"].startswith("runtime_active:deterministic_fallback")
    assert cases["active_describe_vector"]["safe_tool_execution"]["external_download_tools_executed"] == []


def test_service_active_smoke_repeated_runs_use_fresh_case_workspace(tmp_path, monkeypatch) -> None:
    from core.agent_runtime.active_smoke import run_service_active_smoke

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")

    workspace = tmp_path / "workspace"
    run_service_active_smoke(
        output_path=tmp_path / "first.json",
        workspace_dir=workspace,
        coordinator_mode="deterministic",
        case_ids=["workflow_priority_table_to_points"],
    )
    second = run_service_active_smoke(
        output_path=tmp_path / "second.json",
        workspace_dir=workspace,
        coordinator_mode="deterministic",
        case_ids=["workflow_priority_table_to_points"],
    )

    case = second["cases"][0]
    assert second["summary"]["failed"] == 0
    assert case["ok"] is True
    assert case["status"] == "succeeded"
    assert case["safe_tool_execution"]["artifact_count"] == 1


def test_service_active_smoke_can_run_opt_in_semantic_gcp_result_map_case(tmp_path, monkeypatch) -> None:
    from core.agent_runtime.active_smoke import run_service_active_smoke

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")

    report = run_service_active_smoke(
        output_path=tmp_path / "semantic_gcp_result_map.json",
        workspace_dir=tmp_path / "workspace",
        coordinator_mode="deterministic",
        case_ids=["semantic_gcp_result_uncertainty_map"],
    )

    case = report["cases"][0]
    assert report["summary"]["case_count"] == 1
    assert report["summary"]["failed"] == 0
    assert case["ok"] is True
    assert "table_to_points" in case["executed_tools"]
    assert "plot_dataset" in case["executed_tools"]
    assert "generic_xgboost_workflow" not in case["executed_tools"]


def test_service_active_smoke_can_run_opt_in_xgboost_raster_prediction_case(tmp_path, monkeypatch) -> None:
    from core.agent_runtime.active_smoke import run_service_active_smoke

    monkeypatch.setenv("GIS_AGENT_RUNTIME_V2", "1")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_MODE", "active")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER", "1")

    report = run_service_active_smoke(
        output_path=tmp_path / "xgboost_raster_prediction.json",
        workspace_dir=tmp_path / "workspace",
        coordinator_mode="deterministic",
        case_ids=["xgboost_raster_prediction_map"],
    )

    case = report["cases"][0]
    assert report["summary"]["case_count"] == 1
    assert report["summary"]["failed"] == 0
    assert case["ok"] is True
    assert "predict_xgboost_raster_map" in case["executed_tools"]
    assert "generic_xgboost_workflow" not in case["executed_tools"]
    assert "train_xgboost_fusion_model" not in case["executed_tools"]
    assert case["safe_tool_execution"]["artifact_count"] >= 3
    presentation = case["presentation_contract"]
    assert presentation["status"] == "succeeded"
    assert presentation["artifact_types"] == ["raster", "png", "summary"]
    assert presentation["map_layer_count"] == 1
    assert presentation["image_ref_count"] == 1
    assert presentation["has_prediction_raster"] is True
    assert presentation["has_summary_json"] is True
    assert "representative_date=2019-07-15" in presentation["result_highlights"]
    assert "valid_prediction_pixels=" in " ".join(presentation["result_highlights"])
    assert "[internal_path]" not in str(presentation)
    assert ":\\\\" not in str(presentation)
    assert case["safe_tool_execution"]["external_download_tools_executed"] == []
