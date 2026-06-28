param(
    [string]$BaselinePath = "outputs/phase53_remote_staging10_baseline.json",
    [string]$ObservationGatePath = "outputs/phase53_remote_staging10_observation_gate.json",
    [string]$RollbackProbePath = "outputs/phase53_remote_staging10_rollback_probe.json",
    [string]$OutputPath = "outputs/phase53_remote_staging10_evidence_summary.json"
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

& $python -m core.agent_runtime.phase53_remote_staging_evidence `
    summarize `
    --baseline $BaselinePath `
    --observation-gate $ObservationGatePath `
    --rollback-probe $RollbackProbePath `
    --output $OutputPath

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
