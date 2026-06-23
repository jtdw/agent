from __future__ import annotations

import json
from typing import Any

from core.agent_policy import policy_summary
from core.area_resolver import resolve_area_candidates
from core.asset_profiler import profile_dataset
from core.download_candidates import candidate_download_products
from core.field_semantics import match_user_field_concept
from core.knowledge_base import retrieve_knowledge_snippets
from core.response_language import detect_response_language
from core.tool_cards import candidate_tool_cards

MAX_CONTEXT_OBJECTS = 12
HISTORY_REFERENCE_TERMS = (
    "上次",
    "刚才",
    "之前",
    "上一轮",
    "这个图层",
    "这个结果",
    "这张图",
    "刚才下载",
    "previous",
    "last result",
    "selected",
    "this layer",
    "this result",
    "this shp",
    "缁撴灉",
)
CURRENT_UPLOAD_TERMS = ("上传", "当前上传", "我上传", "current upload", "uploaded", "this dataset", "this shp")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _asset_profile(manager: Any, name: str) -> dict[str, Any] | None:
    if not name:
        return None
    try:
        return profile_dataset(manager, name)
    except Exception:
        return None


def _compact_dataset(manager: Any, name: str, *, include_profile: bool = False) -> dict[str, Any] | None:
    if not name:
        return None
    try:
        record = manager.get(name)
    except Exception:
        return {"name": name}
    payload = {"name": record.name, "type": record.data_type, "path": str(record.path), "meta": record.meta}
    if include_profile:
        profile = _asset_profile(manager, record.name)
        if profile:
            payload["asset_profile"] = profile
    return payload


def _latest_dataset(manager: Any) -> dict[str, Any] | None:
    try:
        datasets = manager.list_datasets()
    except Exception:
        return None
    return datasets[-1] if datasets else None


def _has_explicit_history_reference(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(term.lower() in text for term in HISTORY_REFERENCE_TERMS)


def _has_explicit_current_upload_reference(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(term.lower() in text for term in CURRENT_UPLOAD_TERMS)


def _available_datasets(manager: Any) -> list[dict[str, Any]]:
    try:
        datasets = manager.list_datasets()
    except Exception:
        return []
    return [item for item in datasets if isinstance(item, dict)]


def _available_asset_profiles(manager: Any, limit: int = MAX_CONTEXT_OBJECTS) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for item in _available_datasets(manager)[-limit:]:
        name = str(item.get("name") or "")
        if not name:
            continue
        compact = _compact_dataset(manager, name, include_profile=True)
        if compact:
            profiles.append(compact)
    return profiles


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
    explicit_history_reference = _has_explicit_history_reference(str(prompt or ""))
    explicit_current_upload_reference = _has_explicit_current_upload_reference(str(prompt or ""))
    active_dataset = _compact_dataset(manager, str(state_dict.get("active_dataset") or ""), include_profile=True)
    if active_dataset is None and explicit_current_upload_reference:
        active_dataset = _latest_dataset(manager)
    if active_dataset and "asset_profile" not in active_dataset:
        active_name_for_profile = _dataset_name(active_dataset)
        profile = _asset_profile(manager, active_name_for_profile)
        if profile:
            active_dataset = {**active_dataset, "asset_profile": profile}
    active_name = _dataset_name(active_dataset)
    artifacts = _as_list(state_dict.get("active_artifacts")) or _as_list(dashboard_dict.get("artifacts"))
    field_profile = _field_profile(manager, active_dataset, str(prompt or ""))
    available_datasets = _compact_object_index(_available_datasets(manager), active_name)
    available_layers = [item for item in available_datasets if str(item.get("type") or item.get("data_type") or "") == "vector"]
    active_selection = {}
    if explicit_history_reference:
        active_selection = {
            "selected_artifact": state_dict.get("selected_artifact"),
            "selected_layer": state_dict.get("selected_layer"),
            "selected_feature": state_dict.get("selected_feature"),
            "selected_model_result": state_dict.get("selected_model_result"),
            "selected_map_bounds": state_dict.get("selected_map_bounds"),
        }
    task_type = str(_as_dict(intent).get("intent") or "")
    retrieval_text = " ".join(
        [
            str(prompt or ""),
            task_type,
            json.dumps(active_dataset, ensure_ascii=False, default=str)[:2000],
        ]
    )
    context = {
        "prompt": str(prompt or ""),
        "response_language": detect_response_language(prompt),
        "agent_policy": policy_summary(),
        "intent": intent,
        "workspace": dashboard_dict.get("summary") or getattr(manager, "workspace_summary", lambda: {})(),
        "active_dataset": active_dataset,
        "available_datasets": available_datasets,
        "available_asset_profiles": _available_asset_profiles(manager),
        "available_layers": available_layers[:MAX_CONTEXT_OBJECTS],
        "latest_derived_datasets": _compact_object_index(_latest_derived_datasets(manager), active_name),
        "active_selection": {key: value for key, value in active_selection.items() if value},
        "recent_artifacts": [item for item in artifacts[:3] if isinstance(item, dict)] if explicit_history_reference else [],
        "recent_map_path": (state_dict.get("last_map_path") or dashboard_dict.get("last_plot") or "") if explicit_history_reference else "",
        "recent_model_result": _recent_model_result(dashboard_dict, state_dict) if explicit_history_reference else None,
        "recent_tool_results": _as_list(state_dict.get("last_tool_results"))[:3] if explicit_history_reference else [],
        "recent_error": state_dict.get("last_error") if explicit_history_reference and isinstance(state_dict.get("last_error"), dict) else None,
        "user_goal": str(state_dict.get("last_user_goal") or ""),
        "referenced_object": state_dict.get("referenced_object") if explicit_history_reference and isinstance(state_dict.get("referenced_object"), dict) else None,
        "followup": followup or {},
        "context_sources": {
            "current_request_priority": True,
            "response_language": detect_response_language(prompt),
            "explicit_history_reference": explicit_history_reference,
            "explicit_current_upload_reference": explicit_current_upload_reference,
            "active_dataset_source": "conversation_state" if state_dict.get("active_dataset") else ("current_upload_reference" if active_dataset else ""),
        },
        "knowledge_snippets": retrieve_knowledge_snippets(retrieval_text, limit=5),
        "candidate_tool_cards": candidate_tool_cards(retrieval_text, task_type=task_type, limit=8),
        "download_candidates": candidate_download_products(retrieval_text, limit=6),
        "area_candidates": resolve_area_candidates(str(prompt or ""), limit=8, manager=manager),
        **field_profile,
    }
    context["capability_trace"] = {
        "knowledge_chunk_ids": [
            str(item.get("knowledge_chunk_id") or item.get("id") or "")
            for item in _as_list(context.get("knowledge_snippets"))
            if isinstance(item, dict)
        ],
        "knowledge_versions": {
            str(item.get("knowledge_id") or item.get("id") or ""): str(item.get("knowledge_version") or item.get("version") or "")
            for item in _as_list(context.get("knowledge_snippets"))
            if isinstance(item, dict)
        },
        "tool_card_versions": {
            str(item.get("tool_name") or ""): str(item.get("version") or item.get("schema_version") or "")
            for item in _as_list(context.get("candidate_tool_cards"))
            if isinstance(item, dict)
        },
        "product_catalog_versions": {
            str(item.get("product_id") or item.get("product_key") or ""): str(item.get("version") or item.get("schema_version") or "")
            for item in _as_list(context.get("download_candidates"))
            if isinstance(item, dict)
        },
        "asset_registry_versions": {
            str(item.get("asset_id") or ""): str(item.get("version") or item.get("schema_version") or "")
            for item in _as_list(context.get("area_candidates"))
            if isinstance(item, dict)
        },
    }
    if explicit_history_reference and followup and isinstance(followup.get("referenced_object"), dict):
        context["referenced_object"] = followup["referenced_object"]
        ref = followup["referenced_object"]
        if ref.get("type") == "model_result" and isinstance(ref.get("data"), dict) and not ref.get("missing"):
            context["recent_model_result"] = ref["data"]
    return context


def format_context_for_agent(context: dict[str, Any]) -> str:
    def _compact_knowledge_snippets(value: Any) -> list[dict[str, Any]]:
        snippets: list[dict[str, Any]] = []
        for item in _as_list(value):
            if not isinstance(item, dict):
                continue
            snippets.append(
                {
                    "knowledge_chunk_id": item.get("knowledge_chunk_id") or item.get("id") or "",
                    "knowledge_id": item.get("knowledge_id") or item.get("id") or "",
                    "knowledge_version": item.get("knowledge_version") or item.get("version") or "",
                    "title": item.get("title") or "",
                    "content": item.get("content") or "",
                    "source": item.get("source") or "",
                    "applicable_scope": item.get("applicable_scope") or item.get("scope") or "",
                    "reliability": item.get("reliability") or item.get("trust_level") or "",
                }
            )
        return snippets

    payload = {
        "intent": _as_dict(context.get("intent")).get("intent"),
        "agent_policy": context.get("agent_policy"),
        "workspace": context.get("workspace"),
        "active_dataset": context.get("active_dataset"),
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
        "knowledge_snippets": _compact_knowledge_snippets(context.get("knowledge_snippets")),
        "candidate_tool_cards": context.get("candidate_tool_cards"),
        "download_candidates": context.get("download_candidates"),
        "area_candidates": context.get("area_candidates"),
        "capability_trace": context.get("capability_trace"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
