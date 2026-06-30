# Start GIS Agent React web UI.
# Run this from the project root in a second PowerShell window.
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Set-Location -Path "$PSScriptRoot\ui_next"
npm install
npm run dev -- --host 127.0.0.1 --port 5173
