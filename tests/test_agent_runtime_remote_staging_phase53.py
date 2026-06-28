from __future__ import annotations

import json
from pathlib import Path


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _baseline_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "phase53-remote-staging10-baseline/v1",
            "ok": True,
            "checks": {
                "schema_ok": True,
                "environment_ok": True,
                "exposure_percent_ok": True,
                "rollback_off": True,
                "eligible_for_user_exposure": True,
                "recommendation_ok": True,
                "deterministic_smoke_passed": True,
                "soil_moisture_gcp_smoke_passed": True,
            },
            "admin_exposure": {
                "environment": "staging",
                "requested_percent": 10,
                "eligible_for_user_exposure": True,
                "recommendation": "allow_staging_exposure",
            },
        },
    )


def _observation_gate_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "phase52-staging10-observation-gate/v1",
            "ok": True,
            "checks": {
                "phase49_policy_and_routing_ok": True,
                "phase50_service_routing_ok": True,
                "phase51_quality_window_ok": True,
                "phase51_has_three_cases": True,
                "phase51_all_cases_passed": True,
                "no_external_download_tools": True,
                "artifact_and_map_outputs_present": True,
            },
            "task_window": {"summary": {"case_count": 3, "passed": 3, "failed": 0}},
        },
    )


def _rollback_probe_fixture(path: Path) -> Path:
    return _write_json(
        path,
        {
            "schema_version": "phase53-remote-staging10-baseline/v1",
            "ok": False,
            "checks": {
                "schema_ok": True,
                "environment_ok": True,
                "exposure_percent_ok": True,
                "rollback_off": False,
                "eligible_for_user_exposure": False,
                "recommendation_ok": False,
                "deterministic_smoke_passed": True,
                "soil_moisture_gcp_smoke_passed": True,
            },
            "admin_exposure": {
                "environment": "staging",
                "requested_percent": 10,
                "rollback_requested": True,
                "eligible_for_user_exposure": False,
                "recommendation": "do_not_expose_users",
                "reasons": ["rollback_requested"],
            },
        },
    )


def test_phase53_evidence_summary_accepts_baseline_gate_and_rollback_probe(tmp_path: Path) -> None:
    from core.agent_runtime.phase53_remote_staging_evidence import build_phase53_evidence_summary

    output = tmp_path / "phase53_summary.json"

    summary = build_phase53_evidence_summary(
        baseline_path=_baseline_fixture(tmp_path / "baseline.json"),
        observation_gate_path=_observation_gate_fixture(tmp_path / "observation_gate.json"),
        rollback_probe_path=_rollback_probe_fixture(tmp_path / "rollback_probe.json"),
        output_path=output,
    )

    saved = json.loads(output.read_text(encoding="utf-8"))
    rendered = json.dumps(saved, ensure_ascii=False)
    assert summary["ok"] is True
    assert saved["schema_version"] == "phase53-remote-staging-evidence/v1"
    assert saved["checks"]["baseline_ready_for_staging10"] is True
    assert saved["checks"]["observation_gate_ok"] is True
    assert saved["checks"]["rollback_probe_confirms_block"] is True
    assert saved["evidence_files"]["baseline"] == "baseline.json"
    assert ":\\\\" not in rendered


def test_phase53_evidence_validation_script_wraps_python_summary() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "validate_agent_runtime_phase53_evidence.ps1"

    content = script.read_text(encoding="utf-8")

    assert "phase53_remote_staging10_evidence_summary.json" in content
    assert "core.agent_runtime.phase53_remote_staging_evidence" in content
    assert "--baseline" in content
    assert "--observation-gate" in content
    assert "--rollback-probe" in content


def test_phase53_remote_staging_script_is_read_only_and_token_safe() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "run_agent_runtime_remote_staging10_check.ps1"

    content = script.read_text(encoding="utf-8")

    assert "[Parameter(Mandatory = $true)]" in content
    assert "[string]$BaseUrl" in content
    assert "phase53_remote_staging10_baseline.json" in content
    assert "/api/admin/agent-runtime/exposure" in content
    assert "Invoke-RestMethod" in content
    assert "-Method Get" in content
    assert "[switch]$FailOnNotReady" in content
    assert "if ($FailOnNotReady -and -not $ok)" in content
    assert "x-admin-token" in content
    assert "GIS_AGENT_ADMIN_TOKEN" in content
    assert "GIS_AGENT_RUNTIME_ADMIN_TOKEN" not in content
    assert "Set-Content" not in content
    assert "Add-Content" not in content
    assert "GIS_AGENT_RUNTIME_EXPOSURE_PERCENT =" not in content
    assert "GIS_AGENT_RUNTIME_ROLLBACK =" not in content


def test_phase53_remote_staging_runbook_documents_remote_checks_and_rollback() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runbook = repo_root / "docs" / "runbooks" / "agent-runtime-phase53-remote-staging-observation.md"

    content = runbook.read_text(encoding="utf-8")

    assert "Phase 53" in content
    assert "f0d3a69" in content
    assert "run_agent_runtime_remote_staging10_check.ps1" in content
    assert "phase53_remote_staging10_baseline.json" in content
    assert "phase53_remote_staging10_observation_gate.json" in content
    assert "GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=10" in content
    assert "GIS_AGENT_RUNTIME_ROLLBACK=1" in content
    assert "30 分钟" in content
    assert "2 小时" in content
    assert "外部下载误触发" in content
    assert "artifact/map" in content
    assert "soil moisture/GCP" in content
    assert "latency" in content


def test_staging_exposure_runbook_links_phase53_remote_observation() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runbook = repo_root / "docs" / "runbooks" / "agent-runtime-staging-exposure.md"

    content = runbook.read_text(encoding="utf-8")

    assert "Phase 53" in content
    assert "agent-runtime-phase53-remote-staging-observation.md" in content
