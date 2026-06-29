from __future__ import annotations

import json
from pathlib import Path


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _phase49_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "ok": True,
            "admin_exposure": {
                "environment": "staging",
                "requested_percent": 10,
                "eligible_for_user_exposure": True,
                "recommendation": "allow_staging_exposure",
                "reasons": [],
            },
            "routing_sample": {"sample_count": 2000, "selected_percent": 9.45},
            "rollback": {"ready_switch": "GIS_AGENT_RUNTIME_ROLLBACK=1", "currently_requested": False},
        },
    )


def _phase50_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "ok": True,
            "cases": [
                {"label": "inside", "routing": {"use_active_runtime": True}},
                {"label": "outside", "routing": {"use_active_runtime": False}},
            ],
        },
    )


def _phase51_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "summary": {"case_count": 3, "passed": 3, "failed": 0, "ready_for_next_phase": True},
            "cases": [
                {
                    "case_id": "active_vector_clip_map",
                    "ok": True,
                    "status": "succeeded",
                    "executed_tools": ["vector_clip_by_vector", "plot_dataset"],
                    "safe_tool_execution": {"external_download_tools_executed": [], "artifact_count": 2, "image_count": 1},
                    "presentation_contract": {"status": "succeeded", "artifact_types": ["dataset", "map"]},
                },
                {
                    "case_id": "active_table_to_points_map",
                    "ok": True,
                    "status": "succeeded",
                    "executed_tools": ["table_to_points", "plot_dataset"],
                    "safe_tool_execution": {"external_download_tools_executed": [], "artifact_count": 2, "image_count": 1},
                    "presentation_contract": {"status": "succeeded", "artifact_types": ["dataset", "map"]},
                },
                {
                    "case_id": "xgboost_raster_prediction_map",
                    "ok": True,
                    "status": "succeeded",
                    "executed_tools": ["predict_xgboost_raster_map"],
                    "safe_tool_execution": {"external_download_tools_executed": [], "artifact_count": 3, "image_count": 2},
                    "presentation_contract": {
                        "status": "succeeded",
                        "artifact_types": ["raster", "png", "summary"],
                        "has_prediction_raster": True,
                        "has_summary_json": True,
                    },
                },
            ],
        },
    )


def test_build_observation_gate_summary_passes_with_clean_window(tmp_path: Path) -> None:
    from core.agent_runtime.staging_observation_gate import build_observation_gate_summary

    output = tmp_path / "phase52_summary.json"

    summary = build_observation_gate_summary(
        phase49_path=_phase49_fixture(tmp_path / "phase49.json"),
        phase50_path=_phase50_fixture(tmp_path / "phase50.json"),
        phase51_path=_phase51_fixture(tmp_path / "phase51.json"),
        output_path=output,
    )

    saved = json.loads(output.read_text(encoding="utf-8"))
    rendered = json.dumps(saved, ensure_ascii=False)
    assert summary["ok"] is True
    assert saved["schema_version"] == "phase52-staging10-observation-gate/v1"
    assert saved["checks"]["phase49_policy_and_routing_ok"] is True
    assert saved["checks"]["phase50_service_routing_ok"] is True
    assert saved["checks"]["phase51_quality_window_ok"] is True
    assert saved["checks"]["no_external_download_tools"] is True
    assert saved["task_window"]["summary"]["case_count"] == 3
    assert ":\\\\" not in rendered


def test_observation_gate_script_uses_pwsh_safe_case_array() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "run_agent_runtime_staging10_observation_gate.ps1"

    content = script.read_text(encoding="utf-8")

    assert "phase52_staging10_observation_gate.json" in content
    assert "capture_agent_runtime_diagnostics.ps1" in content
    assert "run_soil_moisture_gcp_smoke.ps1" in content
    assert "run_agent_runtime_active_smoke.ps1" in content
    assert "$ObservationCases" in content
    assert "-Case $ObservationCases" in content
    assert "core.agent_runtime.staging_observation_gate" in content
    assert 'GIS_AGENT_RUNTIME_V2 = "1"' in content
    assert 'GIS_AGENT_RUNTIME_MODE = "active"' in content
    assert 'GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER = "1"' in content
    assert 'GIS_AGENT_RUNTIME_EXPOSURE_ENV = "staging"' in content
    assert 'GIS_AGENT_RUNTIME_EXPOSURE_PERCENT = "10"' in content
