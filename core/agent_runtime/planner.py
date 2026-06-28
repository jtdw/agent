from __future__ import annotations

from typing import Any

from .decision_trace import (
    runtime_coordinator_input_schema,
    runtime_coordinator_output_schema,
    runtime_planner_input_schema,
    runtime_planner_output_schema,
)
from core.llm_task_planner import build_shadow_llm_task_plan
from core.workflow_coordinator import build_coordinator_decision


def _runtime_adapter_metadata(runtime: Any) -> dict[str, Any]:
    config = getattr(runtime, "config", None)
    cutover_guard_fn = getattr(config, "cutover_guard", None)
    cutover_guard = cutover_guard_fn() if callable(cutover_guard_fn) else {}
    return {
        "enabled": bool(getattr(runtime, "enabled", False)),
        "mode": str(getattr(runtime, "mode", "legacy") or "legacy"),
        "executes_tools": False,
        "cutover_guard": cutover_guard,
    }


def _runtime_planner_should_run(runtime: Any) -> bool:
    mode = str(getattr(runtime, "mode", "") or "")
    if mode == "shadow":
        return True
    if mode != "active":
        return False
    guard = _runtime_adapter_metadata(runtime).get("cutover_guard")
    if not isinstance(guard, dict):
        return False
    return bool(guard.get("active_effective"))


def _step_tool_name(step: Any) -> str:
    if not isinstance(step, dict):
        return ""
    return str(step.get("tool_name") or step.get("tool") or step.get("name") or "").strip()


def _plan_scoped_tool_metadata(
    runtime: Any,
    plan: dict[str, Any],
    current_step: dict[str, Any] | None,
    remaining_steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    all_cards = runtime.tool_metadata()
    desired_names: list[str] = []
    for step in [current_step, *remaining_steps]:
        name = _step_tool_name(step)
        if name and name not in desired_names:
            desired_names.append(name)
    for step in plan.get("planned_steps") or plan.get("workflow_plan") or []:
        name = _step_tool_name(step)
        if name and name not in desired_names:
            desired_names.append(name)
    if not desired_names:
        return all_cards
    by_name = {str(card.get("name") or ""): card for card in all_cards}
    scoped = [by_name[name] for name in desired_names if name in by_name]
    return scoped or all_cards


def _deterministic_plan_can_fallback(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    if plan.get("workflow_plan") or plan.get("tool_plan") or plan.get("validated_tool_args"):
        return True
    executable = plan.get("executable_workflow")
    if isinstance(executable, dict) and executable.get("status") == "ready" and executable.get("workflow_plan"):
        return True
    return bool(plan.get("requires_confirmation") and (plan.get("should_ask_clarification") or plan.get("clarification_question")))


def _promote_executable_workflow(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    workflow_plan = plan.get("workflow_plan")
    if isinstance(workflow_plan, list) and workflow_plan:
        return dict(plan)
    executable = plan.get("executable_workflow")
    if not isinstance(executable, dict) or executable.get("status") != "ready":
        return dict(plan)
    steps = executable.get("workflow_plan")
    if not isinstance(steps, list) or not steps:
        return dict(plan)
    promoted = dict(plan)
    promoted["workflow_plan"] = [dict(step) for step in steps if isinstance(step, dict)]
    validated_args: dict[str, Any] = {}
    tool_plan: list[dict[str, Any]] = []
    for step in promoted["workflow_plan"]:
        tool_name = _step_tool_name(step)
        args = step.get("validated_tool_args") if isinstance(step.get("validated_tool_args"), dict) else step.get("args")
        if tool_name and isinstance(args, dict):
            validated_args[tool_name] = dict(args)
            tool_plan.append({"tool_name": tool_name, "args": dict(args)})
    if validated_args and not promoted.get("validated_tool_args"):
        promoted["validated_tool_args"] = validated_args
    if tool_plan and not promoted.get("tool_plan"):
        promoted["tool_plan"] = tool_plan
    return promoted


def _plan_has_actions(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    return bool(plan.get("workflow_plan") or plan.get("tool_plan") or plan.get("validated_tool_args"))


def _plan_tool_names(plan: dict[str, Any]) -> list[str]:
    if not isinstance(plan, dict):
        return []
    names: list[str] = []
    for step in plan.get("workflow_plan") or []:
        name = _step_tool_name(step)
        if name and name not in names:
            names.append(name)
    for step in plan.get("tool_plan") or []:
        name = _step_tool_name(step)
        if name and name not in names:
            names.append(name)
    validated = plan.get("validated_tool_args")
    if isinstance(validated, dict):
        for name in validated:
            text = str(name or "").strip()
            if text and text not in names:
                names.append(text)
    return names


def _llm_skips_table_to_points_prerequisite(llm_plan: dict[str, Any], deterministic_plan: dict[str, Any]) -> bool:
    deterministic_tools = _plan_tool_names(_promote_executable_workflow(deterministic_plan))
    llm_tools = _plan_tool_names(llm_plan)
    if "table_to_points" not in deterministic_tools or "plot_dataset" not in deterministic_tools:
        return False
    if "plot_dataset" not in llm_tools or "table_to_points" in llm_tools:
        return False
    resolved = deterministic_plan.get("resolved_fields") if isinstance(deterministic_plan.get("resolved_fields"), dict) else {}
    return bool(resolved.get("map_field"))


def _plan_requests_user(plan: dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    return bool(plan.get("requires_confirmation") or plan.get("should_ask_clarification") or str(plan.get("clarification_question") or "").strip())


def _active_result_should_use_deterministic_fallback(result: dict[str, Any], deterministic_plan: dict[str, Any]) -> bool:
    if not _deterministic_plan_can_fallback(deterministic_plan):
        return False
    if result.get("status") != "ready":
        return True
    deterministic_fallback = _promote_executable_workflow(deterministic_plan)
    deterministic_has_actions = _plan_has_actions(deterministic_fallback)
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else result
    if _plan_has_actions(plan):
        if _llm_skips_table_to_points_prerequisite(plan, deterministic_fallback):
            return True
        return False
    if _plan_requests_user(plan):
        return deterministic_has_actions
    return True


def _step_id(step: Any) -> str:
    if not isinstance(step, dict):
        return ""
    return str(step.get("step_id") or step.get("id") or "").strip()


def _fill_missing_coordinator_required_tool(
    result: dict[str, Any],
    current_step: dict[str, Any] | None,
    remaining_steps: list[dict[str, Any]],
) -> None:
    if result.get("status") != "ready":
        return
    decision = result.get("decision")
    decision_value = str(getattr(decision, "decision", "") or (decision.get("decision") if isinstance(decision, dict) else "") or "").strip()
    required_tool = str(getattr(decision, "required_tool", "") or (decision.get("required_tool") if isinstance(decision, dict) else "") or "").strip()
    if decision_value != "continue" or required_tool:
        return
    next_step_id = str(getattr(decision, "next_step_id", "") or (decision.get("next_step_id") if isinstance(decision, dict) else "") or "").strip()
    candidates = [step for step in [current_step, *remaining_steps] if isinstance(step, dict)]
    selected = next((step for step in candidates if next_step_id and _step_id(step) == next_step_id), None)
    if selected is None and len(remaining_steps) == 1:
        selected = remaining_steps[0]
    tool_name = _step_tool_name(selected)
    if not tool_name:
        return
    if isinstance(decision, dict):
        decision["required_tool"] = tool_name
    else:
        try:
            decision.required_tool = tool_name
        except Exception:
            pass


class RuntimePlannerAdapter:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def diagnostics(self) -> dict[str, Any]:
        metadata = _runtime_adapter_metadata(self.runtime)
        return {
            **metadata,
            "planner_shadow_available": metadata["enabled"],
            "coordinator_diagnostic_available": metadata["enabled"],
        }

    def _disabled(self, *, mode: str) -> dict[str, Any]:
        return {
            "status": "disabled",
            "mode": mode,
            "planner_source": "runtime_disabled",
            "executes_tools": False,
            "runtime_adapter": _runtime_adapter_metadata(self.runtime),
        }

    def _context_for_adapter(self, context: dict[str, Any]) -> dict[str, Any]:
        if not bool(getattr(self.runtime, "enabled", False)):
            return dict(context)
        merged = self.runtime.merge_context(context)
        policy = merged.get("agent_policy") if isinstance(merged.get("agent_policy"), dict) else {}
        merged["agent_policy"] = {
            **policy,
            "runtime": merged.get("runtime", {}),
            "runtime_tool_metadata": merged.get("runtime_tool_metadata", []),
        }
        return merged

    def build_shadow_task_plan(
        self,
        prompt: str,
        context: dict[str, Any],
        deterministic_plan: dict[str, Any],
        *,
        client: Any | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        if not bool(getattr(self.runtime, "enabled", False)):
            return self._disabled(mode="shadow")
        merged_context = self._context_for_adapter(context)
        input_schema = runtime_planner_input_schema(
            prompt,
            merged_context,
            deterministic_plan,
            runtime_enabled=True,
            runtime_mode=str(getattr(self.runtime, "mode", "") or ""),
        )
        should_run = _runtime_planner_should_run(self.runtime) if enabled is None else enabled
        result = dict(
            build_shadow_llm_task_plan(
                prompt,
                merged_context,
                deterministic_plan,
                client=client,
                enabled=should_run,
            )
        )
        result["executes_tools"] = False
        result["runtime_adapter"] = _runtime_adapter_metadata(self.runtime)
        output_schema = runtime_planner_output_schema(result)
        self.runtime.record_trace_event(
            "planner_shadow",
            {
                "input": input_schema,
                "output": output_schema,
                "status": str(output_schema.get("status") or ""),
                "planner_source": str(output_schema.get("planner_source") or ""),
                "executes_tools": False,
            },
        )
        return result

    def build_active_task_plan(
        self,
        prompt: str,
        context: dict[str, Any],
        deterministic_plan: dict[str, Any],
        *,
        client: Any | None = None,
    ) -> dict[str, Any]:
        metadata = _runtime_adapter_metadata(self.runtime)
        if not bool(metadata.get("enabled")):
            return self._disabled(mode="active")
        if not _runtime_planner_should_run(self.runtime):
            return {
                "status": "disabled",
                "mode": "active",
                "planner_source": "active_cutover_blocked",
                "executes_tools": False,
                "runtime_adapter": metadata,
            }
        merged_context = self._context_for_adapter(context)
        input_schema = runtime_planner_input_schema(
            prompt,
            merged_context,
            deterministic_plan,
            runtime_enabled=True,
            runtime_mode="active",
        )
        result = dict(
            build_shadow_llm_task_plan(
                prompt,
                merged_context,
                deterministic_plan,
                client=client,
                enabled=True,
            )
        )
        if _active_result_should_use_deterministic_fallback(result, deterministic_plan):
            fallback_plan = _promote_executable_workflow(deterministic_plan)
            result = {
                "status": "ready",
                "mode": "active",
                "planner_source": "deterministic_fallback",
                "executes_tools": False,
                "plan": fallback_plan,
                "active_fallback": {
                    "llm_status": str(result.get("status") or ""),
                    "llm_planner_source": str(result.get("planner_source") or ""),
                    "reason": str(result.get("reason") or ""),
                },
            }
        result["mode"] = "active"
        result["planner_source"] = f"runtime_active:{result.get('planner_source') or 'unknown'}"
        result["executes_tools"] = False
        result["runtime_adapter"] = metadata
        output_schema = runtime_planner_output_schema(result)
        self.runtime.record_trace_event(
            "planner_active",
            {
                "input": input_schema,
                "output": output_schema,
                "status": str(output_schema.get("status") or ""),
                "planner_source": str(output_schema.get("planner_source") or ""),
                "executes_tools": False,
            },
        )
        return result

    def build_coordinator_decision_diagnostic(
        self,
        plan: dict[str, Any],
        current_step: dict[str, Any] | None,
        remaining_steps: list[dict[str, Any]],
        execution_trace: Any,
        user_request: str,
        *,
        tool_cards: list[dict[str, Any]] | None = None,
        knowledge_snippets: list[dict[str, Any]] | None = None,
        client: Any = None,
        min_confidence: float | None = None,
    ) -> dict[str, Any]:
        if not bool(getattr(self.runtime, "enabled", False)):
            return self._disabled(mode="coordinator_diagnostic")
        kwargs: dict[str, Any] = {
            "tool_cards": tool_cards
            if tool_cards is not None
            else _plan_scoped_tool_metadata(self.runtime, plan, current_step, remaining_steps),
            "knowledge_snippets": knowledge_snippets,
            "client": client,
        }
        if min_confidence is not None:
            kwargs["min_confidence"] = min_confidence
        input_schema = runtime_coordinator_input_schema(
            plan,
            current_step,
            remaining_steps,
            execution_trace,
            user_request,
            tool_cards=kwargs["tool_cards"],
            knowledge_snippets=knowledge_snippets,
        )
        result = dict(
            build_coordinator_decision(
                plan,
                current_step,
                remaining_steps,
                execution_trace,
                user_request,
                **kwargs,
            )
        )
        _fill_missing_coordinator_required_tool(result, current_step, remaining_steps)
        result["executes_tools"] = False
        result["runtime_adapter"] = _runtime_adapter_metadata(self.runtime)
        output_schema = runtime_coordinator_output_schema(result)
        self.runtime.record_trace_event(
            "coordinator_diagnostic",
            {
                "input": input_schema,
                "output": output_schema,
                "status": str(output_schema.get("status") or ""),
                "decision": str(output_schema.get("decision") or ""),
                "executes_tools": False,
            },
        )
        return result
