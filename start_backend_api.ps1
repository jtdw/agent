# Start GIS Agent FastAPI backend.
# Run this from the project root.
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython app.py
} else {
    python app.py
}
