param(
    [switch]$Delete
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$targets = @(
    "ui_next\test-results",
    "ui_next\dist"
)

foreach ($relative in $targets) {
    $path = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Output "missing $relative"
        continue
    }
    $item = Get-Item -LiteralPath $path
    $bytes = (Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    $mb = [Math]::Round(($bytes / 1MB), 2)
    if ($Delete) {
        Remove-Item -LiteralPath $item.FullName -Recurse -Force
        Write-Output "deleted $relative ($mb MB)"
    } else {
        Write-Output "preview $relative ($mb MB)"
    }
}

if (-not $Delete) {
    Write-Output "Run with -Delete to remove these generated frontend artifacts."
}
