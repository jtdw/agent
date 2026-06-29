param(
    [string]$OutputPath = "outputs/phase52_staging10_observation_gate.json",
    [string]$DiagnosticsOutput = "outputs/phase52_staging10_diagnostics.json",
    [string]$EvalOutputsOutput = "outputs/phase52_staging10_eval_outputs.json",
    [string]$SoilMoistureGcpSummaryPath = "outputs/phase45_real_soil_gcp_smoke/phase45_real_soil_gcp_recurring_smoke_summary.json",
    [string]$Phase49Path = "outputs/phase49_staging10_observation_window.json",
    [string]$Phase50Path = "outputs/phase50_staging10_routed_request_smoke.json",
    [string]$TaskWindowOutput = "outputs/phase52_staging10_quasi_real_task_window.json",
    [string]$TaskWorkspacePath = "outputs/phase52_staging10_quasi_real_task_workspace",
    [string[]]$ObservationCases = @(
        "active_vector_clip_map",
        "active_table_to_points_map",
        "xgboost_raster_prediction_map"
    )
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:GIS_AGENT_RUNTIME_V2 = "1"
$env:GIS_AGENT_RUNTIME_MODE = "active"
$env:GIS_AGENT_RUNTIME_ALLOW_ACTIVE_CUTOVER = "1"
$env:GIS_AGENT_RUNTIME_EXPOSURE_ENV = "staging"
$env:GIS_AGENT_RUNTIME_EXPOSURE_PERCENT = "10"
$env:GIS_AGENT_RUNTIME_ENFORCE_EXPOSURE_ROUTING = "1"
$env:GIS_AGENT_RUNTIME_ROLLBACK = "0"
$env:GIS_AGENT_RUNTIME_REQUIRE_SOIL_MOISTURE_GCP_SMOKE = "1"
$env:GIS_AGENT_RUNTIME_SMOKE_REPORT = $OutputPath
$env:GIS_AGENT_RUNTIME_SOIL_MOISTURE_GCP_SMOKE_SUMMARY = $SoilMoistureGcpSummaryPath

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

Invoke-Checked {
    & .\scripts\capture_agent_runtime_diagnostics.ps1 `
        -DiagnosticsOutput $DiagnosticsOutput `
        -CaseId active_vector_clip_map `
        -EvalOutputsOutput $EvalOutputsOutput
}

Invoke-Checked {
    & .\scripts\run_soil_moisture_gcp_smoke.ps1 `
        -OutputPath $SoilMoistureGcpSummaryPath `
        -ValidateOnly
}

Invoke-Checked {
    & .\scripts\run_agent_runtime_active_smoke.ps1 `
        -OutputPath $TaskWindowOutput `
        -WorkspacePath $TaskWorkspacePath `
        -CoordinatorMode deterministic `
        -RuntimeAgent lightweight `
        -Case $ObservationCases `
        -FailOnError
}

Invoke-Checked {
    & $python -m core.agent_runtime.staging_observation_gate `
        summarize `
        --phase49 $Phase49Path `
        --phase50 $Phase50Path `
        --phase51 $TaskWindowOutput `
        --output $OutputPath
}
