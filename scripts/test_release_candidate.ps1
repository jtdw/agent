param(
    [switch]$SkipBrowserE2E
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& .\.venv\Scripts\python.exe -m pytest -q

Push-Location .\ui_next
try {
    npm run build
    npm test
    if (-not $SkipBrowserE2E) {
        npm run test:e2e:real
    }
}
finally {
    Pop-Location
}
