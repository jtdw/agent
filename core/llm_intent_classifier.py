from __future__ import annotations

import json
import os
from typing import Any

from core.llm_config import load_llm_provider_config, validate_llm_config


ALLOWED_INTENTS = {
    "data_upload_analysis",
    "data_processing",
    "map_generation",
    "modeling",
    "result_analysis",
    "follow_up_question",
    "troubleshooting",
    "data_download",
    "general_gis_question",
    "unclear_request",
}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "fallback_reason": reason}


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value)


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "content"):
        raw = getattr(raw, "content")
    if isinstance(raw, str):
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
    return None


def _call_client(client: Any, prompt: str, conversation_state: Any, workspace_summary: Any) -> Any:
    if hasattr(client, "classify_intent"):
        return client.classify_intent(prompt, conversation_state, workspace_summary)
    if callable(client) and not hasattr(client, "invoke"):
        return client(prompt, conversation_state, workspace_summary)
    if hasattr(client, "invoke"):
        messages = [
            (
                "system",
                "You classify GIS assistant user intent. Return one JSON object only. "
                "Do not invent dataset fields, paths, map files, model metrics, or artifacts.",
            ),
            (
                "user",
                _safe_json(
                    {
                        "prompt": prompt,
                        "conversation_state": conversation_state,
                        "workspace_summary": workspace_summary,
                        "allowed_intents": sorted(ALLOWED_INTENTS),
                        "schema": {
                            "intent": "one allowed intent",
                            "confidence": "number 0-1",
                            "referenced_object": "object or null",
                            "missing_inputs": "array of strings",
                            "reasoning_summary": "short user-visible summary",
                            "should_ask_clarification": "boolean",
                            "secondary_intents": "array of allowed intents",
                        },
                    }
                ),
            ),
        ]
        return client.invoke(messages)
    return None


def _default_client() -> Any | None:
    validation = validate_llm_config()
    if validation.get("status") == "invalid":
        return None
    config = load_llm_provider_config()
    if config.provider == "fake":
        return None
    api_key = os.getenv(config.api_key_env, "") if config.api_key_env else ""
    if not api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except Exception:
        return None

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "model": os.getenv("ZAI_INTENT_MODEL") or config.model,
        "temperature": 0,
        "timeout": config.timeout,
        "max_retries": config.max_retries,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return ChatOpenAI(**kwargs)


def _reference_is_grounded(referenced_object: Any, conversation_state: Any, workspace_summary: Any) -> bool:
    if not referenced_object:
        return True
    if not isinstance(referenced_object, dict):
        return False
    serialized_context = _safe_json({"state": conversation_state, "workspace_summary": workspace_summary})
    for key in ("path", "name", "id", "label"):
        value = referenced_object.get(key)
        if value and str(value) not in serialized_context:
            return False
    return True


def _normalize_payload(payload: dict[str, Any], conversation_state: Any, workspace_summary: Any) -> dict[str, Any]:
    intent = str(payload.get("intent") or "")
    if intent not in ALLOWED_INTENTS:
        return _unavailable("llm_unknown_intent")

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    referenced_object = payload.get("referenced_object")
    if not _reference_is_grounded(referenced_object, conversation_state, workspace_summary):
        return _unavailable("llm_reference_not_in_context")

    missing_inputs = payload.get("missing_inputs")
    if not isinstance(missing_inputs, list):
        missing_inputs = []
    missing_inputs = [str(item) for item in missing_inputs if item]

    secondary = payload.get("secondary_intents")
    if not isinstance(secondary, list):
        secondary = []
    secondary_intents = [str(item) for item in secondary if str(item) in ALLOWED_INTENTS and str(item) != intent]

    reasoning = str(payload.get("reasoning_summary") or payload.get("reason") or "").strip()
    if len(reasoning) > 200:
        reasoning = reasoning[:197].rstrip() + "..."

    return {
        "available": True,
        "intent": intent,
        "confidence": confidence,
        "referenced_object": referenced_object if isinstance(referenced_object, dict) else None,
        "missing_inputs": missing_inputs,
        "reasoning_summary": reasoning,
        "should_ask_clarification": bool(payload.get("should_ask_clarification", False)),
        "secondary_intents": secondary_intents,
    }


def classify_intent_with_llm(
    prompt: str,
    conversation_state: Any,
    workspace_summary: Any,
    *,
    client: Any | None = None,
) -> dict[str, Any]:
    """Classify intent with an optional LLM client and a strict JSON contract."""
    selected_client = client or _default_client()
    if selected_client is None:
        return _unavailable("llm_unavailable")

    try:
        raw = _call_client(selected_client, prompt, conversation_state, workspace_summary)
    except Exception:
        return _unavailable("llm_call_failed")

    payload = _parse_payload(raw)
    if payload is None:
        return _unavailable("llm_invalid_json")

    return _normalize_payload(payload, conversation_state, workspace_summary)
