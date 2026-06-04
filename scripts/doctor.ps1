param(
    [string]$BackendUrl = "http://127.0.0.1:8765",
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Problems = New-Object System.Collections.Generic.List[string]
$Warnings = New-Object System.Collections.Generic.List[string]

function Add-Problem([string]$Message) { $Problems.Add($Message) | Out-Null }
function Add-Warning([string]$Message) { $Warnings.Add($Message) | Out-Null }
function Test-CommandOk([scriptblock]$Block) {
    try {
        & $Block | Out-Null
        return $true
    } catch {
        return $false
    }
}

Write-Host "GIS Agent doctor"
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path $Python)) {
    Add-Problem "Missing project virtualenv: .venv\Scripts\python.exe"
} else {
    $pyVersion = & $Python --version
    Write-Host "Python: $pyVersion"
    if ($pyVersion -notmatch "3\.12") {
        Add-Warning "Python 3.12 is recommended for Windows GIS wheels."
    }
    foreach ($pkg in @("uvicorn", "fastapi", "fiona", "playwright")) {
        if (-not (Test-CommandOk { & $Python -m pip show $pkg })) {
            Add-Problem "Missing Python package: $pkg"
        }
    }
}

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
    Add-Warning ".env is missing; backend requires ZAI_API_KEY unless environment variables are set."
}

if (-not $env:ZAI_API_KEY -and -not (Select-String -Path (Join-Path $ProjectRoot ".env") -Pattern "^ZAI_API_KEY=.+" -ErrorAction SilentlyContinue)) {
    Add-Warning "ZAI_API_KEY is not visible in environment or .env."
}

if ($env:GIS_AGENT_ENV -match "^(prod|production)$") {
    foreach ($name in @("APP_SECRET_KEY", "GIS_AGENT_ADMIN_TOKEN")) {
        if (-not [Environment]::GetEnvironmentVariable($name)) {
            Add-Problem "Production requires $name."
        }
    }
    if ($env:GIS_AGENT_COOKIE_SECURE -notmatch "^(1|true|yes|on)$") {
        Add-Problem "Production requires GIS_AGENT_COOKIE_SECURE=1."
    }
}

if (Test-Path (Join-Path $ProjectRoot "ui_next\node_modules")) {
    Write-Host "Frontend dependencies: present"
} else {
    Add-Warning "ui_next\node_modules is missing; run npm install in ui_next."
}

try {
    $status = Invoke-RestMethod -Uri "$BackendUrl/api/status" -TimeoutSec 5
    if ($status.ok) {
        Write-Host "Backend: OK $BackendUrl"
    } else {
        Add-Warning "Backend responded but did not report ok=true."
    }
} catch {
    Add-Warning "Backend is not reachable at $BackendUrl. Start it with .\start_backend_api.ps1."
}

$stateCandidates = @(
    $env:GSCLOUD_PLATFORM_STORAGE_STATE,
    (Join-Path $ProjectRoot "workspace\domestic_auth\platform_gscloud_storage_state.json")
) | Where-Object { $_ }
if ($stateCandidates.Count -gt 0 -and $stateCandidates[0] -and (Test-Path $stateCandidates[0])) {
    Write-Host "GSCloud storage_state: found"
} else {
    Add-Warning "GSCloud platform storage_state was not found; automated downloads may need relogin."
}

if ($Warnings.Count) {
    Write-Host ""
    Write-Host "Warnings:" -ForegroundColor Yellow
    $Warnings | ForEach-Object { Write-Host " - $_" -ForegroundColor Yellow }
}
if ($Problems.Count) {
    Write-Host ""
    Write-Host "Problems:" -ForegroundColor Red
    $Problems | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
    exit 1
}
if ($Strict -and $Warnings.Count) {
    exit 2
}
Write-Host ""
Write-Host "Doctor completed."
