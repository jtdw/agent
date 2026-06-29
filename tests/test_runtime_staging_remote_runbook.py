from __future__ import annotations

from pathlib import Path


def test_remote_staging_sync_runbook_locks_phase56_checklist() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runbook = repo_root / "docs" / "runbooks" / "agent-runtime-remote-staging-sync.md"

    content = runbook.read_text(encoding="utf-8")

    required_terms = [
        "Phase 56",
        "GIS_AGENT_RUNTIME_EXPOSURE_ENV=staging",
        "GIS_AGENT_RUNTIME_EXPOSURE_PERCENT=10",
        "GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING=1",
        "GIS_AGENT_RUNTIME_ROLLBACK=0",
        "GIS_AGENT_RUNTIME_REQUIRE_SOIL_MOISTURE_GCP_SMOKE=1",
        "GIS_AGENT_RUNTIME_SMOKE_REPORT",
        "GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_REPORT",
        "/api/admin/agent-runtime/exposure",
        "eligible_for_user_exposure",
        "recommendation",
        "rollback_requested",
        "pwsh -File .\\scripts\\run_agent_runtime_staging10_observation_gate.ps1",
        "pwsh -File .\\scripts\\run_soil_moisture_gcp_smoke.ps1",
    ]

    for term in required_terms:
        assert term in content


def test_remote_staging_sync_runbook_documents_observation_metrics_and_rollbacks() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runbook = repo_root / "docs" / "runbooks" / "agent-runtime-remote-staging-sync.md"

    content = runbook.read_text(encoding="utf-8")

    required_terms = [
        "部署后立即运行一次 full observation gate",
        "每 15-30 分钟运行一次",
        "每 2-4 小时运行一次",
        "请求总量",
        "active 命中量",
        "legacy fallback 量",
        "HTTP 4xx/5xx",
        "runtime planner fallback 原因分布",
        "外部下载工具误触发次数",
        "artifact/map/raster/png/summary 输出成功率",
        "p50/p95 latency",
        "active smoke 低于 9/9",
        "observation gate 失败",
        "soil moisture/GCP recurring gate 失败",
        "新请求全部回到 legacy/fallback 路径",
    ]

    for term in required_terms:
        assert term in content


def test_remote_staging_sync_runbook_documents_ci_cache_observation_without_installed_cache() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runbook = repo_root / "docs" / "runbooks" / "agent-runtime-remote-staging-sync.md"

    content = runbook.read_text(encoding="utf-8")

    required_terms = [
        "gh pr checks 3 --repo jtdw/agent",
        "python-tests",
        "frontend-build",
        "smoke",
        "Install Python dependencies",
        "Install frontend dependencies",
        "actions/setup-python",
        "actions/setup-node",
        "Yarn fallback cache",
        "不要缓存 node_modules",
        "不要缓存 .venv",
    ]

    for term in required_terms:
        assert term in content
