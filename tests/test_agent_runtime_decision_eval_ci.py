from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_decision_eval_ci_fixture_passes_report_cli_without_live_operations() -> None:
    from core.agent_runtime.decision_eval import default_runtime_decision_eval_cases

    repo_root = Path(__file__).resolve().parents[1]
    fixture_path = repo_root / "tests" / "fixtures" / "agent_runtime_decision_eval_outputs.json"
    expected_case_ids = {case["case_id"] for case in default_runtime_decision_eval_cases()}
    outputs = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert set(outputs) == expected_case_ids

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.agent_runtime.decision_eval",
            "report",
            "--outputs",
            str(fixture_path),
            "--min-pass-rate",
            "1.0",
        ],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["report"]["ready_for_cutover_eval"] is True
    assert payload["report"]["planner"]["pass_rate"] == 1.0
    assert payload["report"]["coordinator"]["pass_rate"] == 1.0
    assert payload["operations"]["llm_calls_performed"] == 0
    assert payload["operations"]["tool_calls_performed"] == 0
    assert str(fixture_path) not in completed.stdout


def test_decision_eval_guard_script_checks_child_exit_codes() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "test_agent_runtime_decision_eval.ps1").read_text(encoding="utf-8")

    assert "Invoke-Checked" in script
    assert "$LASTEXITCODE" in script
    assert "tests\\test_agent_runtime_exposure_policy.py" in script
