from __future__ import annotations

import json
from pathlib import Path


def test_exposure_policy_blocks_user_exposure_when_rollback_is_requested(tmp_path: Path) -> None:
    from core.agent_runtime.exposure import AgentRuntimeExposurePolicy

    report_path = tmp_path / "active_smoke.json"
    report_path.write_text(
        json.dumps({"summary": {"passed": 3, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )
    policy = AgentRuntimeExposurePolicy(
        environment="staging",
        requested_percent=5,
        rollback_requested=True,
        deterministic_smoke_report=report_path,
    )

    report = policy.evaluate({"active_effective": True})

    assert report["eligible_for_user_exposure"] is False
    assert "rollback_requested" in report["reasons"]
    assert report["deterministic_smoke"]["status"] == "passed"
    assert str(tmp_path) not in str(report)


def test_exposure_policy_allows_small_staging_exposure_after_smoke_passes(tmp_path: Path) -> None:
    from core.agent_runtime.exposure import AgentRuntimeExposurePolicy

    report_path = tmp_path / "active_smoke.json"
    report_path.write_text(
        json.dumps({"summary": {"case_count": 3, "passed": 3, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )
    policy = AgentRuntimeExposurePolicy(
        environment="staging",
        requested_percent=10,
        rollback_requested=False,
        deterministic_smoke_report=report_path,
    )

    report = policy.evaluate({"active_effective": True})

    assert report["eligible_for_user_exposure"] is True
    assert report["recommendation"] == "allow_staging_exposure"
    assert report["deterministic_smoke"]["report_filename"] == "active_smoke.json"
    assert report["checked_at"]
    assert "deterministic_smoke" in report["required_reports"]
    assert "Continue staging rollout" in " ".join(report["next_actions"])


def test_exposure_policy_requires_explicit_production_override(tmp_path: Path) -> None:
    from core.agent_runtime.exposure import AgentRuntimeExposurePolicy

    report_path = tmp_path / "active_smoke.json"
    report_path.write_text(
        json.dumps({"summary": {"passed": 3, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )
    policy = AgentRuntimeExposurePolicy(
        environment="production",
        requested_percent=1,
        rollback_requested=False,
        deterministic_smoke_report=report_path,
        allow_production_exposure=False,
    )

    report = policy.evaluate({"active_effective": True})

    assert report["eligible_for_user_exposure"] is False
    assert "production_exposure_requires_override" in report["reasons"]


def test_runtime_diagnostics_include_exposure_policy_report(monkeypatch) -> None:
    from core.agent_runtime.config import AgentRuntimeConfig
    from core.agent_runtime.context import AgentRuntimeContext
    from core.agent_runtime.runtime import GISAgentRuntime

    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_ENV", "local")
    monkeypatch.setenv("GIS_AGENT_RUNTIME_EXPOSURE_PERCENT", "0")
    monkeypatch.delenv("GIS_AGENT_RUNTIME_SMOKE_REPORT", raising=False)

    runtime = GISAgentRuntime.from_legacy_agent(
        model=object(),
        tools=[],
        system_prompt="system",
        legacy_agent=object(),
        context=AgentRuntimeContext(current_user_id="u_1", current_session_id="s_1", workspace_dir=Path("workspace")),
        config=AgentRuntimeConfig(enabled=True, mode="active", active_requested=True, active_cutover_allowed=True),
    )

    diagnostics = runtime.diagnostics()

    assert diagnostics["exposure_policy"]["schema_version"] == "agent-runtime-exposure-policy/v1"
    assert diagnostics["exposure_policy"]["eligible_for_user_exposure"] is False
    assert diagnostics["exposure_policy"]["blocking_reasons_human"]


def test_staging_exposure_dry_run_writes_sanitized_evidence(tmp_path: Path) -> None:
    from core.agent_runtime.exposure import run_staging_exposure_dry_run

    report_path = tmp_path / "active_smoke.json"
    output_path = tmp_path / "evidence.json"
    report_path.write_text(
        json.dumps({"summary": {"case_count": 3, "passed": 3, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )

    evidence = run_staging_exposure_dry_run(
        output_path=output_path,
        environment="staging",
        percent=1,
        smoke_report=report_path,
        cutover_guard={"active_effective": True},
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    rendered = json.dumps(saved, ensure_ascii=False)
    assert evidence["schema_version"] == "agent-runtime-staging-exposure-dry-run/v1"
    assert saved["exposure"]["environment"] == "staging"
    assert saved["exposure"]["requested_percent"] == 1
    assert saved["exposure"]["eligible_for_user_exposure"] is True
    assert saved["operations"] == {
        "llm_calls_performed": 0,
        "tool_calls_performed": 0,
        "live_traffic_changed": False,
    }
    assert str(report_path) not in rendered
    assert str(tmp_path) not in rendered


def test_staging_exposure_dry_run_requires_soil_moisture_gcp_gate_when_requested(tmp_path: Path) -> None:
    from core.agent_runtime.exposure import run_staging_exposure_dry_run

    report_path = tmp_path / "active_smoke.json"
    output_path = tmp_path / "evidence.json"
    missing_soil_summary = tmp_path / "missing_soil_summary.json"
    report_path.write_text(
        json.dumps({"summary": {"case_count": 3, "passed": 3, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )

    evidence = run_staging_exposure_dry_run(
        output_path=output_path,
        environment="staging",
        percent=10,
        smoke_report=report_path,
        cutover_guard={"active_effective": True},
        require_soil_moisture_gcp_smoke=True,
        soil_moisture_gcp_summary=missing_soil_summary,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    rendered = json.dumps(saved, ensure_ascii=False)
    assert evidence["exposure"]["eligible_for_user_exposure"] is False
    assert "soil_moisture_gcp_smoke_not_passed" in evidence["exposure"]["reasons"]
    assert saved["exposure"]["soil_moisture_gcp_smoke"]["status"] == "missing_report"
    assert saved["exposure"]["soil_moisture_gcp_smoke"]["report_filename"] == "missing_soil_summary.json"
    assert str(missing_soil_summary) not in rendered


def test_staging_exposure_dry_run_cli_writes_output(tmp_path: Path) -> None:
    from core.agent_runtime.exposure import run_exposure_cli

    report_path = tmp_path / "active_smoke.json"
    output_path = tmp_path / "evidence.json"
    report_path.write_text(
        json.dumps({"summary": {"passed": 3, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )

    code, payload = run_exposure_cli(
        [
            "staging-dry-run",
            "--output",
            str(output_path),
            "--environment",
            "staging",
            "--percent",
            "1",
            "--smoke-report",
            str(report_path),
            "--active-effective",
        ]
    )

    assert code == 0
    assert payload["output_filename"] == "evidence.json"
    assert output_path.exists()


def test_staging_exposure_dry_run_cli_accepts_passing_soil_moisture_gcp_summary(tmp_path: Path) -> None:
    from core.agent_runtime.exposure import run_exposure_cli

    report_path = tmp_path / "active_smoke.json"
    soil_summary_path = tmp_path / "soil_summary.json"
    output_path = tmp_path / "evidence.json"
    report_path.write_text(
        json.dumps({"summary": {"passed": 3, "failed": 0, "ready_for_next_phase": True}}),
        encoding="utf-8",
    )
    soil_summary_path.write_text(
        json.dumps(
            {
                "overall_ok": True,
                "cases": [
                    {
                        "case_id": "summer_20190715",
                        "ok": True,
                        "workflow_status": "modeled",
                        "study_area_filter": {"filter_method": "study_area_boundary"},
                        "prediction": {"status": "mapped", "valid_pixels": 742, "tif_exists": True, "png_exists": True},
                        "gcp": {"empirical_coverage": 0.8919, "report_exists": True},
                    },
                    {
                        "case_id": "spring_20190515",
                        "ok": True,
                        "workflow_status": "modeled",
                        "study_area_filter": {"filter_method": "study_area_boundary"},
                        "prediction": {"status": "mapped", "valid_pixels": 742, "tif_exists": True, "png_exists": True},
                        "gcp": {"empirical_coverage": 0.8919, "report_exists": True},
                    },
                    {
                        "case_id": "early_window_20190115",
                        "ok": True,
                        "workflow_status": "modeled",
                        "study_area_filter": {"filter_method": "study_area_boundary"},
                        "prediction": {"status": "mapped", "valid_pixels": 725, "tif_exists": True, "png_exists": True},
                        "gcp": {"empirical_coverage": 0.8919, "report_exists": True},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    code, payload = run_exposure_cli(
        [
            "staging-dry-run",
            "--output",
            str(output_path),
            "--environment",
            "staging",
            "--percent",
            "10",
            "--smoke-report",
            str(report_path),
            "--active-effective",
            "--require-soil-moisture-gcp-smoke",
            "--soil-moisture-gcp-summary",
            str(soil_summary_path),
        ]
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    rendered = json.dumps(saved, ensure_ascii=False)
    assert code == 0
    assert payload["eligible_for_user_exposure"] is True
    assert saved["exposure"]["soil_moisture_gcp_smoke"]["status"] == "passed"
    assert saved["exposure"]["soil_moisture_gcp_smoke"]["case_count"] == 3
    assert str(soil_summary_path) not in rendered


def test_staging_exposure_dry_run_script_runs_smoke_and_evidence_cli() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "run_agent_runtime_staging_exposure_dry_run.ps1"

    content = script.read_text(encoding="utf-8")

    assert "run_agent_runtime_active_smoke.ps1" in content
    assert "core.agent_runtime.exposure" in content
    assert "staging-dry-run" in content
    assert "GIS_AGENT_RUNTIME_EXPOSURE_PERCENT" in content
    assert "run_soil_moisture_gcp_smoke.ps1" in content
    assert "-ValidateOnly" in content
    assert "--require-soil-moisture-gcp-smoke" in content
    assert "--soil-moisture-gcp-summary" in content
    assert "Invoke-Checked" in content


def test_staging_exposure_runbook_documents_admin_endpoint_and_rollback() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runbook = repo_root / "docs" / "runbooks" / "agent-runtime-staging-exposure.md"

    content = runbook.read_text(encoding="utf-8")

    assert "/api/admin/agent-runtime/exposure" in content
    assert "GIS_AGENT_RUNTIME_EXPOSURE_PERCENT" in content
    assert "GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING" in content
    assert "GIS_AGENT_RUNTIME_ROLLBACK=1" in content
    assert "1%" in content
    assert "10%" in content
