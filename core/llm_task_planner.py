from __future__ import annotations

import json
import os
from typing import Any, Mapping

from core.llm_config import load_llm_provider_config, validate_llm_config
from core.response_language import enforce_user_text_language, localized_text, normalize_response_language
from core.task_plan_schema import validate_llm_task_plan


MIN_ACTIVE_PLAN_CONFIDENCE = 0.65


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _active_dataset(context: dict[str, Any]) -> dict[str, Any]:
    active = context.get("active_dataset")
    if isinstance(active, dict) and active.get("name"):
        return active
    for item in context.get("available_datasets") or []:
        if isinstance(item, dict) and item.get("name"):
            return item
    return {}


def _candidate_tool_names(context: dict[str, Any], defaults: list[str]) -> list[str]:
    names = [
        str(item.get("tool_name"))
        for item in context.get("candidate_tool_cards") or []
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    ]
    for name in defaults:
        if name not in names:
            names.append(name)
    return names


def _context_tool_names(context: dict[str, Any]) -> set[str]:
    return {
        str(item.get("tool_name"))
        for item in context.get("candidate_tool_cards") or []
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    }


class _E2ELLMFixtureClient:
    """Explicit opt-in fake Planner/Coordinator for real-backend E2E tests only."""

    def plan_task(self, prompt: str, context: dict[str, Any], deterministic_plan: dict[str, Any]) -> dict[str, Any]:
        text = str(prompt or "").lower()
        active = _active_dataset(context)
        dataset = str(active.get("name") or "dataset")
        dataset_type = str(active.get("type") or "").lower()
        fields = [str(item) for item in context.get("available_fields") or [] if str(item or "").strip()]
        source = "current_upload"
        if "plot" in text or "map" in text or "制图" in text or "地图" in text:
            if dataset_type == "table":
                candidate_tools = _candidate_tool_names(context, ["table_to_points", "plot_dataset"])
                return {
                    "primary_goal": "table_to_points_map",
                    "intent": "map_generation",
                    "operation": "map_workflow",
                    "input_assets": [{"role": "coordinate_table", "name": dataset, "source": source}],
                    "asset_roles": {dataset: "coordinate_table"},
                    "requested_downloads": [],
                    "study_area": "",
                    "time_range": {},
                    "spatial_resolution": "",
                    "candidate_tools": candidate_tools,
                    "selected_tools": ["table_to_points", "plot_dataset"],
                    "workflow_steps": [
                        {
                            "step_id": "make_points",
                            "tool_name": "table_to_points",
                            "args": {"dataset_name": dataset, "x_col": "lon", "y_col": "lat", "crs": "EPSG:4326", "output_name": f"{dataset}_points"},
                            "expected_outputs": ["point_layer"],
                        },
                        {
                            "step_id": "map",
                            "tool_name": "plot_dataset",
                            "args": {"dataset_name": "$steps.make_points.outputs.result_dataset", "column": "pop_density", "output_name": f"{dataset}_population_density_map.png"},
                            "depends_on": ["make_points"],
                            "expected_outputs": ["map_artifact"],
                        },
                    ],
                    "expected_outputs": ["point_layer", "map_artifact"],
                    "requires_confirmation": False,
                    "clarification_question": "",
                    "confidence": 0.9,
                    "source_attribution": {dataset: source},
                    "explicit_history_references": [],
                }
            candidate_tools = _candidate_tool_names(context, ["plot_dataset"])
            column = "pop_density" if "pop_density" in fields else (fields[0] if fields else "")
            return {
                "primary_goal": "vector_map",
                "intent": "map_generation",
                "operation": "map_workflow",
                "input_assets": [{"role": "vector_layer", "name": dataset, "source": source}],
                "asset_roles": {dataset: "vector_layer"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["plot_dataset"],
                "workflow_steps": [
                    {
                        "step_id": "map",
                        "tool_name": "plot_dataset",
                        "args": {"dataset_name": dataset, "column": column, "output_name": f"{dataset}_map.png"},
                        "expected_outputs": ["map_artifact"],
                    }
                ],
                "expected_outputs": ["map_artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {dataset: source},
                "explicit_history_references": [],
            }
        actual_tools = _context_tool_names(context)
        candidate_tools = _candidate_tool_names(context, ["describe_dataset"])
        if "describe_dataset" not in actual_tools and "plot_dataset" in actual_tools:
            column = "pop_density" if "pop_density" in fields else (fields[0] if fields else "")
            return {
                "primary_goal": "dataset_inspection_map",
                "intent": "inspection",
                "operation": "inspect_dataset",
                "input_assets": [{"role": "dataset", "name": dataset, "source": source}],
                "asset_roles": {dataset: "dataset"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["plot_dataset"],
                "workflow_steps": [
                    {
                        "step_id": "inspect_map",
                        "tool_name": "plot_dataset",
                        "args": {"dataset_name": dataset, "column": column, "output_name": f"{dataset}_inspection_map.png"},
                        "expected_outputs": ["map_artifact"],
                    }
                ],
                "expected_outputs": ["map_artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {dataset: source},
                "explicit_history_references": [],
            }
        return {
            "primary_goal": "dataset_inspection",
            "intent": "inspection",
            "operation": "inspect_dataset",
            "input_assets": [{"role": "dataset", "name": dataset, "source": source}],
            "asset_roles": {dataset: "dataset"},
            "requested_downloads": [],
            "study_area": "",
            "time_range": {},
            "spatial_resolution": "",
            "candidate_tools": candidate_tools,
            "selected_tools": ["describe_dataset"],
            "workflow_steps": [
                {"step_id": "describe", "tool_name": "describe_dataset", "args": {"dataset_name": dataset}, "expected_outputs": ["dataset_summary"]}
            ],
            "expected_outputs": ["dataset_summary"],
            "requires_confirmation": False,
            "clarification_question": "",
            "confidence": 0.9,
            "source_attribution": {dataset: source},
            "explicit_history_references": [],
        }

    def invoke(self, messages: Any) -> str:
        raw = messages[-1][1] if isinstance(messages, list) and messages else messages
        payload = json.loads(raw) if isinstance(raw, str) else raw
        remaining = payload.get("remaining_steps") if isinstance(payload, dict) else []
        current = payload.get("current_step") if isinstance(payload, dict) else {}
        if remaining and isinstance(current, dict) and current.get("step_id"):
            return json.dumps(
                {
                    "decision": "continue",
                    "next_step_id": current.get("step_id"),
                    "selected_next_action": "",
                    "required_tool": current.get("tool_name"),
                    "required_inputs": current.get("validated_tool_args") or current.get("args") or {},
                    "reason": "Run the next validated fixture step.",
                    "user_question": "",
                    "confidence": 0.9,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "decision": "stop_success",
                "next_step_id": "",
                "selected_next_action": "",
                "required_tool": "",
                "required_inputs": {},
                "reason": "All fixture steps completed.",
                "user_question": "",
                "confidence": 0.9,
            },
            ensure_ascii=False,
        )


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "content"):
        raw = getattr(raw, "content")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _call_client(client: Any, prompt: str, context: dict[str, Any], deterministic_plan: dict[str, Any]) -> Any:
    payload = {
        "instruction": "Return one JSON TaskPlan only. Plan tools, but do not claim that any tool has executed.",
        "response_language": normalize_response_language(context.get("response_language"), prompt),
        "prompt": prompt,
        "context": {
            "agent_policy": context.get("agent_policy"),
            "active_dataset": context.get("active_dataset"),
            "available_asset_profiles": context.get("available_asset_profiles"),
            "available_fields": context.get("available_fields"),
            "context_sources": context.get("context_sources"),
            "knowledge_snippets": context.get("knowledge_snippets"),
            "candidate_tool_cards": context.get("candidate_tool_cards"),
            "download_candidates": context.get("download_candidates"),
            "area_candidates": context.get("area_candidates"),
        },
        "existing_deterministic_plan": deterministic_plan,
        "schema": {
            "task_type": "string",
            "goal": "string",
            "selected_assets": "array of {role,name,evidence}",
            "tools_read": "array of tool_name strings",
            "planned_steps": "array of {step_id, tool_name, args}",
            "requires_confirmation": "boolean",
            "clarification_question": "string",
            "assumptions": "array",
            "expected_outputs": "array",
            "forbidden_tools": "array",
            "explanation": "string",
            "phase2_required_fields": [
                "primary_goal",
                "intent",
                "operation",
                "input_assets",
                "asset_roles",
                "requested_downloads",
                "download_requests",
                "study_area",
                "time_range",
                "spatial_resolution",
                "candidate_tools",
                "selected_tools",
                "workflow_steps",
                "expected_outputs",
                "requires_confirmation",
                "clarification_question",
                "confidence",
                "source_attribution",
            "explicit_history_references",
            "response_language",
            ],
            "download_request_fields": [
                "area_asset_id",
                "area_source",
                "product_id",
                "requested_resolution",
                "resolved_resolution",
                "time_range",
                "download_parameters",
                "source_attribution",
                "expected_outputs",
                "requires_confirmation",
            ],
        },
    }
    plan_task = getattr(type(client), "plan_task", None)
    if callable(plan_task):
        return plan_task(client, prompt, context, deterministic_plan)
    invoke = getattr(client, "invoke", None)
    if callable(invoke):
        language = payload["response_language"]
        return invoke(
            [
                (
                    "system",
                    "You are a GIS LLM-first task planner. You only produce plans; tools execute later after validation. "
                    f"Set response_language={language}. User-facing clarification_question must use that language.",
                ),
                ("user", json.dumps(payload, ensure_ascii=False, default=str)),
            ]
        )
    if callable(client):
        return client(prompt, context, deterministic_plan)
    return None


def _blocked_plan(reason: str, message: str, *, errors: list[dict[str, Any]] | None = None, response_language: str = "en-US") -> dict[str, Any]:
    return {
        "task_type": "unclear_request",
        "required_inputs": [],
        "missing_inputs": [reason],
        "recommended_tools": [],
        "tool_preconditions": {},
        "execution_steps": [],
        "expected_outputs": [],
        "should_ask_clarification": True,
        "clarification_question": message,
        "resolved_fields": {},
        "resolved_objects": {},
        "slots": {},
        "tool_plan": [],
        "validated_tool_args": {},
        "workflow_plan": [],
        "slot_validation_errors": errors or [],
        "semantic_parse": {},
        "download_plan": {},
        "requested_downloads": [],
        "requires_confirmation": False,
        "response_language": response_language,
    }


def build_llm_task_plan(
    prompt: str,
    context: dict[str, Any],
    *,
    client: Any | None = None,
    min_confidence: float = MIN_ACTIVE_PLAN_CONFIDENCE,
) -> dict[str, Any]:
    planner_source = "injected_client" if client is not None else "default_llm"
    response_language = normalize_response_language(context.get("response_language"), prompt)
    context = {**context, "response_language": response_language}
    if client is None:
        client = build_default_llm_task_planner_client()
    if client is None:
        return {
            "status": "unavailable",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": "llm_planner_client_unavailable",
            "plan": _blocked_plan(
                "llm_planner_unavailable",
                localized_text("planner_unavailable", response_language),
                response_language=response_language,
            ),
        }

    try:
        raw = _call_client(client, prompt, context, {})
    except Exception as exc:
        return {
            "status": "error",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": type(exc).__name__,
            "plan": _blocked_plan(
                "llm_planner_error",
                localized_text("planner_error", response_language),
                response_language=response_language,
            ),
        }

    payload = _parse_payload(raw)
    if payload is None:
        return {
            "status": "invalid_json",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "plan": _blocked_plan(
                "invalid_llm_output",
                localized_text("invalid_llm_output", response_language),
                response_language=response_language,
            ),
        }

    validation = validate_llm_task_plan(payload, context)
    if not validation.get("ok"):
        errors = validation.get("errors", [])
        return {
            "status": "invalid_plan",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "errors": errors,
            "fallback_plan": validation.get("fallback_plan"),
            "plan": validation.get("fallback_plan")
            or _blocked_plan(
                "invalid_llm_plan",
                localized_text("invalid_llm_plan", response_language),
                errors=errors,
                response_language=response_language,
            ),
        }

    plan = validation["plan"]
    confidence = float(plan.get("confidence") or 0.0)
    if confidence < min_confidence:
        low_confidence_plan = {**plan}
        low_confidence_plan["workflow_plan"] = []
        low_confidence_plan["tool_plan"] = []
        low_confidence_plan["validated_tool_args"] = {}
        low_confidence_plan["should_ask_clarification"] = True
        low_confidence_plan["clarification_question"] = enforce_user_text_language(
            low_confidence_plan.get("clarification_question") or localized_text("low_confidence", response_language),
            response_language,
            "low_confidence",
        )
        low_confidence_plan["response_language"] = response_language
        low_confidence_plan["slot_validation_errors"] = [
            _error
            for _error in low_confidence_plan.get("slot_validation_errors", [])
            if isinstance(_error, dict)
        ] + [{"code": "LLM_PLAN_LOW_CONFIDENCE", "message": "LLM plan confidence is below the execution threshold.", "confidence": confidence}]
        return {
            "status": "low_confidence",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "plan": low_confidence_plan,
        }

    return {
        "status": "ready",
        "mode": "active",
        "planner_source": planner_source,
        "executes_tools": False,
        "plan": plan,
    }


def build_default_llm_task_planner_client(*, chat_model_cls: Any | None = None, env: Mapping[str, str] | None = None) -> Any | None:
    source = env or os.environ
    if _truthy(source.get("GIS_AGENT_E2E_LLM_FIXTURES")):
        return _E2ELLMFixtureClient()
    config = load_llm_provider_config(env)
    validation = validate_llm_config(config)
    if validation.get("status") == "invalid" or config.provider == "fake" or not config.api_key_present:
        return None

    model_cls = chat_model_cls
    if model_cls is None:
        try:
            from langchain_openai import ChatOpenAI
        except Exception:
            return None
        model_cls = ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": config.model,
        "api_key": str((env or os.environ).get(config.api_key_env) or ""),
        "temperature": 0,
        "timeout": config.timeout,
        "max_retries": config.max_retries,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    try:
        return model_cls(**kwargs)
    except Exception:
        return None


def build_shadow_llm_task_plan(
    prompt: str,
    context: dict[str, Any],
    deterministic_plan: dict[str, Any],
    *,
    client: Any | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    if enabled is None:
        enabled = _truthy(os.getenv("GIS_AGENT_ENABLE_LLM_PLANNER_SHADOW"))
    if not enabled:
        return {"status": "disabled", "mode": "shadow", "planner_source": "disabled", "executes_tools": False}
    planner_source = "injected_client" if client is not None else "default_llm"
    if client is None:
        client = build_default_llm_task_planner_client()
    if client is None:
        return {
            "status": "unavailable",
            "mode": "shadow",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": "llm_planner_client_unavailable",
        }

    try:
        raw = _call_client(client, prompt, context, deterministic_plan)
    except Exception as exc:
        return {
            "status": "error",
            "mode": "shadow",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": type(exc).__name__,
        }

    payload = _parse_payload(raw)
    if payload is None:
        return {"status": "invalid_json", "mode": "shadow", "planner_source": planner_source, "executes_tools": False}

    validation = validate_llm_task_plan(payload, context)
    if not validation.get("ok"):
        return {
            "status": "invalid_plan",
            "mode": "shadow",
            "planner_source": planner_source,
            "executes_tools": False,
            "errors": validation.get("errors", []),
            "fallback_plan": validation.get("fallback_plan"),
        }
    return {
        "status": "ready",
        "mode": "shadow",
        "planner_source": planner_source,
        "executes_tools": False,
        "plan": validation["plan"],
    }
