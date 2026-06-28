param(
    [switch]$IncludeLlmCoordinatorSmoke
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:GIS_AGENT_RUNTIME_V2 = "1"
$env:GIS_AGENT_RUNTIME_MODE = "active"
$env:GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER = "1"

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

function Invoke-Checked {
    param(
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Invoke-Checked { & $python -m pytest tests\test_agent_runtime_active_smoke.py tests\test_agent_runtime_active_smoke_guard.py -q }

Invoke-Checked {
    & .\scripts\run_agent_runtime_active_smoke.ps1 `
        -OutputPath "outputs/agent_runtime_service_active_smoke_guard.json" `
        -WorkspacePath "outputs/agent_runtime_service_active_smoke_guard_workspace" `
        -CoordinatorMode deterministic `
        -RuntimeAgent lightweight `
        -FailOnError
}

$runLlmSmoke = $IncludeLlmCoordinatorSmoke -or ($env:GIS_AGENT_RUN_LLM_COORDINATOR_SMOKE -match "^(1|true|yes|on)$")
if ($runLlmSmoke) {
    Invoke-Checked {
        & .\scripts\run_agent_runtime_active_smoke.ps1 `
            -OutputPath "outputs/agent_runtime_service_llm_coordinator_describe_guard.json" `
            -WorkspacePath "outputs/agent_runtime_service_llm_coordinator_describe_guard_workspace" `
            -CoordinatorMode llm `
            -RuntimeAgent lightweight `
            -FailOnError `
            -Case active_describe_vector
    }

    Invoke-Checked {
        & .\scripts\run_agent_runtime_active_smoke.ps1 `
            -OutputPath "outputs/agent_runtime_service_llm_coordinator_map_guard.json" `
            -WorkspacePath "outputs/agent_runtime_service_llm_coordinator_map_guard_workspace" `
            -CoordinatorMode llm `
            -RuntimeAgent lightweight `
            -FailOnError `
            -Case active_map_generation
    }

    Invoke-Checked {
        & .\scripts\run_agent_runtime_active_smoke.ps1 `
            -OutputPath "outputs/agent_runtime_service_llm_coordinator_table_points_guard.json" `
            -WorkspacePath "outputs/agent_runtime_service_llm_coordinator_table_points_guard_workspace" `
            -CoordinatorMode llm `
            -RuntimeAgent lightweight `
            -FailOnError `
            -Case workflow_priority_table_to_points
    }

    Invoke-Checked {
        & .\scripts\run_agent_runtime_active_smoke.ps1 `
            -OutputPath "outputs/agent_runtime_service_llm_coordinator_raster_clip_guard.json" `
            -WorkspacePath "outputs/agent_runtime_service_llm_coordinator_raster_clip_guard_workspace" `
            -CoordinatorMode llm `
            -RuntimeAgent lightweight `
            -FailOnError `
            -Case active_raster_clip_by_boundary
    }

    Invoke-Checked {
        & .\scripts\run_agent_runtime_active_smoke.ps1 `
            -OutputPath "outputs/agent_runtime_service_llm_coordinator_vector_clip_map_guard.json" `
            -WorkspacePath "outputs/agent_runtime_service_llm_coordinator_vector_clip_map_guard_workspace" `
            -CoordinatorMode llm `
            -RuntimeAgent lightweight `
            -FailOnError `
            -Case active_vector_clip_map
    }

    Invoke-Checked {
        & .\scripts\run_agent_runtime_active_smoke.ps1 `
            -OutputPath "outputs/agent_runtime_service_llm_coordinator_table_points_map_guard.json" `
            -WorkspacePath "outputs/agent_runtime_service_llm_coordinator_table_points_map_guard_workspace" `
            -CoordinatorMode llm `
            -RuntimeAgent lightweight `
            -FailOnError `
            -Case active_table_to_points_map
    }
}
