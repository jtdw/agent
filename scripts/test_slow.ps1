param(
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

& .\.venv\Scripts\python.exe -m pytest -q -m "slow" @ExtraArgs
