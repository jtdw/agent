from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.response_language import localized_text, normalize_response_language


CoordinatorDecisionValue = Literal["continue", "stop_success", "stop_failure", "request_clarification", "request_confirmation"]
MIN_COORDINATOR_CONFIDENCE = 0.65


class CoordinatorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: CoordinatorDecisionValue
    next_step_id: str = ""
    selected_next_action: str = ""
    required_tool: str = ""
    required_inputs: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    user_question: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    response_language: str = ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _decision(
    decision: CoordinatorDecisionValue,
    *,
    reason: str,
    user_question: str = "",
    confidence: float = 0.0,
    response_language: str = "",
) -> CoordinatorDecision:
    return CoordinatorDecision(
        decision=decision,
        next_step_id="",
        selected_next_action="",
        required_tool="",
        required_inputs={},
        reason=reason,
        user_question=user_question,
        confidence=confidence,
        response_language=response_language,
    )


def _safe_task_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": plan.get("plan_id") or "",
        "primary_goal": plan.get("primary_goal") or plan.get("task_type") or "",
        "intent": plan.get("intent") or plan.get("task_type") or "",
        "operation": plan.get("operation") or "",
        "requested_downloads": _as_list(plan.get("requested_downloads")),
        "selected_tools": _as_list(plan.get("selected_tools")),
        "candidate_tools": _as_list(plan.get("candidate_tools")),
    }


def _coordinator_payload(
    *,
    plan: dict[str, Any],
    current_step: dict[str, Any] | None,
    remaining_steps: list[dict[str, Any]],
    execution_trace: Any,
    user_request: str,
    tool_cards: list[dict[str, Any]] | None,
    knowledge_snippets: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    trace_payload = execution_trace.model_dump(mode="json") if hasattr(execution_trace, "model_dump") else _as_dict(execution_trace)
    return {
        "task_plan": _safe_task_plan(plan),
        "response_language": normalize_response_language(plan.get("response_language"), user_request),
        "current_step": current_step or {},
        "remaining_steps": remaining_steps,
        "execution_trace": trace_payload,
        "user_request": user_request,
        "tool_cards": tool_cards or [],
        "knowledge_snippets": knowledge_snippets or [],
        "decision_schema": CoordinatorDecision.model_json_schema(),
        "rules": [
            "Only select a remaining step from the validated TaskPlan.",
            "Only use fields from normalized ToolResult: status, errors, warnings, artifacts, outputs, next_actions, step_id, tool_name, input_asset_ids.",
            "Do not add downloads when requested_downloads is empty.",
            "Ask one concrete clarification or confirmation question when execution cannot continue safely.",
            "All user-facing reason and user_question text must use response_language.",
        ],
    }


def _invoke_client(client: Any, payload: dict[str, Any]) -> Any:
    if client is None:
        raise RuntimeError("coordinator client unavailable")
    if hasattr(client, "with_structured_output"):
        structured = client.with_structured_output(CoordinatorDecision)
        if hasattr(structured, "invoke"):
            return structured.invoke(payload)
        if callable(structured):
            return structured(payload)
    if hasattr(client, "invoke"):
        return client.invoke(
            [
                (
                    "system",
                    "You are a GIS Workflow Coordinator. Return only a CoordinatorDecision JSON object. "
                    "You may only choose validated remaining TaskPlan steps and must rely on normalized ToolResult facts. "
                    "Use the provided response_language for user-facing reason and user_question.",
                ),
                ("user", json.dumps(payload, ensure_ascii=False, default=str)),
            ]
        )
    if callable(client):
        return client(payload)
    raise RuntimeError("coordinator client is not callable")


def _parse_raw_decision(raw: Any) -> dict[str, Any]:
    if isinstance(raw, CoordinatorDecision):
        return raw.model_dump(mode="json")
    if isinstance(raw, dict):
        return raw
    content = getattr(raw, "content", raw)
    if isinstance(content, CoordinatorDecision):
        return content.model_dump(mode="json")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        return json.loads(content)
    raise TypeError(f"Unsupported coordinator decision type: {type(raw).__name__}")


def build_coordinator_decision(
    plan: dict[str, Any],
    current_step: dict[str, Any] | None,
    remaining_steps: list[dict[str, Any]],
    execution_trace: Any,
    user_request: str,
    *,
    tool_cards: list[dict[str, Any]] | None = None,
    knowledge_snippets: list[dict[str, Any]] | None = None,
    client: Any = None,
    min_confidence: float = MIN_COORDINATOR_CONFIDENCE,
) -> dict[str, Any]:
    if client is None:
        try:
            from .llm_task_planner import build_default_llm_task_planner_client

            client = build_default_llm_task_planner_client()
        except Exception:
            client = None
    payload = _coordinator_payload(
        plan=plan,
        current_step=current_step,
        remaining_steps=remaining_steps,
        execution_trace=execution_trace,
        user_request=user_request,
        tool_cards=tool_cards,
        knowledge_snippets=knowledge_snippets,
    )
    response_language = str(payload.get("response_language") or "")
    try:
        raw = _invoke_client(client, payload)
    except Exception as exc:
        return {
            "status": "unavailable",
            "decision": _decision(
                "stop_failure",
                reason=("LLM Workflow Coordinator is unavailable." if not response_language.startswith("zh") else "LLM 工作流协调器当前不可用。"),
                response_language=response_language,
            ),
            "error": f"{type(exc).__name__}: {exc}",
            "payload": payload,
        }
    try:
        decision = CoordinatorDecision.model_validate(_parse_raw_decision(raw))
    except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return {
            "status": "invalid_decision",
            "decision": _decision(
                "stop_failure",
                reason=("CoordinatorDecision failed schema validation." if not response_language.startswith("zh") else "CoordinatorDecision 未通过结构化校验。"),
                response_language=response_language,
            ),
            "error": f"{type(exc).__name__}: {exc}",
            "payload": payload,
        }
    if not decision.response_language:
        decision.response_language = response_language
    if decision.confidence < min_confidence:
        return {
            "status": "low_confidence",
            "decision": _decision(
                "stop_failure",
                reason=("CoordinatorDecision confidence is below execution threshold." if not response_language.startswith("zh") else "CoordinatorDecision 置信度低于执行阈值。"),
                response_language=response_language,
            ),
            "raw_decision": decision.model_dump(mode="json"),
            "payload": payload,
        }
    return {"status": "ready", "decision": decision, "payload": payload}
