param(
    [string]$DiagnosticsOutput = "outputs\agent_runtime_diagnostics.json",
    [string]$CaseId = "",
    [string]$EvalOutputsOutput = "outputs\agent_runtime_eval_outputs.json"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$argsList = @(
    "-m",
    "core.agent_runtime.diagnostics_capture",
    "service",
    "--diagnostics-output",
    $DiagnosticsOutput
)

if ($CaseId) {
    $argsList += @("--case-id", $CaseId, "--eval-outputs-output", $EvalOutputsOutput)
}

& $python @argsList
