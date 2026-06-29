param()

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$UiRoot = Join-Path $ProjectRoot "ui_next"

Set-Location $UiRoot

function Test-FrontendInstall {
    $tsc = Join-Path $UiRoot "node_modules\.bin\tsc.cmd"
    return Test-Path -LiteralPath $tsc
}

function Remove-FrontendNodeModules {
    $nodeModules = Join-Path $UiRoot "node_modules"
    if (-not (Test-Path -LiteralPath $nodeModules)) {
        return
    }

    $resolvedUi = (Resolve-Path -LiteralPath $UiRoot).Path
    $resolvedNodeModules = (Resolve-Path -LiteralPath $nodeModules).Path
    if (-not $resolvedNodeModules.StartsWith($resolvedUi, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove node_modules outside ui_next."
    }

    Remove-Item -LiteralPath $resolvedNodeModules -Recurse -Force
}

function Invoke-Npm {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("ci", "install")]
        [string]$Command
    )

    if ($Command -eq "ci") {
        & npm.cmd ci
    }
    else {
        & npm.cmd install --no-audit --fund=false
    }

    $script:NpmExitCode = $LASTEXITCODE
}

Invoke-Npm -Command "ci"
$ciExit = $script:NpmExitCode
if ($ciExit -eq 0 -and (Test-FrontendInstall)) {
    exit 0
}

Write-Warning "npm ci did not leave a complete frontend install; retrying with npm install."
Remove-FrontendNodeModules

Invoke-Npm -Command "install"
$installExit = $script:NpmExitCode
if ($installExit -ne 0) {
    exit $installExit
}

if (-not (Test-FrontendInstall)) {
    Write-Error "Frontend install completed without node_modules\.bin\tsc.cmd."
    exit 1
}
