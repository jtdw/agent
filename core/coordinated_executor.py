from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from .execution_trace import build_execution_trace
from .plan_validator import DOWNLOAD_TOOLS, validate_task_plan_before_execution
from .tool_context import ToolRuntimeContext
from .tool_contracts import is_tool_result_success, normalize_tool_result
from .tool_cards import list_tool_cards
from .workflow_coordinator import build_coordinator_decision
from .workflow_executor import execute_single_workflow_step


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _decision_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return _as_dict(value)


def _plan_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    steps = _as_list(plan.get("workflow_plan"))
    if steps:
        return [step for step in steps if isinstance(step, dict)]
    tool_plan = _as_list(plan.get("tool_plan"))
    if tool_plan:
        out: list[dict[str, Any]] = []
        execution_step_names = [str(item).strip() for item in _as_list(plan.get("execution_steps"))]
        used_step_ids: set[str] = set()
        for index, step in enumerate(tool_plan):
            if not isinstance(step, dict):
                continue
            tool_name = str(step.get("tool_name") or "")
            args = step.get("args")
            if not isinstance(args, dict):
                args = _as_dict(_as_dict(plan.get("validated_tool_args")).get(tool_name))
            step_id = str(step.get("step_id") or "").strip()
            if not step_id and index < len(execution_step_names):
                candidate_step_id = execution_step_names[index]
                if candidate_step_id not in used_step_ids and all(ch.isalnum() or ch in {"_", "-"} for ch in candidate_step_id):
                    step_id = candidate_step_id
            if not step_id:
                step_id = tool_name or f"step_{index + 1}"
            used_step_ids.add(step_id)
            out.append(
                {
                    "step_id": step_id,
                    "tool_name": tool_name,
                    "validated_tool_args": args if isinstance(args, dict) else {},
                    "depends_on": _as_list(step.get("depends_on")),
                }
            )
        return out
    return [
        {"step_id": name, "tool_name": name, "validated_tool_args": args, "depends_on": []}
        for name, args in _as_dict(plan.get("validated_tool_args")).items()
        if isinstance(args, dict)
    ]


def _step_id(step: dict[str, Any], index: int) -> str:
    return str(step.get("step_id") or step.get("id") or f"step_{index + 1}")


def _step_index(steps: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {_step_id(step, index): {**step, "step_id": _step_id(step, index)} for index, step in enumerate(steps)}


def _allowed_tools(plan: dict[str, Any], steps: list[dict[str, Any]]) -> set[str]:
    names = {str(name) for name in _as_list(plan.get("selected_tools")) + _as_list(plan.get("candidate_tools")) if str(name).strip()}
    names.update(str(step.get("tool_name") or "") for step in steps if str(step.get("tool_name") or "").strip())
    return names


def _is_download_tool(tool_name: str) -> bool:
    lower = tool_name.lower()
    return tool_name in DOWNLOAD_TOOLS or "download" in lower or "gscloud" in lower


def _requested_downloads(plan: dict[str, Any]) -> list[Any]:
    return _as_list(plan.get("requested_downloads")) or _as_list(_as_dict(plan.get("download_plan")).get("requested_downloads"))


def _context_cards(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(context.get("candidate_tool_cards")) if isinstance(item, dict)]


def _card_tool_name(card: dict[str, Any]) -> str:
    return str(card.get("tool_name") or card.get("name") or "").strip()


def _coordinator_tool_cards(context: dict[str, Any], steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = [dict(card) for card in _context_cards(context)]
    present = {_card_tool_name(card) for card in cards if _card_tool_name(card)}
    planned_names = [str(step.get("tool_name") or "").strip() for step in steps if str(step.get("tool_name") or "").strip()]
    missing = [name for name in dict.fromkeys(planned_names) if name not in present]
    if not missing:
        return cards
    builtin_cards = {_card_tool_name(card): card for card in list_tool_cards() if _card_tool_name(card)}
    for name in missing:
        card = dict(builtin_cards.get(name) or {"tool_name": name, "name": name, "capability": "Validated planned GIS tool."})
        card.setdefault("name", name)
        card.setdefault("tool_name", name)
        cards.append(card)
    return cards


def _knowledge(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _as_list(context.get("knowledge_snippets")) if isinstance(item, dict)]


def _completed_results(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("step_id") or ""): item for item in results if str(item.get("step_id") or "").strip()}


def _make_return(
    *,
    plan: dict[str, Any],
    plan_id: str,
    start_monotonic: float,
    started_at: str,
    results: list[dict[str, Any]],
    retry_counts: dict[str, int],
    decisions: list[dict[str, Any]],
    final_decision: dict[str, Any],
    status: str,
    blocked_reason: str = "",
    budget: dict[str, Any],
) -> dict[str, Any]:
    elapsed_ms = int((time.monotonic() - start_monotonic) * 1000)
    trace = build_execution_trace(plan, {"tool_results": results}, plan_id=plan_id, retry_counts=retry_counts, started_at=started_at, elapsed_ms=elapsed_ms)
    executed_tools = [str(item.get("tool_name") or "") for item in results if str(item.get("tool_name") or "").strip()]
    if status == "succeeded":
        ok = True
    elif status in {"awaiting_confirmation", "blocked", "failed"}:
        ok = False
    else:
        ok = all(is_tool_result_success(item) for item in results) if results else False
    return {
        "executed": bool(results),
        "ok": ok,
        "success": ok,
        "status": status,
        "raw_reply": "",
        "tool_results": results,
        "normalized_results": [item.model_dump(mode="json") for item in trace.results],
        "execution_trace": trace.model_dump(mode="json"),
        "final_decision": final_decision,
        "coordinator_decisions": decisions,
        "coordinator_budget": budget,
        "blocked_reason": blocked_reason,
        "executed_tools": executed_tools,
    }


def _single_step_plan(plan: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(step.get("tool_name") or "")
    single = dict(plan)
    single["workflow_plan"] = [step]
    single["tool_plan"] = []
    single["validated_tool_args"] = {tool_name: _as_dict(step.get("validated_tool_args") or step.get("args"))}
    single["selected_tools"] = [tool_name]
    single["candidate_tools"] = list(dict.fromkeys([tool_name, *[str(name) for name in _as_list(plan.get("candidate_tools")) if str(name).strip()]]))
    return single


def run_coordinated_execution(
    manager: Any,
    plan: dict[str, Any],
    context: dict[str, Any],
    user_request: str,
    *,
    runtime_context: ToolRuntimeContext | None = None,
    coordinator_client: Any = None,
    max_steps: int | None = None,
    max_tool_retries: int | None = None,
    max_elapsed_seconds: int | None = None,
) -> dict[str, Any]:
    steps = _plan_steps(plan)
    if not steps:
        return {
            "executed": False,
            "ok": False,
            "success": False,
            "status": "blocked",
            "raw_reply": "",
            "tool_results": [],
            "normalized_results": [],
            "execution_trace": build_execution_trace(plan, {}).model_dump(mode="json"),
            "final_decision": {},
            "coordinator_decisions": [],
            "coordinator_budget": {},
            "blocked_reason": "NO_EXECUTABLE_STEPS",
            "executed_tools": [],
        }
    plan = {**plan, "workflow_plan": steps, "tool_plan": []}

    plan_id = str(plan.get("plan_id") or f"plan_{uuid4().hex[:10]}")
    plan["plan_id"] = plan_id
    step_by_id = _step_index(steps)
    allowed_tools = _allowed_tools(plan, steps)
    planned_count = len(steps)
    max_steps = int(max_steps or os.getenv("GIS_COORDINATOR_MAX_STEPS") or min(12, max(1, 2 * planned_count)))
    max_tool_retries = int(max_tool_retries if max_tool_retries is not None else os.getenv("GIS_COORDINATOR_MAX_TOOL_RETRIES") or 1)
    max_elapsed_seconds = int(max_elapsed_seconds or os.getenv("GIS_COORDINATOR_MAX_SECONDS") or 300)
    budget = {"max_steps": max_steps, "max_tool_retries": max_tool_retries, "max_elapsed_seconds": max_elapsed_seconds}
    started_at = datetime.now().isoformat(timespec="seconds")
    start_monotonic = time.monotonic()
    results: list[dict[str, Any]] = []
    retry_counts: dict[str, int] = {}
    decisions: list[dict[str, Any]] = []
    last_signature = ""
    repeated_signatures = 0

    for _iteration in range(max_steps):
        if time.monotonic() - start_monotonic > max_elapsed_seconds:
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision={},
                status="failed",
                blocked_reason="COORDINATOR_TIME_BUDGET_EXCEEDED",
                budget=budget,
            )

        trace = build_execution_trace(
            plan,
            {"tool_results": results},
            plan_id=plan_id,
            retry_counts=retry_counts,
            started_at=started_at,
            elapsed_ms=int((time.monotonic() - start_monotonic) * 1000),
        )
        remaining_steps = [step_by_id[step_id] for step_id in trace.remaining_step_ids if step_id in step_by_id]
        current_step = remaining_steps[0] if remaining_steps else None
        decision_result = build_coordinator_decision(
            plan,
            current_step,
            remaining_steps,
            trace,
            user_request,
            tool_cards=_coordinator_tool_cards(context, steps),
            knowledge_snippets=_knowledge(context),
            client=coordinator_client,
        )
        decision = _decision_dict(decision_result.get("decision"))
        decisions.append({"status": decision_result.get("status"), "decision": decision, "error": decision_result.get("error")})
        signature = f"{decision.get('decision')}|{decision.get('next_step_id')}|{decision.get('required_tool')}"
        repeated_signatures = repeated_signatures + 1 if signature and signature == last_signature else 0
        last_signature = signature

        if decision_result.get("status") != "ready" and not remaining_steps and results and all(is_tool_result_success(item) for item in results):
            final_decision = {
                **decision,
                "decision": "stop_success",
                "reason": str(decision.get("reason") or "All planned steps completed successfully."),
            }
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=final_decision,
                status="succeeded",
                budget=budget,
            )
        if decision_result.get("status") != "ready":
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="failed",
                blocked_reason=str(decision_result.get("status") or "COORDINATOR_UNAVAILABLE").upper(),
                budget=budget,
            )
        if repeated_signatures >= 2:
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="failed",
                blocked_reason="COORDINATOR_REPEATED_DECISION",
                budget=budget,
            )

        action = str(decision.get("decision") or "")
        if action == "stop_success":
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="succeeded",
                budget=budget,
            )
        if action == "request_confirmation":
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="awaiting_confirmation",
                blocked_reason="COORDINATOR_REQUESTED_CONFIRMATION",
                budget=budget,
            )
        if action == "request_clarification":
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason="COORDINATOR_REQUESTED_CLARIFICATION",
                budget=budget,
            )
        if action == "stop_failure":
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="failed",
                blocked_reason=str(decision.get("reason") or "COORDINATOR_STOP_FAILURE"),
                budget=budget,
            )
        if action != "continue":
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="failed",
                blocked_reason="COORDINATOR_UNKNOWN_DECISION",
                budget=budget,
            )

        next_step_id = str(decision.get("next_step_id") or "")
        if not remaining_steps and results and all(is_tool_result_success(item) for item in results):
            final_decision = {
                **decision,
                "decision": "stop_success",
                "reason": str(decision.get("reason") or "All planned steps completed successfully."),
            }
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=final_decision,
                status="succeeded",
                budget=budget,
            )
        if not next_step_id:
            required_tool_for_step = str(decision.get("required_tool") or "")
            matching_steps = [
                step
                for step in remaining_steps
                if required_tool_for_step and str(step.get("tool_name") or "") == required_tool_for_step
            ]
            if len(matching_steps) == 1:
                next_step_id = str(matching_steps[0].get("step_id") or "")
                decision["next_step_id"] = next_step_id
        step = step_by_id.get(next_step_id)
        if step and retry_counts.get(next_step_id, 0) >= max_tool_retries:
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="failed",
                blocked_reason="STEP_RETRY_LIMIT_EXCEEDED",
                budget=budget,
            )
        if not step or next_step_id not in trace.remaining_step_ids:
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason="STEP_NOT_IN_REMAINING_PLAN",
                budget=budget,
            )
        tool_name = str(step.get("tool_name") or "")
        required_tool = str(decision.get("required_tool") or "")
        if not required_tool:
            decision["required_tool"] = tool_name
            required_tool = tool_name
        if required_tool != tool_name:
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason="TOOL_STEP_MISMATCH",
                budget=budget,
            )
        if tool_name not in allowed_tools:
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason="TOOL_NOT_ALLOWED_BY_PLAN",
                budget=budget,
            )
        if _is_download_tool(tool_name) and not _requested_downloads(plan):
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason="DOWNLOAD_STEP_WITHOUT_REQUESTED_DOWNLOADS",
                budget=budget,
            )
        dependencies = [str(dep) for dep in _as_list(step.get("depends_on")) if str(dep).strip()]
        successful_steps = {str(item.get("step_id") or "") for item in results if is_tool_result_success(item)}
        missing_dependencies = [dep for dep in dependencies if dep not in successful_steps]
        if missing_dependencies:
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason="WORKFLOW_DEPENDENCY_NOT_SATISFIED",
                budget=budget,
            )
        single_plan = _single_step_plan(plan, step)
        validation = validate_task_plan_before_execution(single_plan, context)
        if not validation.get("ok"):
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason=str((_as_list(validation.get("errors"))[0] or {}).get("code") if validation.get("errors") else "PLAN_VALIDATION_FAILED"),
                budget=budget,
            )

        execution = execute_single_workflow_step(
            manager,
            step,
            completed_results=_completed_results(results),
            context=runtime_context,
        )
        retry_counts[next_step_id] = retry_counts.get(next_step_id, 0) + 1
        tool_result = normalize_tool_result(execution.get("tool_result") if isinstance(execution, dict) else {})
        tool_result["step_id"] = next_step_id
        tool_result["tool_name"] = tool_name
        results.append(tool_result)
        result_status = str(tool_result.get("status") or "")
        if result_status == "awaiting_confirmation":
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="awaiting_confirmation",
                blocked_reason="TOOL_AWAITING_CONFIRMATION",
                budget=budget,
            )
        if result_status == "blocked" and not tool_result.get("next_actions"):
            return _make_return(
                plan=plan,
                plan_id=plan_id,
                start_monotonic=start_monotonic,
                started_at=started_at,
                results=results,
                retry_counts=retry_counts,
                decisions=decisions,
                final_decision=decision,
                status="blocked",
                blocked_reason=str(tool_result.get("error_code") or "TOOL_BLOCKED"),
                budget=budget,
            )

    return _make_return(
        plan=plan,
        plan_id=plan_id,
        start_monotonic=start_monotonic,
        started_at=started_at,
        results=results,
        retry_counts=retry_counts,
        decisions=decisions,
        final_decision=decisions[-1]["decision"] if decisions else {},
        status="failed",
        blocked_reason="COORDINATOR_STEP_LIMIT_EXCEEDED",
        budget=budget,
    )
