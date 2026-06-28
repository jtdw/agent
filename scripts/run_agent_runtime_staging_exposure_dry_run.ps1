param(
    [string]$OutputPath = "outputs/agent_runtime_exposure_staging_dry_run.json",
    [string]$SmokeOutputPath = "outputs/agent_runtime_service_active_smoke_guard.json",
    [string]$SmokeWorkspacePath = "outputs/agent_runtime_service_active_smoke_guard_workspace",
    [ValidateSet("local", "staging")]
    [string]$ExposureEnvironment = "staging",
    [int]$ExposurePercent = 1
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:GIS_AGENT_RUNTIME_V2 = "1"
$env:GIS_AGENT_RUNTIME_MODE = "active"
$env:GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER = "1"
$env:GIS_AGENT_RUNTIME_EXPOSURE_ENV = $ExposureEnvironment
$env:GIS_AGENT_RUNTIME_EXPOSURE_PERCENT = [string]$ExposurePercent
$env:GIS_AGENT_RUNTIME_ROLLBACK = "0"
$env:GIS_AGENT_RUNTIME_SMOKE_REPORT = $SmokeOutputPath

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

Invoke-Checked {
    & .\scripts\run_agent_runtime_active_smoke.ps1 `
        -OutputPath $SmokeOutputPath `
        -WorkspacePath $SmokeWorkspacePath `
        -CoordinatorMode deterministic `
        -RuntimeAgent lightweight `
        -FailOnError
}

Invoke-Checked {
    & $python -m core.agent_runtime.exposure `
        staging-dry-run `
        --output $OutputPath `
        --environment $ExposureEnvironment `
        --percent $ExposurePercent `
        --smoke-report $SmokeOutputPath `
        --active-effective
}
