from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any, limit: int = 160) -> str:
    return str(value or "").strip()[:limit]


def _plan_steps(plan: dict[str, Any]) -> list[Any]:
    steps = plan.get("planned_steps")
    if not isinstance(steps, list):
        steps = plan.get("workflow_plan")
    if not isinstance(steps, list):
        steps = plan.get("tool_plan")
    return steps if isinstance(steps, list) else []


def _planned_tools(plan: dict[str, Any]) -> list[str]:
    tools: list[str] = []
    for step in _plan_steps(plan):
        if not isinstance(step, dict):
            continue
        name = _clean_text(step.get("tool_name") or step.get("tool") or step.get("name"), 120)
        if name:
            tools.append(name)
    return tools


def runtime_planner_input_schema(
    prompt: str,
    context: dict[str, Any],
    deterministic_plan: dict[str, Any],
    *,
    runtime_enabled: bool,
    runtime_mode: str,
) -> dict[str, Any]:
    context_dict = _as_dict(context)
    intent = _as_dict(context_dict.get("intent"))
    rag_trace = _as_dict(context_dict.get("rag_trace"))
    return {
        "schema_version": "runtime-planner-input/v1",
        "runtime_enabled": bool(runtime_enabled),
        "runtime_mode": _clean_text(runtime_mode, 40),
        "prompt_length": len(str(prompt or "")),
        "context_keys": sorted(str(key) for key in context_dict.keys()),
        "task_type": _clean_text(_as_dict(deterministic_plan).get("task_type") or intent.get("intent"), 80),
        "deterministic_step_count": len(_plan_steps(_as_dict(deterministic_plan))),
        "tool_metadata_count": len(_as_list(context_dict.get("runtime_tool_metadata"))),
        "knowledge_snippet_count": len(_as_list(context_dict.get("knowledge_snippets"))),
        "rag": {
            "vector_rag_status": _clean_text(rag_trace.get("vector_rag_status"), 80),
            "full_vector_rag": bool(rag_trace.get("full_vector_rag")),
            "vector_hit_count": int(rag_trace.get("vector_hit_count") or 0),
        },
    }


def runtime_planner_output_schema(result: dict[str, Any]) -> dict[str, Any]:
    result_dict = _as_dict(result)
    plan = _as_dict(result_dict.get("plan"))
    steps = _plan_steps(result_dict) or _plan_steps(plan)
    return {
        "schema_version": "runtime-planner-output/v1",
        "status": _clean_text(result_dict.get("status"), 80),
        "planner_source": _clean_text(result_dict.get("planner_source"), 80),
        "task_type": _clean_text(result_dict.get("task_type") or plan.get("task_type"), 80),
        "step_count": len(steps),
        "planned_tools": _planned_tools(result_dict) or _planned_tools(plan),
        "requires_confirmation": bool(result_dict.get("requires_confirmation") if "requires_confirmation" in result_dict else plan.get("requires_confirmation")),
        "executes_tools": bool(result_dict.get("executes_tools", False)),
    }


def runtime_coordinator_input_schema(
    plan: dict[str, Any],
    current_step: dict[str, Any] | None,
    remaining_steps: list[dict[str, Any]],
    execution_trace: Any,
    user_request: str,
    *,
    tool_cards: list[dict[str, Any]] | None = None,
    knowledge_snippets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current = _as_dict(current_step)
    trace = _as_dict(execution_trace)
    return {
        "schema_version": "runtime-coordinator-input/v1",
        "request_length": len(str(user_request or "")),
        "plan_step_count": len(_plan_steps(_as_dict(plan))),
        "current_step_id": _clean_text(current.get("step_id") or current.get("id"), 80),
        "remaining_step_count": len(_as_list(remaining_steps)),
        "execution_result_count": len(_as_list(trace.get("results"))),
        "tool_card_count": len(_as_list(tool_cards)),
        "knowledge_snippet_count": len(_as_list(knowledge_snippets)),
    }


def runtime_coordinator_output_schema(result: dict[str, Any]) -> dict[str, Any]:
    result_dict = _as_dict(result)
    decision = result_dict.get("decision")
    return {
        "schema_version": "runtime-coordinator-output/v1",
        "status": _clean_text(result_dict.get("status"), 80),
        "decision": _clean_text(getattr(decision, "decision", "") or result_dict.get("decision"), 80),
        "next_step_id": _clean_text(getattr(decision, "next_step_id", "") or result_dict.get("next_step_id"), 80),
        "required_tool": _clean_text(getattr(decision, "required_tool", "") or result_dict.get("required_tool"), 120),
        "confidence": float(getattr(decision, "confidence", 0.0) or result_dict.get("confidence") or 0.0),
        "executes_tools": bool(result_dict.get("executes_tools", False)),
    }


def _latest_event(events: list[dict[str, Any]], event_name: str) -> dict[str, Any]:
    for item in reversed(events):
        if item.get("event") == event_name:
            return _as_dict(item.get("payload"))
    return {}


def _tool_prechecks_from_events(events: list[dict[str, Any]]) -> dict[str, int]:
    checks = [_as_dict(item.get("payload")) for item in events if item.get("event") == "tool_precheck"]
    failed = sum(1 for item in checks if not bool(item.get("ok")))
    return {
        "total": len(checks),
        "failed": failed,
        "passed": len(checks) - failed,
    }


def build_runtime_decision_trace(runtime: Any, *, rag_readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    events = runtime.trace_snapshot() if hasattr(runtime, "trace_snapshot") else []
    planner_active = _latest_event(events, "planner_active")
    planner_shadow = _latest_event(events, "planner_shadow")
    planner = planner_active.get("output") or planner_active or planner_shadow.get("output") or planner_shadow
    coordinator = _latest_event(events, "coordinator_diagnostic").get("output") or _latest_event(events, "coordinator_diagnostic")
    return {
        "schema_version": "runtime-decision-trace/v1",
        "runtime": {
            "enabled": bool(getattr(runtime, "enabled", False)),
            "mode": _clean_text(getattr(runtime, "mode", "legacy"), 40),
        },
        "executes_tools": False,
        "event_count": len(events),
        "planner": _as_dict(planner),
        "coordinator": _as_dict(coordinator),
        "tool_prechecks": _tool_prechecks_from_events(events),
        "tool_risk_summary": runtime.tool_risk_summary() if hasattr(runtime, "tool_risk_summary") else {},
        "rag_readiness": {
            "ready": bool(_as_dict(rag_readiness).get("ready")),
            "status": _clean_text(_as_dict(rag_readiness).get("status"), 80),
            "reasons": [str(item) for item in _as_list(_as_dict(rag_readiness).get("reasons"))],
        },
    }
