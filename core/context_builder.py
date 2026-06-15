from __future__ import annotations

import json
import re
from typing import Any

from core.field_semantics import match_user_field_concept

MAX_CONTEXT_OBJECTS = 12


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact_dataset(manager: Any, name: str) -> dict[str, Any] | None:
    if not name:
        return None
    try:
        record = manager.get(name)
    except Exception:
        return {"name": name}
    return {"name": record.name, "type": record.data_type, "path": str(record.path), "meta": record.meta}


def _latest_dataset(manager: Any) -> dict[str, Any] | None:
    try:
        datasets = manager.list_datasets()
    except Exception:
        return None
    return datasets[-1] if datasets else None


def _available_datasets(manager: Any) -> list[dict[str, Any]]:
    try:
        datasets = manager.list_datasets()
    except Exception:
        return []
    return [item for item in datasets if isinstance(item, dict)]


def _mentioned_datasets(manager: Any, prompt: str) -> list[dict[str, Any]]:
    names = [item.strip() for item in re.findall(r"@\{([^{}]+)\}", str(prompt or "")) if item.strip()]
    if not names:
        return []
    available = {str(item.get("name") or ""): item for item in _available_datasets(manager)}
    return [available[name] for name in dict.fromkeys(names) if name in available]


def _compact_object_index(items: list[dict[str, Any]], active_name: str = "", limit: int = MAX_CONTEXT_OBJECTS) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                key: item.get(key)
                for key in ("name", "dataset_id", "type", "data_type", "path", "artifact_id", "title", "description", "model_result_id")
                if item.get(key) not in (None, "")
            }
        )
    active_items = [item for item in compacted if active_name and str(item.get("name") or item.get("dataset_id") or "") == active_name]
    remaining = [item for item in compacted if item not in active_items]
    return [*active_items, *remaining][-limit:]


def _latest_derived_datasets(manager: Any, limit: int = 5) -> list[dict[str, Any]]:
    datasets = _available_datasets(manager)
    derived = [item for item in datasets if "derived" in str(item.get("path") or "").replace("\\", "/").lower()]
    return list(reversed(derived[-limit:]))


def _dataset_name(dataset: Any) -> str:
    if isinstance(dataset, dict):
        return str(dataset.get("name") or "")
    return ""


def _field_profile(manager: Any, dataset: dict[str, Any] | None, prompt: str) -> dict[str, Any]:
    if not dataset:
        return {
            "available_fields": [],
            "numeric_fields": [],
            "geometry_fields": [],
            "semantic_field_candidates": match_user_field_concept(prompt, []),
            "likely_target_fields": [],
            "likely_mapping_fields": [],
        }

    fields: list[str] = []
    numeric_fields: list[str] = []
    geometry_fields: list[str] = []
    name = _dataset_name(dataset)
    meta = dataset.get("meta") if isinstance(dataset.get("meta"), dict) else {}
    for col in meta.get("columns") or meta.get("fields") or []:
        if str(col or "").strip():
            fields.append(str(col))

    frame = None
    try:
        dtype = str(dataset.get("type") or dataset.get("data_type") or "")
        if dtype == "table" and hasattr(manager, "get_table"):
            frame = manager.get_table(name)
        elif dtype == "vector" and hasattr(manager, "get_vector"):
            frame = manager.get_vector(name)
    except Exception:
        frame = None

    if frame is not None:
        try:
            columns = [str(col) for col in frame.columns]
            fields = columns or fields
            for col in columns:
                if col.lower() == "geometry":
                    geometry_fields.append(col)
                    continue
                try:
                    if bool(getattr(frame[col], "dtype", None) is not None and frame[col].dtype.kind in "biufc"):
                        numeric_fields.append(col)
                except Exception:
                    continue
        except Exception:
            pass

    if not numeric_fields:
        for item in meta.get("numeric_fields") or meta.get("value_cols") or []:
            if str(item or "").strip():
                numeric_fields.append(str(item))
    if not geometry_fields and ("geometry" in fields or str(dataset.get("type") or "") == "vector"):
        geometry_fields = [field for field in fields if field.lower() == "geometry"] or ["geometry"]

    available_fields = list(dict.fromkeys(fields))
    numeric_fields = [field for field in dict.fromkeys(numeric_fields) if field in available_fields]
    lower_skip = ("id", "code", "name", "date", "time", "lon", "lng", "lat", "x", "y")
    likely_target_fields = [
        field
        for field in numeric_fields
        if not any(token == field.lower() or field.lower().endswith(f"_{token}") for token in lower_skip)
    ]
    likely_mapping_fields = numeric_fields or [field for field in available_fields if field not in geometry_fields][:8]
    return {
        "available_fields": available_fields,
        "numeric_fields": numeric_fields,
        "geometry_fields": geometry_fields,
        "semantic_field_candidates": match_user_field_concept(prompt, available_fields),
        "likely_target_fields": likely_target_fields[:12],
        "likely_mapping_fields": likely_mapping_fields[:12],
    }


def _recent_model_result(dashboard: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
    ref = state.get("referenced_object")
    if isinstance(ref, dict) and ref.get("type") == "model_result":
        data = ref.get("data")
        if isinstance(data, dict) and not ref.get("missing"):
            return data
    selected = state.get("selected_model_result")
    selected_id = str(selected.get("id") or "") if isinstance(selected, dict) else ""
    if selected_id:
        for item in _as_list(dashboard.get("model_results")):
            if isinstance(item, dict) and str(item.get("model_result_id") or item.get("id") or "") == selected_id:
                return item
    model = state.get("last_model_result")
    if isinstance(model, dict) and model:
        return model
    for item in _as_list(dashboard.get("model_results")):
        if isinstance(item, dict):
            return item
    return None


def build_conversation_context(
    prompt: str,
    intent: dict[str, Any],
    state: Any,
    manager: Any,
    dashboard: Any,
    followup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state_dict = _as_dict(state)
    dashboard_dict = _as_dict(dashboard)
    mentioned_datasets = _mentioned_datasets(manager, str(prompt or ""))
    active_dataset = (mentioned_datasets[0] if mentioned_datasets else None) or _compact_dataset(manager, str(state_dict.get("active_dataset") or "")) or _latest_dataset(manager)
    active_name = _dataset_name(active_dataset)
    artifacts = _as_list(state_dict.get("active_artifacts")) or _as_list(dashboard_dict.get("artifacts"))
    field_profile = _field_profile(manager, active_dataset, str(prompt or ""))
    available_datasets = _compact_object_index(_available_datasets(manager), active_name)
    available_layers = [item for item in available_datasets if str(item.get("type") or item.get("data_type") or "") == "vector"]
    active_selection = {
        "selected_artifact": state_dict.get("selected_artifact"),
        "selected_layer": state_dict.get("selected_layer"),
        "selected_feature": state_dict.get("selected_feature"),
        "selected_model_result": state_dict.get("selected_model_result"),
        "selected_map_bounds": state_dict.get("selected_map_bounds"),
    }
    context = {
        "prompt": str(prompt or ""),
        "intent": intent,
        "workspace": dashboard_dict.get("summary") or getattr(manager, "workspace_summary", lambda: {})(),
        "active_dataset": active_dataset,
        "mentioned_datasets": _compact_object_index(mentioned_datasets, active_name),
        "available_datasets": available_datasets,
        "available_layers": available_layers[:MAX_CONTEXT_OBJECTS],
        "latest_derived_datasets": _compact_object_index(_latest_derived_datasets(manager), active_name),
        "active_selection": {key: value for key, value in active_selection.items() if value},
        "recent_artifacts": [item for item in artifacts[:3] if isinstance(item, dict)],
        "recent_map_path": state_dict.get("last_map_path") or dashboard_dict.get("last_plot") or "",
        "recent_model_result": _recent_model_result(dashboard_dict, state_dict),
        "recent_tool_results": _as_list(state_dict.get("last_tool_results"))[:3],
        "recent_error": state_dict.get("last_error") if isinstance(state_dict.get("last_error"), dict) else None,
        "user_goal": str(state_dict.get("last_user_goal") or ""),
        "referenced_object": state_dict.get("referenced_object") if isinstance(state_dict.get("referenced_object"), dict) else None,
        "followup": followup or {},
        **field_profile,
    }
    if followup and isinstance(followup.get("referenced_object"), dict):
        context["referenced_object"] = followup["referenced_object"]
        ref = followup["referenced_object"]
        if ref.get("type") == "model_result" and isinstance(ref.get("data"), dict) and not ref.get("missing"):
            context["recent_model_result"] = ref["data"]
    return context


def format_context_for_agent(context: dict[str, Any]) -> str:
    payload = {
        "intent": _as_dict(context.get("intent")).get("intent"),
        "workspace": context.get("workspace"),
        "active_dataset": context.get("active_dataset"),
        "mentioned_datasets": context.get("mentioned_datasets"),
        "available_datasets": context.get("available_datasets"),
        "available_layers": context.get("available_layers"),
        "latest_derived_datasets": context.get("latest_derived_datasets"),
        "active_selection": context.get("active_selection"),
        "recent_artifacts": context.get("recent_artifacts"),
        "recent_map_path": context.get("recent_map_path"),
        "recent_model_result": context.get("recent_model_result"),
        "recent_tool_results": context.get("recent_tool_results"),
        "recent_error": context.get("recent_error"),
        "user_goal": context.get("user_goal"),
        "referenced_object": context.get("referenced_object"),
        "available_fields": context.get("available_fields"),
        "numeric_fields": context.get("numeric_fields"),
        "geometry_fields": context.get("geometry_fields"),
        "semantic_field_candidates": context.get("semantic_field_candidates"),
        "likely_target_fields": context.get("likely_target_fields"),
        "likely_mapping_fields": context.get("likely_mapping_fields"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
