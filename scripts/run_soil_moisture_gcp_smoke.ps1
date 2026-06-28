param(
    [string]$SourcePath = "outputs/phase45_real_soil_gcp_smoke/phase45_real_soil_gcp_three_sample_smoke.json",
    [string]$OutputPath = "outputs/phase45_real_soil_gcp_smoke/phase45_real_soil_gcp_recurring_smoke_summary.json",
    [int]$MinCases = 3,
    [double]$MinGcpCoverage = 0.85,
    [switch]$ValidateOnly,
    [switch]$AllowMissingStudyAreaFilter
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

if ($ValidateOnly) {
    $argsList = @(
        "-m", "core.workflows.soil_moisture_gcp_smoke",
        "validate-summary",
        "--summary", $OutputPath,
        "--min-cases", [string]$MinCases,
        "--min-gcp-coverage", [string]$MinGcpCoverage
    )
}
else {
    $argsList = @(
        "-m", "core.workflows.soil_moisture_gcp_smoke",
        "recover-phase45",
        "--source", $SourcePath,
        "--output", $OutputPath,
        "--validate",
        "--min-cases", [string]$MinCases,
        "--min-gcp-coverage", [string]$MinGcpCoverage
    )
}

if ($AllowMissingStudyAreaFilter) {
    $argsList += "--allow-missing-study-area-filter"
}

& $python @argsList
exit $LASTEXITCODE
