param(
    [string]$OutputPath = "outputs/agent_runtime_service_active_smoke.json",
    [string]$WorkspacePath = "outputs/agent_runtime_service_active_smoke_workspace",
    [ValidateSet("deterministic", "llm")]
    [string]$CoordinatorMode = "deterministic",
    [ValidateSet("lightweight", "real")]
    [string]$RuntimeAgent = "lightweight",
    [string[]]$Case = @(),
    [switch]$FailOnError
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

$argsList = @(
    "-m", "core.agent_runtime.active_smoke",
    "service",
    "--output", $OutputPath,
    "--workspace", $WorkspacePath,
    "--coordinator-mode", $CoordinatorMode,
    "--runtime-agent", $RuntimeAgent
)

foreach ($item in $Case) {
    if (-not [string]::IsNullOrWhiteSpace($item)) {
        $argsList += @("--case", $item)
    }
}

if ($FailOnError) {
    $argsList += "--fail-on-error"
}

& $python @argsList
exit $LASTEXITCODE
