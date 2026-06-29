param(
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

function Invoke-Checked {
    param([scriptblock]$Command)

    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Invoke-Checked { & .\scripts\test_agent_runtime_decision_eval.ps1 }
Invoke-Checked { & .\scripts\test_agent_runtime_active_smoke.ps1 }

Invoke-Checked {
    & $python -m pytest `
        tests\test_admin_agent_runtime_diagnostics.py `
        tests\test_agent_runtime_staging_observation_gate.py `
        tests\test_agent_runtime_exposure_policy.py `
        tests\test_semantic_parser.py `
        tests\test_checkpoint_route_migration.py `
        tests\test_checkpoint_map_layer_service.py `
        tests\test_admin_boundary_county.py `
        tests\test_gscloud_dem_region_routing.py `
        tests\test_ci_baseline_workflow.py `
        -q `
        @ExtraArgs
}
