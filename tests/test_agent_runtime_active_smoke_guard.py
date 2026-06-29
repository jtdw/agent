from __future__ import annotations

from pathlib import Path


def test_active_smoke_guard_script_exists_and_keeps_llm_smoke_opt_in() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "test_agent_runtime_active_smoke.ps1"

    content = script.read_text(encoding="utf-8")

    assert "tests\\test_agent_runtime_active_smoke.py" in content
    assert "run_agent_runtime_active_smoke.ps1" in content
    assert "-CoordinatorMode deterministic" in content
    assert "-FailOnError" in content
    assert "GIS_AGENT_RUN_LLM_COORDINATOR_SMOKE" in content
    assert "active_describe_vector" in content
    assert "active_map_generation" in content
    assert "workflow_priority_table_to_points" in content
    assert "active_raster_clip_by_boundary" in content
    assert "active_vector_clip_map" in content
    assert "active_table_to_points_map" in content
    assert "Invoke-Checked" in content
    assert "$LASTEXITCODE" in content


def test_ci_runs_active_smoke_guard_without_llm_opt_in() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    ci_script = (repo_root / "scripts" / "test_ci_python.ps1").read_text(encoding="utf-8")

    assert ".\\scripts\\test_ci_python.ps1" in ci
    assert ".\\scripts\\test_agent_runtime_active_smoke.ps1" in ci_script
    assert "GIS_AGENT_RUN_LLM_COORDINATOR_SMOKE" not in ci
