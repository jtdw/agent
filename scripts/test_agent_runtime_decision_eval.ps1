param(
    [string]$MinPassRate = "1.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

function Invoke-Checked {
    param(
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Invoke-Checked { & $python -m pytest tests\test_agent_runtime_phase1.py tests\test_agent_runtime_planner_adapter.py tests\test_agent_runtime_decision_eval.py tests\test_agent_runtime_decision_eval_ci.py tests\test_agent_runtime_diagnostics_capture.py tests\test_agent_runtime_exposure_policy.py tests\test_agent_runtime_traffic_routing.py -q }
Invoke-Checked { & $python -m core.agent_runtime.decision_eval report --outputs tests\fixtures\agent_runtime_decision_eval_outputs.json --min-pass-rate $MinPassRate }
