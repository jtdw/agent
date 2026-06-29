from __future__ import annotations

import json
from pathlib import Path


def test_ci_uses_stable_node_lts_for_frontend_jobs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'node-version: "20"' in workflow
    assert 'node-version: "22"' not in workflow
    assert ".\\scripts\\install_frontend_dependencies.ps1" in workflow


def test_ci_caches_python_dependencies_for_python_jobs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert workflow.count("cache: pip") >= 2
    assert workflow.count("cache-dependency-path: requirements.txt") >= 2


def test_ci_caches_package_manager_downloads_not_installed_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "Cache Yarn fallback download cache" in workflow
    assert "actions/cache@v4" in workflow
    assert "~\\AppData\\Local\\Yarn\\Cache" in workflow
    assert "hashFiles('ui_next/package-lock.json')" in workflow

    for line in workflow.splitlines():
        if line.strip().startswith("path:"):
            assert "node_modules" not in line
            assert ".venv" not in line


def test_ci_python_gate_uses_curated_script_not_unbounded_discover() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert ".\\scripts\\test_ci_python.ps1" in workflow
    assert "python -m unittest discover tests" not in workflow


def test_ci_python_script_runs_stable_runtime_and_contract_suites() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "test_ci_python.ps1").read_text(encoding="utf-8")

    assert "test_agent_runtime_decision_eval.ps1" in script
    assert "test_agent_runtime_active_smoke.ps1" in script
    assert "test_admin_agent_runtime_diagnostics.py" in script
    assert "test_agent_runtime_staging_observation_gate.py" in script
    assert "test_agent_runtime_exposure_policy.py" in script
    assert "test_ci_baseline_workflow.py" in script
    assert "test_semantic_parser.py" not in script
    assert "test_checkpoint_route_migration.py" not in script
    assert "test_checkpoint_map_layer_service.py" not in script
    assert "test_admin_boundary_county.py" not in script
    assert "test_gscloud_dem_region_routing.py" not in script


def test_frontend_install_script_falls_back_when_npm_ci_leaves_incomplete_modules() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "install_frontend_dependencies.ps1").read_text(encoding="utf-8")

    assert "npm.cmd ci" in script
    assert "npm.cmd install" in script
    assert "corepack.cmd prepare yarn@1.22.22 --activate" in script
    assert "yarn.cmd install --no-lockfile --non-interactive --ignore-engines" in script
    assert "node_modules" in script
    assert "tsc.cmd" in script
    assert "Invoke-Npm" in script


def test_ci_doctor_uses_actions_python_instead_of_requiring_project_venv() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    doctor = (repo_root / "scripts" / "doctor.ps1").read_text(encoding="utf-8")

    assert ".\\scripts\\doctor.ps1 -PythonPath python" in workflow
    assert "[string]$PythonPath" in doctor
    assert "Missing project virtualenv" in doctor


def test_frontend_declares_geojson_types_for_yarn_fallback_build() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    package_json = json.loads((repo_root / "ui_next" / "package.json").read_text(encoding="utf-8"))

    assert "@types/geojson" in package_json["devDependencies"]
    assert "react-is" in package_json["dependencies"]


def test_smoke_workflow_waits_for_services_instead_of_fixed_sleep() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workflow = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "Start-Sleep -Seconds 25" not in workflow
    assert "-PassThru" in workflow
    assert "Invoke-RestMethod" in workflow
    assert "Invoke-WebRequest" in workflow
    assert "/api/status" in workflow
    assert ".HasExited" in workflow
    assert "- name: Run E2E smoke\n        run: python scripts\\e2e_smoke.py" not in workflow
    assert "python scripts\\e2e_smoke.py" in workflow
    assert "Stop-Process -Id $process.Id" in workflow
