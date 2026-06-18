from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .tools.registry import build_tools
from .tool_context import ToolRuntimeContext
from .tool_contracts import parse_tool_result, tool_result_error, tool_result_ok
from .tool_preconditions import validate_output_file_path


SUPPORTED_WORKFLOW_TOOLS = {
    "describe_dataset",
    "vector_clip_by_vector",
    "vector_overlay",
    "vector_spatial_join",
    "table_to_points",
    "extract_raster_values_to_points",
    "raster_zonal_stats",
    "raster_mosaic",
    "raster_reproject",
    "raster_algebra",
    "dem_terrain_derivatives",
    "plot_dataset",
    "train_xgboost_fusion_model",
    "train_rf_fusion_model",
    "geographical_conformal_prediction",
    "export_dataset",
}
VIRTUAL_WORKFLOW_TOOLS = {"field_match", "interpret_result", "export_artifact"}


@dataclass
class WorkflowStep:
    step_id: str
    tool_name: str
    step_type: str = ""
    validated_tool_args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    stop_on_failure: bool = True
    status: str = "pending"
    tool_result: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Any) -> "WorkflowStep":
        item = data if isinstance(data, dict) else {}
        args = item.get("validated_tool_args")
        if not isinstance(args, dict):
            args = item.get("args")
        depends = item.get("depends_on")
        expected = item.get("expected_outputs")
        return cls(
            step_id=str(item.get("step_id") or item.get("id") or ""),
            tool_name=str(item.get("tool_name") or ""),
            step_type=str(item.get("step_type") or ""),
            validated_tool_args=args if isinstance(args, dict) else {},
            depends_on=[str(value) for value in depends] if isinstance(depends, list) else [],
            expected_outputs=[str(value) for value in expected] if isinstance(expected, list) else [],
            stop_on_failure=bool(item.get("stop_on_failure", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowResult:
    ok: bool
    workflow_id: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    final_artifacts: list[dict[str, Any]] = field(default_factory=list)
    final_summary: str = ""
    failed_step: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)


def parse_workflow_result(value: Any) -> dict[str, Any] | None:
    if isinstance(value, WorkflowResult):
        return value.to_dict()
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        return None
    if not isinstance(payload, dict):
        return None
    required = {"ok", "workflow_id", "steps", "final_artifacts", "final_summary", "failed_step", "diagnostics", "next_actions"}
    if not required.issubset(payload):
        return None
    return payload


def _workflow_steps(plan: dict[str, Any]) -> list[WorkflowStep]:
    steps = plan.get("workflow_plan")
    if not isinstance(steps, list) or not steps:
        return []
    return [WorkflowStep.from_dict(step) for step in steps if isinstance(step, dict)]


def _step_result_by_id(completed: dict[str, WorkflowStep], step_id: str) -> dict[str, Any]:
    step = completed.get(step_id)
    return step.tool_result if step and isinstance(step.tool_result, dict) else {}


def _resolve_placeholder(value: Any, completed: dict[str, WorkflowStep]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_placeholder(item, completed) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_placeholder(item, completed) for item in value]
    if not isinstance(value, str) or not value.startswith("$steps."):
        return value
    parts = value.split(".")
    if len(parts) < 4:
        return value
    _, step_id, section, *path = parts
    result = _step_result_by_id(completed, step_id)
    current: Any = result.get(section)
    for key in path:
        if isinstance(current, list) and key.isdigit():
            index = int(key)
            if index < 0 or index >= len(current):
                return value
            current = current[index]
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return value
    return current if current not in (None, "") else value


def _error_result(tool_name: str, inputs: dict[str, Any], code: str, message: str, detail: str = "") -> dict[str, Any]:
    return tool_result_error(
        tool_name,
        inputs=inputs,
        error_code=code,
        error_title="Workflow step failed",
        user_message=message,
        technical_detail=detail[:1000],
        next_actions=["Review the failed workflow step, correct its inputs, then retry the workflow."],
    ).to_dict()


def _manager_has_dataset(manager: Any, name: str) -> bool:
    if not str(name or "").strip() or str(name).startswith("$steps."):
        return False
    try:
        manager.get(str(name))
        return True
    except Exception:
        return False


def _dataset_fields(manager: Any, name: str) -> set[str]:
    try:
        record = manager.get(str(name))
    except Exception:
        return set()
    meta = record.meta if isinstance(getattr(record, "meta", None), dict) else {}
    fields = {str(field) for field in meta.get("columns") or meta.get("fields") or [] if str(field or "").strip()}
    if fields:
        return fields
    try:
        if record.data_type == "vector":
            return {str(col) for col in manager.get_vector(name).columns}
        if record.data_type == "table":
            return {str(col) for col in manager.get_table(name).columns}
    except Exception:
        return set()
    return set()


def _path_inside(root: Path, path: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except Exception:
        return False


def _validate_step_objects(manager: Any, step: WorkflowStep) -> dict[str, Any] | None:
    args = step.validated_tool_args
    for key in (
        "dataset_name",
        "clip_name",
        "raster_name",
        "vector_name",
        "point_name",
        "polygon_name",
        "target_name",
        "join_name",
        "calibration_dataset",
        "target_dataset_name",
    ):
        value = str(args.get(key) or "").strip()
        if key in args and value and not _manager_has_dataset(manager, value):
            return _error_result(
                step.tool_name,
                args,
                "OBJECT_NOT_FOUND",
                f"Workflow step {step.step_id} references missing dataset object: {args.get(key)}.",
            )
    if step.tool_name == "plot_dataset" and args.get("column"):
        dataset_name = str(args.get("dataset_name") or "")
        fields = _dataset_fields(manager, dataset_name)
        if fields and str(args.get("column")) not in fields:
            return _error_result(
                step.tool_name,
                args,
                "OBJECT_NOT_FOUND",
                f"Workflow step {step.step_id} references missing field object: {args.get('column')}.",
                f"available_fields={sorted(fields)}",
            )
    if step.tool_name == "export_artifact":
        source_path = str(args.get("source_path") or "")
        if not source_path or source_path.startswith("$steps.") or not Path(source_path).exists():
            return _error_result(
                step.tool_name,
                args,
                "OBJECT_NOT_FOUND",
                f"Workflow step {step.step_id} references missing artifact object: {source_path}.",
            )
        if not _path_inside(manager.workdir, source_path):
            return _error_result(
                step.tool_name,
                args,
                "OBJECT_NOT_FOUND",
                f"Workflow step {step.step_id} references an artifact outside the current workspace.",
            )
        output_errors = validate_output_file_path(manager.workdir, str(args.get("output_path") or ""))
        if output_errors:
            first = output_errors[0]
            return _error_result(
                step.tool_name,
                args,
                str(first.get("error_code") or "OUTPUT_PATH_UNSAFE"),
                str(first.get("user_message") or "Workflow export output path is unsafe."),
            )
        output_path = Path(str(args.get("output_path") or ""))
        if output_path and not output_path.is_absolute():
            args["output_path"] = str((Path(manager.workdir).resolve() / output_path).resolve())
    return None


def _virtual_result(step: WorkflowStep) -> dict[str, Any]:
    if step.tool_name == "field_match":
        return tool_result_ok(
            "field_match",
            inputs=step.validated_tool_args,
            outputs={"candidate_fields": step.validated_tool_args.get("candidate_fields", [])},
            summary="Field matching step completed using planner-provided candidates.",
            next_actions=["Use the resolved field in the next GIS tool step."],
        ).to_dict()
    if step.tool_name == "export_artifact":
        source_raw = str(step.validated_tool_args.get("source_path") or "").strip()
        output_raw = str(step.validated_tool_args.get("output_path") or "").strip()
        source_path = Path(source_raw)
        output_path = Path(output_raw)
        if not source_raw or not source_path.exists():
            return _error_result(
                "export_artifact",
                step.validated_tool_args,
                "SOURCE_ARTIFACT_NOT_FOUND",
                "The artifact selected for export does not exist or was not provided.",
            )
        if not output_raw:
            return _error_result("export_artifact", step.validated_tool_args, "OUTPUT_PATH_REQUIRED", "An export output_path is required.")
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, output_path)
        except Exception as exc:
            return _error_result(
                "export_artifact",
                step.validated_tool_args,
                "ARTIFACT_EXPORT_FAILED",
                "The artifact could not be copied to the requested export path.",
                f"{type(exc).__name__}: {exc}",
            )
        artifact_type = "map" if output_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else "file"
        return tool_result_ok(
            "export_artifact",
            inputs=step.validated_tool_args,
            outputs={"path": str(output_path), "source_path": str(source_path), "format": output_path.suffix.lower().lstrip(".")},
            artifacts=[
                {
                    "artifact_id": f"file:{output_path.name}",
                    "path": str(output_path),
                    "type": artifact_type,
                    "title": output_path.name,
                    "description": f"Exported artifact copied from {source_path.name}",
                    "quality_status": "ok",
                    "preview_available": artifact_type == "map",
                    "created_at": "",
                }
            ],
            summary=f"Exported artifact {source_path} to {output_path}.",
            next_actions=["Download or open the exported artifact."],
        ).to_dict()
    return tool_result_ok(
        "interpret_result",
        inputs=step.validated_tool_args,
        outputs={"referenced_step": step.validated_tool_args.get("referenced_step") or ""},
        summary="Workflow result is ready for structured interpretation.",
        next_actions=["Explain the generated outputs and artifacts to the user."],
    ).to_dict()


def _skip_remaining(steps: list[WorkflowStep], start_index: int, completed: dict[str, WorkflowStep]) -> None:
    for step in steps[start_index:]:
        if step.status == "pending":
            step.status = "skipped"
            step.tool_result = _error_result(
                step.tool_name or "workflow_step",
                step.validated_tool_args,
                "WORKFLOW_DEPENDENCY_FAILED",
                "This step was skipped because an earlier workflow step failed.",
            )
            completed[step.step_id] = step


def execute_workflow_plan(manager: Any, plan: dict[str, Any], context: ToolRuntimeContext | None = None) -> dict[str, Any]:
    steps = _workflow_steps(plan)
    if not steps:
        return {"executed": False, "ok": False, "raw_reply": "", "workflow_result": None, "executed_steps": [], "failed_step": ""}

    workflow_id = f"workflow_{uuid4().hex[:10]}"
    if context is not None and hasattr(manager, "set_runtime_scope"):
        manager.set_runtime_scope(context.current_user_id, context.current_session_id)
    tool_map = {tool.name: tool for tool in build_tools(manager, context=context)}
    completed: dict[str, WorkflowStep] = {}
    final_artifacts: list[dict[str, Any]] = []
    failed_step = ""
    executed_steps: list[str] = []

    for index, step in enumerate(steps):
        if not step.step_id:
            step.step_id = f"step_{index + 1}"
        missing_dependencies = [dep for dep in step.depends_on if dep not in completed or completed[dep].status != "success"]
        if missing_dependencies:
            step.status = "skipped"
            step.tool_result = _error_result(
                step.tool_name,
                step.validated_tool_args,
                "WORKFLOW_DEPENDENCY_FAILED",
                f"Step {step.step_id} was skipped because dependencies failed or were missing: {', '.join(missing_dependencies)}.",
            )
            completed[step.step_id] = step
            continue

        resolved_args = _resolve_placeholder(step.validated_tool_args, completed)
        step.validated_tool_args = resolved_args if isinstance(resolved_args, dict) else step.validated_tool_args
        executed_steps.append(step.step_id)

        preflight_error = None
        if step.tool_name in SUPPORTED_WORKFLOW_TOOLS or step.tool_name == "export_artifact":
            preflight_error = _validate_step_objects(manager, step)

        if preflight_error is not None:
            parsed = preflight_error
        elif step.tool_name in VIRTUAL_WORKFLOW_TOOLS:
            parsed = _virtual_result(step)
        elif step.tool_name not in SUPPORTED_WORKFLOW_TOOLS:
            parsed = _error_result(
                step.tool_name,
                step.validated_tool_args,
                "UNSUPPORTED_WORKFLOW_TOOL",
                f"Tool {step.tool_name} is not enabled for deterministic workflow execution.",
            )
        else:
            tool = tool_map.get(step.tool_name)
            if tool is None:
                parsed = _error_result(step.tool_name, step.validated_tool_args, "TOOL_NOT_REGISTERED", f"Tool {step.tool_name} is not registered.")
            else:
                try:
                    raw = tool.invoke(step.validated_tool_args)
                    parsed = parse_tool_result(raw)
                    if parsed is None:
                        parsed = _error_result(step.tool_name, step.validated_tool_args, "INVALID_TOOL_RESULT", f"Tool {step.tool_name} did not return ToolResult.", str(raw))
                except Exception as exc:
                    parsed = _error_result(step.tool_name, step.validated_tool_args, "TOOL_EXECUTION_EXCEPTION", f"Tool {step.tool_name} raised before returning ToolResult.", f"{type(exc).__name__}: {exc}")

        step.tool_result = parsed
        step.status = "success" if parsed.get("ok") else "failed"
        completed[step.step_id] = step
        artifacts = parsed.get("artifacts") if isinstance(parsed.get("artifacts"), list) else []
        final_artifacts.extend(artifact for artifact in artifacts if isinstance(artifact, dict))
        if step.status == "failed":
            failed_step = step.step_id
            if step.stop_on_failure:
                _skip_remaining(steps, index + 1, completed)
                break

    ok = not failed_step and all(step.status in {"success", "skipped"} for step in steps)
    failed_result = _step_result_by_id(completed, failed_step) if failed_step else {}
    result = WorkflowResult(
        ok=ok,
        workflow_id=workflow_id,
        steps=[step.to_dict() for step in steps],
        final_artifacts=final_artifacts,
        final_summary="Workflow completed successfully." if ok else f"Workflow stopped at step {failed_step}.",
        failed_step=failed_step,
        diagnostics={"executed_steps": executed_steps, "tool_count": len([step for step in steps if step.tool_name not in VIRTUAL_WORKFLOW_TOOLS])},
        next_actions=[str(item) for item in failed_result.get("next_actions", []) if str(item).strip()]
        if failed_step
        else ["Review the generated artifacts and continue with interpretation or downstream GIS processing."],
    )
    return {
        "executed": True,
        "ok": result.ok,
        "raw_reply": result.to_json(),
        "workflow_result": result.to_dict(),
        "executed_steps": executed_steps,
        "failed_step": failed_step,
    }
