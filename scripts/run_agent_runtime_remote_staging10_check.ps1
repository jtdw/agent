param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,
    [string]$OutputPath = "outputs/phase53_remote_staging10_baseline.json",
    [string]$AdminToken = $env:GIS_AGENT_ADMIN_TOKEN,
    [ValidateSet("staging")]
    [string]$ExpectedEnvironment = "staging",
    [int]$ExpectedExposurePercent = 10,
    [switch]$FailOnNotReady
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-ObjectValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) {
        return $null
    }
    if ($null -ne $Object.PSObject.Properties[$Name]) {
        return $Object.$Name
    }
    return $null
}

function Convert-ToBool {
    param([object]$Value)

    if ($null -eq $Value) {
        return $false
    }
    return [bool]$Value
}

if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    throw "BaseUrl is required."
}

$baseUri = [Uri]$BaseUrl
if ($baseUri.Scheme -notin @("http", "https")) {
    throw "BaseUrl must use http or https."
}
if (-not [string]::IsNullOrWhiteSpace($baseUri.UserInfo)) {
    throw "BaseUrl must not include credentials."
}

$endpoint = $BaseUrl.TrimEnd("/") + "/api/admin/agent-runtime/exposure"
$headers = @{}
if (-not [string]::IsNullOrWhiteSpace($AdminToken)) {
    $headers["x-admin-token"] = $AdminToken
}

$adminExposure = Invoke-RestMethod -Uri $endpoint -Headers $headers -Method Get -TimeoutSec 30
$deterministicSmoke = Get-ObjectValue -Object $adminExposure -Name "deterministic_smoke"
$soilMoistureGcpSmoke = Get-ObjectValue -Object $adminExposure -Name "soil_moisture_gcp_smoke"

$checks = [ordered]@{
    schema_ok = (Get-ObjectValue -Object $adminExposure -Name "schema_version") -eq "agent-runtime-exposure-policy/v1"
    environment_ok = (Get-ObjectValue -Object $adminExposure -Name "environment") -eq $ExpectedEnvironment
    exposure_percent_ok = [int](Get-ObjectValue -Object $adminExposure -Name "requested_percent") -eq $ExpectedExposurePercent
    rollback_off = -not (Convert-ToBool (Get-ObjectValue -Object $adminExposure -Name "rollback_requested"))
    eligible_for_user_exposure = Convert-ToBool (Get-ObjectValue -Object $adminExposure -Name "eligible_for_user_exposure")
    recommendation_ok = (Get-ObjectValue -Object $adminExposure -Name "recommendation") -eq "allow_staging_exposure"
    deterministic_smoke_passed = (Get-ObjectValue -Object $deterministicSmoke -Name "status") -eq "passed"
    soil_moisture_gcp_smoke_passed = (Get-ObjectValue -Object $soilMoistureGcpSmoke -Name "status") -eq "passed"
}

$ok = $true
foreach ($value in $checks.Values) {
    if (-not [bool]$value) {
        $ok = $false
        break
    }
}

$report = [ordered]@{
    schema_version = "phase53-remote-staging10-baseline/v1"
    checked_at = (Get-Date).ToUniversalTime().ToString("o")
    mode = "read_only_remote_admin_exposure_check"
    endpoint = $endpoint
    expected = [ordered]@{
        environment = $ExpectedEnvironment
        exposure_percent = $ExpectedExposurePercent
    }
    ok = $ok
    checks = $checks
    admin_exposure = $adminExposure
    next_actions = @(
        "Keep staging exposure at 10 percent until recurring observation gates are stable.",
        "If any check is false, set GIS_AGENT_RUNTIME_ROLLBACK=1 and restart or reload the remote staging service.",
        "Archive this JSON with the matching remote service commit and observation window evidence."
    )
}

$outputFile = [System.IO.Path]::GetFullPath((Join-Path $root $OutputPath))
$outputDir = [System.IO.Path]::GetDirectoryName($outputFile)
if (-not [string]::IsNullOrWhiteSpace($outputDir)) {
    [System.IO.Directory]::CreateDirectory($outputDir) | Out-Null
}

$json = $report | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($outputFile, $json, [System.Text.UTF8Encoding]::new($false))
Write-Output "Phase 53 remote staging check ok=$ok output=$OutputPath"
if ($FailOnNotReady -and -not $ok) {
    exit 1
}
