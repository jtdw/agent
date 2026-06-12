from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .conversation_state import ConversationState


ALLOWED_CONTEXT_KEYS = {
    "session_id",
    "active_dataset_id",
    "selected_artifact_id",
    "selected_artifact_type",
    "selected_artifact_path",
    "selected_layer_id",
    "selected_feature_id",
    "selected_feature_properties",
    "selected_map_bounds",
    "selected_model_result_id",
    "active_task_id",
    "last_visible_panel",
    "user_focus_hint",
}
SENSITIVE_KEY_PARTS = ("password", "token", "secret", "cookie", "authorization", "apikey", "api_key")
LARGE_KEY_PARTS = ("file", "content", "blob", "base64", "raw", "text", "html", "geojson", "geometry")
SENSITIVE_VALUE_RE = re.compile(r"(password|token|secret|cookie|authorization|api[_-]?key)\s*[:=]", re.IGNORECASE)
MAX_STRING_LENGTH = 200
MAX_FEATURE_PROPERTIES = 12
MAX_CONTEXT_JSON_LENGTH = 4096


def _is_blocked_key(key: str) -> bool:
    lower = str(key or "").lower()
    return any(part in lower for part in (*SENSITIVE_KEY_PARTS, *LARGE_KEY_PARTS))


def _clean_string(value: Any, max_length: int = MAX_STRING_LENGTH) -> str:
    text = str(value or "").strip()
    return text[:max_length]


def _looks_sensitive_value(value: Any) -> bool:
    text = str(value or "")
    return bool(SENSITIVE_VALUE_RE.search(text) or re.search(r"\bsk-[A-Za-z0-9_-]{8,}", text))


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _clean_string(value)
    return _clean_string(value)


def _sanitize_feature_properties(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    props: dict[str, Any] = {}
    for key, raw in value.items():
        clean_key = _clean_string(key, 80)
        if not clean_key or _is_blocked_key(clean_key):
            continue
        if isinstance(raw, (dict, list, tuple, set)):
            continue
        props[clean_key] = _scalar(raw)
        if len(props) >= MAX_FEATURE_PROPERTIES:
            break
    while props and len(json.dumps(props, ensure_ascii=False, default=str)) > MAX_CONTEXT_JSON_LENGTH:
        props.pop(next(reversed(props)))
    return props


def _sanitize_bounds(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        bounds = [float(item) for item in value]
    except Exception:
        return None
    minx, miny, maxx, maxy = bounds
    if minx >= maxx or miny >= maxy:
        return None
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        return None
    return bounds


def _sanitize_artifact_path(value: Any) -> str:
    text = _clean_string(value, MAX_STRING_LENGTH)
    if not text:
        return ""
    lowered = text.lower()
    parsed = urlparse(text)
    if parsed.scheme:
        return ""
    if lowered.startswith(("data:", "javascript:", "file:", "http:", "https:")):
        return ""
    if re.match(r"^[a-zA-Z]:[\\/]", text):
        return ""
    decoded = unquote(text).replace("\\", "/")
    if decoded.startswith("/api/files/artifact?"):
        query_path = parse_qs(urlparse(decoded).query).get("path", [""])[0]
        return _sanitize_artifact_path(query_path)
    if decoded.startswith("/"):
        return ""
    parts = [part for part in decoded.split("/") if part]
    if any(part == ".." for part in parts):
        return ""
    return text


def sanitize_frontend_context(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    clean: dict[str, Any] = {}
    for key in ALLOWED_CONTEXT_KEYS:
        if key not in payload:
            continue
        value = payload.get(key)
        if value in ("", None, [], {}):
            continue
        if key == "selected_feature_properties":
            props = _sanitize_feature_properties(value)
            if props:
                clean[key] = props
        elif key == "selected_map_bounds":
            bounds = _sanitize_bounds(value)
            if bounds:
                clean[key] = bounds
        elif key == "selected_artifact_path":
            artifact_path = _sanitize_artifact_path(value)
            if artifact_path:
                clean[key] = artifact_path
        else:
            if not _looks_sensitive_value(value):
                clean[key] = _clean_string(value)
    while clean and len(json.dumps(clean, ensure_ascii=False, default=str)) > MAX_CONTEXT_JSON_LENGTH:
        if "selected_feature_properties" in clean:
            clean.pop("selected_feature_properties")
        else:
            clean.pop(next(reversed(clean)))
    return clean


def _selected_artifact(payload: dict[str, Any]) -> dict[str, Any] | None:
    artifact_id = str(payload.get("selected_artifact_id") or "")
    path = str(payload.get("selected_artifact_path") or "")
    if not artifact_id and not path:
        return None
    return {
        "id": artifact_id,
        "type": str(payload.get("selected_artifact_type") or "artifact"),
        "path": path,
        "source": "frontend_context",
    }


def apply_frontend_context_to_state(state: ConversationState, payload: Any) -> ConversationState:
    context = sanitize_frontend_context(payload)
    if not context:
        return state
    state.frontend_context = context
    if context.get("active_dataset_id"):
        state.active_dataset = str(context["active_dataset_id"])
    artifact = _selected_artifact(context)
    if artifact:
        state.selected_artifact = artifact
        state.referenced_object = {"type": "artifact", "label": artifact.get("id") or artifact.get("path"), "path": artifact.get("path"), "data": artifact, "source": "frontend_context"}
    if context.get("selected_layer_id"):
        state.selected_layer = {"id": context["selected_layer_id"], "source": "frontend_context"}
        if not state.referenced_object:
            state.referenced_object = {
                "type": "dataset",
                "id": context["selected_layer_id"],
                "dataset_id": context["selected_layer_id"],
                "name": context["selected_layer_id"],
                "label": context["selected_layer_id"],
                "source": "frontend_context",
            }
    if context.get("selected_feature_id") or context.get("selected_feature_properties"):
        state.selected_feature = {
            "id": str(context.get("selected_feature_id") or ""),
            "layer_id": str(context.get("selected_layer_id") or ""),
            "properties": context.get("selected_feature_properties") or {},
            "source": "frontend_context",
        }
        state.referenced_object = {"type": "feature", "label": state.selected_feature.get("id") or "selected feature", "properties": state.selected_feature.get("properties") or {}, "data": state.selected_feature, "source": "frontend_context"}
    if context.get("selected_map_bounds"):
        state.selected_map_bounds = context["selected_map_bounds"]
    if context.get("selected_model_result_id"):
        state.selected_model_result = {"id": context["selected_model_result_id"], "source": "frontend_context"}
        state.referenced_object = {"type": "model_result", "label": context["selected_model_result_id"], "id": context["selected_model_result_id"], "data": state.selected_model_result, "source": "frontend_context"}
    if context.get("active_task_id"):
        state.active_task = {"id": context["active_task_id"], "source": "frontend_context"}
    return state
