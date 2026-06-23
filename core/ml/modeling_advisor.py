from __future__ import annotations

import json
import os
from typing import Any

from core.llm_config import load_llm_provider_config_for_role
from core.zhipu_json_client import ZhipuJSONClient


_BLOCKED_KEYS = {
    "path",
    "file_path",
    "full_path",
    "sample_rows",
    "raw_rows",
    "records",
    "data",
    "bounds",
    "coordinates",
    "geometry",
}


def _sanitize_profile(value: Any, *, parent_key: str = "") -> Any:
    key = str(parent_key or "").lower()
    if key in _BLOCKED_KEYS:
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_key_text = str(child_key)
            if child_key_text.lower() in _BLOCKED_KEYS:
                continue
            sanitized = _sanitize_profile(child_value, parent_key=child_key_text)
            if sanitized is not None:
                result[child_key_text] = sanitized
        return result
    if isinstance(value, list):
        return [_sanitize_profile(item, parent_key=parent_key) for item in value if _sanitize_profile(item, parent_key=parent_key) is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _validate_advice(data: dict[str, Any], safe_profile: dict[str, Any]) -> dict[str, Any]:
    fields = {str(item.get("name")) for item in safe_profile.get("fields", []) if isinstance(item, dict) and item.get("name")}
    feature_candidates = {str(item) for item in safe_profile.get("feature_candidates", [])}
    target = str(data.get("target_col") or "")
    features = [str(item) for item in data.get("feature_cols", []) if str(item or "").strip()] if isinstance(data.get("feature_cols"), list) else []
    if target and fields and target not in fields:
        target = ""
    features = [field for field in features if not fields or field in fields]
    if not features and feature_candidates:
        features = sorted(feature_candidates)
    task_type = str(data.get("task_type") or "auto").lower()
    if task_type not in {"auto", "regression", "classification"}:
        task_type = "auto"
    split_method = str(data.get("split_method") or "auto").lower()
    if split_method not in {"auto", "random", "group", "spatial", "spatial_block", "date", "temporal", "spatiotemporal"}:
        split_method = "auto"
    return {
        "target_col": target,
        "feature_cols": features,
        "task_type": task_type,
        "split_method": "date" if split_method == "temporal" else split_method,
        "notes": data.get("notes") if isinstance(data.get("notes"), list) else [],
    }


def build_zhipu_modeling_advice(modeling_profile: dict[str, Any], *, client: Any) -> dict[str, Any]:
    """Ask a Zhipu-compatible JSON client for modeling advice using only a safe profile."""

    safe_profile = _sanitize_profile(modeling_profile)
    if not isinstance(safe_profile, dict):
        safe_profile = {}
    messages = [
        {
            "role": "system",
            "content": (
                "You are a modeling advisor. Return JSON only. "
                "Use the provided desensitized dataset profile to suggest target_col, feature_cols, task_type, split_method, and notes. "
                "Do not request raw data."
            ),
        },
        {"role": "user", "content": json.dumps({"modeling_profile": safe_profile}, ensure_ascii=False, default=str)},
    ]
    try:
        raw = client.invoke(messages)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("advisor response is not an object")
        return {"status": "ok", "advice": _validate_advice(parsed, safe_profile), "payload_profile": safe_profile}
    except Exception as exc:
        return {"status": "fallback_local", "advice": {}, "error": exc.__class__.__name__, "payload_profile": safe_profile}


def modeling_advisor_enabled(value: bool | None = None) -> bool:
    if value is not None:
        return bool(value)
    return os.getenv("GIS_AGENT_ENABLE_MODELING_ADVISOR", "").strip().lower() in {"1", "true", "yes", "on"}


def build_default_modeling_advisor_client() -> Any | None:
    config = load_llm_provider_config_for_role("planner")
    api_key = os.getenv(config.api_key_env, "") if config.api_key_env else ""
    if config.provider != "fake" and not api_key:
        return None
    return ZhipuJSONClient(config, api_key=api_key, operation="modeling_advisor")
