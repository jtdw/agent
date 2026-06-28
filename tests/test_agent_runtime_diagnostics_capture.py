from __future__ import annotations

import json
import tempfile
from pathlib import Path


class FakeService:
    def agent_runtime_diagnostics(self) -> dict:
        return {
            "available": True,
            "decision_trace": {
                "schema_version": "runtime-decision-trace/v1",
                "planner": {
                    "task_type": "data_inspection",
                    "planned_tools": ["describe_dataset"],
                    "requires_confirmation": False,
                },
                "coordinator": {
                    "decision": "continue",
                    "required_tool": "describe_dataset",
                },
                "executes_tools": False,
            },
        }


def test_capture_service_runtime_diagnostics_writes_diagnostics_and_eval_outputs() -> None:
    from core.agent_runtime.diagnostics_capture import capture_service_runtime_diagnostics

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        diagnostics_path = Path(tmp) / "diagnostics.json"
        outputs_path = Path(tmp) / "outputs.json"

        payload = capture_service_runtime_diagnostics(
            FakeService(),
            diagnostics_output=diagnostics_path,
            case_id="describe_uploaded_vector",
            eval_outputs_output=outputs_path,
        )
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        outputs = json.loads(outputs_path.read_text(encoding="utf-8"))

    assert payload["ok"] is True
    assert payload["schema_version"] == "agent-runtime-diagnostics-capture/v1"
    assert payload["diagnostics_filename"] == "diagnostics.json"
    assert payload["eval_outputs_filename"] == "outputs.json"
    assert payload["operations"]["llm_calls_performed"] == 0
    assert payload["operations"]["tool_calls_performed"] == 0
    assert str(diagnostics_path) not in str(payload)
    assert diagnostics["decision_trace"]["planner"]["planned_tools"] == ["describe_dataset"]
    assert outputs["describe_uploaded_vector"]["planner"]["planned_steps"] == [{"tool_name": "describe_dataset"}]


def test_diagnostics_capture_cli_uses_service_factory_and_writes_files() -> None:
    from core.agent_runtime import diagnostics_capture

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        diagnostics_path = Path(tmp) / "diagnostics.json"
        outputs_path = Path(tmp) / "outputs.json"

        code, payload = diagnostics_capture.run_diagnostics_capture_cli(
            [
                "service",
                "--diagnostics-output",
                str(diagnostics_path),
                "--case-id",
                "describe_uploaded_vector",
                "--eval-outputs-output",
                str(outputs_path),
            ],
            service_factory=FakeService,
        )
        outputs = json.loads(outputs_path.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["command"] == "service"
    assert payload["diagnostics_filename"] == "diagnostics.json"
    assert payload["eval_outputs_filename"] == "outputs.json"
    assert outputs["describe_uploaded_vector"]["coordinator"]["required_tool"] == "describe_dataset"
