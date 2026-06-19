from __future__ import annotations

import json
from typing import Any

from .tools.registry import build_tools
from .tool_context import ToolRuntimeContext
from .tool_contracts import aggregate_tool_results, is_tool_result_success, parse_tool_result, tool_result_error


DEFAULT_DETERMINISTIC_TOOLS = {
    "describe_dataset",
    "plot_dataset",
    "vector_clip_by_vector",
    "table_to_points",
    "raster_zonal_stats",
    "extract_raster_values_to_points",
    "dem_terrain_derivatives",
    "raster_reproject",
    "export_dataset",
    "generic_xgboost_workflow",
    "submit_commercial_download_job",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _plan_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    steps = plan.get("tool_plan")
    if isinstance(steps, list) and steps:
        return [step for step in steps if isinstance(step, dict)]
    validated = plan.get("validated_tool_args")
    if isinstance(validated, dict):
        return [{"tool_name": name, "args": args} for name, args in validated.items() if isinstance(args, dict)]
    return []


def _failure_result(tool_name: str, inputs: dict[str, Any], *, code: str, message: str, detail: str = "") -> dict[str, Any]:
    return tool_result_error(
        tool_name,
        inputs=inputs,
        error_code=code,
        error_title="Tool execution failed",
        user_message=message,
        technical_detail=detail[:1000],
        next_actions=["Check the task plan inputs, then retry the tool after correcting the missing or invalid value."],
    ).to_dict()


def _aggregate_result(results: list[dict[str, Any]], executed_tools: list[str]) -> str:
    aggregate = aggregate_tool_results(results, tool_name="tool_executor")
    aggregate["inputs"] = {"executed_tools": executed_tools}
    aggregate["outputs"]["executed_tools"] = executed_tools
    if aggregate["status"] == "succeeded" and not aggregate.get("next_actions"):
        aggregate["next_actions"] = ["Review the outputs and continue with interpretation, mapping, or downstream processing."]
    return json.dumps(aggregate, ensure_ascii=False, indent=2, default=str)


def execute_validated_tool_plan(manager: Any, plan: dict[str, Any], *, allow_tools: set[str] | list[str] | tuple[str, ...] | None = None, context: ToolRuntimeContext | None = None) -> dict[str, Any]:
    allowed = set(allow_tools or DEFAULT_DETERMINISTIC_TOOLS)
    steps = _plan_steps(plan)
    validated_args = _as_dict(plan.get("validated_tool_args"))
    if context is not None and hasattr(manager, "set_runtime_scope"):
        manager.set_runtime_scope(context.current_user_id, context.current_session_id)
    tool_map = {tool.name: tool for tool in build_tools(manager, context=context)}

    tool_results: list[dict[str, Any]] = []
    executed_tools: list[str] = []
    skipped_tools: list[str] = []
    failed_tool = ""

    for step in steps:
        tool_name = str(step.get("tool_name") or "")
        if not tool_name:
            continue
        if tool_name not in allowed:
            skipped_tools.append(tool_name)
            continue
        args = validated_args.get(tool_name)
        if not isinstance(args, dict):
            args = step.get("args")
        if not isinstance(args, dict):
            skipped_tools.append(tool_name)
            continue

        executed_tools.append(tool_name)
        tool = tool_map.get(tool_name)
        if tool is None:
            parsed = _failure_result(
                tool_name,
                args,
                code="TOOL_NOT_REGISTERED",
                message=f"Tool {tool_name} is not registered in the current GIS tool registry.",
            )
        else:
            try:
                raw = tool.invoke(args)
                parsed = parse_tool_result(raw)
                if parsed is None:
                    parsed = _failure_result(
                        tool_name,
                        args,
                        code="INVALID_TOOL_RESULT",
                        message=f"Tool {tool_name} did not return a structured ToolResult.",
                        detail=str(raw),
                    )
            except Exception as exc:
                parsed = _failure_result(
                    tool_name,
                    args,
                    code="TOOL_EXECUTION_EXCEPTION",
                    message=f"Tool {tool_name} failed before returning a structured result.",
                    detail=f"{type(exc).__name__}: {exc}",
                )
        tool_results.append(parsed)
        if not is_tool_result_success(parsed):
            failed_tool = tool_name
            break

    if not executed_tools:
        return {
            "executed": False,
            "ok": False,
            "tool_results": [],
            "raw_reply": "",
            "executed_tools": [],
            "failed_tool": "",
            "skipped_tools": skipped_tools,
        }

    raw_reply = tool_results[0] if len(tool_results) == 1 else _aggregate_result(tool_results, executed_tools)
    if isinstance(raw_reply, dict):
        import json

        raw_reply_text = json.dumps(raw_reply, ensure_ascii=False, indent=2, default=str)
    else:
        raw_reply_text = raw_reply
    return {
        "executed": True,
        "ok": all(is_tool_result_success(item) for item in tool_results),
        "status": "succeeded" if all(is_tool_result_success(item) for item in tool_results) else str((next((item for item in tool_results if not is_tool_result_success(item)), {}) or {}).get("status") or "failed"),
        "success": all(is_tool_result_success(item) for item in tool_results),
        "tool_results": tool_results,
        "raw_reply": raw_reply_text,
        "executed_tools": executed_tools,
        "failed_tool": failed_tool,
        "skipped_tools": skipped_tools,
    }
