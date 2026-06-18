from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _first_model_result(state: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any] | None:
    model = state.get("last_model_result")
    if isinstance(model, dict) and model:
        return model
    for item in _as_list(dashboard.get("model_results")):
        if isinstance(item, dict):
            return item
    return None


def _model_result_by_id(dashboard: dict[str, Any], model_result_id: str) -> dict[str, Any] | None:
    target = str(model_result_id or "")
    if not target:
        return None
    for item in _as_list(dashboard.get("model_results")):
        if isinstance(item, dict) and str(item.get("model_result_id") or item.get("id") or "") == target:
            return item
    return None


def _artifact_by_id(dashboard: dict[str, Any], artifact_id: str) -> dict[str, Any] | None:
    target = str(artifact_id or "")
    if not target:
        return None

    for item in _as_list(dashboard.get("artifacts")):
        if isinstance(item, dict) and str(item.get("artifact_id") or item.get("id") or "") == target:
            return item

    for result in _as_list(dashboard.get("model_results")):
        if not isinstance(result, dict):
            continue
        for item in _as_list(result.get("artifacts")):
            if isinstance(item, dict) and str(item.get("artifact_id") or item.get("id") or "") == target:
                return item
    return None


def _first_artifact(state: dict[str, Any], dashboard: dict[str, Any]) -> dict[str, Any] | None:
    for item in _as_list(state.get("active_artifacts")):
        if isinstance(item, dict):
            return item
    for item in _as_list(dashboard.get("artifacts")):
        if isinstance(item, dict):
            return item
    return None


def _object_from_artifact(item: dict[str, Any], fallback_type: str = "artifact") -> dict[str, Any]:
    return {
        "type": fallback_type,
        "label": str(item.get("label") or item.get("name") or item.get("display_path") or item.get("path") or "成果文件"),
        "path": str(item.get("path") or item.get("display_path") or item.get("download_url") or ""),
        "data": item,
    }


def _frontend_artifact_object(item: dict[str, Any], dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    artifact_id = str(item.get("id") or item.get("artifact_id") or "")
    matched = _artifact_by_id(_as_dict(dashboard), artifact_id)
    if matched:
        return {
            "type": "artifact",
            "label": str(
                matched.get("title")
                or matched.get("label")
                or matched.get("name")
                or matched.get("display_path")
                or matched.get("path")
                or artifact_id
            ),
            "id": artifact_id,
            "path": str(matched.get("path") or matched.get("display_path") or matched.get("download_url") or item.get("path") or ""),
            "data": matched,
            "source": "frontend_context",
        }
    return {
        "type": "artifact",
        "label": str(item.get("id") or item.get("path") or "selected artifact"),
        "id": artifact_id,
        "path": str(item.get("path") or ""),
        "data": item,
        "source": "frontend_context",
    }


def _frontend_model_object(item: dict[str, Any], dashboard: dict[str, Any] | None = None) -> dict[str, Any]:
    model_id = str(item.get("id") or item.get("model_result_id") or "")
    matched = _model_result_by_id(_as_dict(dashboard), model_id)
    if matched:
        return {
            "type": "model_result",
            "label": str(matched.get("model") or matched.get("output_prefix") or model_id),
            "id": model_id,
            "data": matched,
            "source": "frontend_context",
        }
    return {
        "type": "model_result",
        "label": str(item.get("id") or item.get("model") or "selected model result"),
        "id": model_id,
        "missing": bool(model_id),
        "data": item,
        "source": "frontend_context",
    }


def _frontend_feature_object(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "feature",
        "label": str(item.get("id") or item.get("layer_id") or "selected feature"),
        "id": str(item.get("id") or ""),
        "layer_id": str(item.get("layer_id") or ""),
        "properties": _as_dict(item.get("properties")),
        "data": item,
        "source": "frontend_context",
    }


def _frontend_layer_or_bounds_object(state: dict[str, Any]) -> dict[str, Any] | None:
    layer = _as_dict(state.get("selected_layer"))
    bounds = state.get("selected_map_bounds")
    if layer:
        return {
            "type": "layer",
            "label": str(layer.get("id") or "selected layer"),
            "id": str(layer.get("id") or ""),
            "bounds": bounds if isinstance(bounds, list) else None,
            "data": layer,
            "source": "frontend_context",
        }
    if isinstance(bounds, list):
        return {"type": "map_bounds", "label": "current map view", "bounds": bounds, "source": "frontend_context"}
    return None


def resolve_followup(prompt: str, state: Any, dashboard: Any) -> dict[str, Any]:
    text = str(prompt or "").strip()
    state_dict = _as_dict(state)
    dashboard_dict = _as_dict(dashboard)
    lower = text.lower()

    if not text:
        return {"resolved": False, "reason": "empty_prompt", "referenced_object": None}

    selected_feature = _as_dict(state_dict.get("selected_feature"))
    selected_artifact = _as_dict(state_dict.get("selected_artifact"))
    selected_model = _as_dict(state_dict.get("selected_model_result"))
    active_task = _as_dict(state_dict.get("active_task"))
    front_context = _as_dict(state_dict.get("frontend_context"))
    selected_layer = _as_dict(state_dict.get("selected_layer"))

    if _has_any(text, ("当前图层", "这个图层", "该图层")):
        layer_or_bounds = _frontend_layer_or_bounds_object(state_dict)
        if layer_or_bounds:
            return {"resolved": True, "reason": "matched_frontend_selected_layer", "referenced_object": layer_or_bounds}

    if _has_any(text, ("刚才的结果", "刚才生成的结果", "刚才下载的", "上一个结果", "这个结果", "下载刚才生成的结果")):
        if selected_model and _has_any(text, ("模型", "指标")):
            return {"resolved": True, "reason": "matched_frontend_selected_model_result", "referenced_object": _frontend_model_object(selected_model, dashboard_dict)}
        model = _first_model_result(state_dict, dashboard_dict)
        if model and not _has_any(text, ("下载", "文件", "图", "地图")):
            return {
                "resolved": True,
                "reason": "matched_recent_model_result",
                "referenced_object": {
                    "type": "model_result",
                    "label": str(model.get("model") or model.get("output_prefix") or "模型结果"),
                    "data": model,
                },
            }
        if selected_artifact:
            return {"resolved": True, "reason": "matched_frontend_selected_artifact", "referenced_object": _frontend_artifact_object(selected_artifact, dashboard_dict)}
        artifact = _first_artifact(state_dict, dashboard_dict)
        if artifact:
            return {"resolved": True, "reason": "matched_recent_artifact", "referenced_object": _object_from_artifact(artifact)}

    if _has_any(text, ("这个数据", "当前数据", "刚才的数据", "刚才下载的 DEM", "刚才下载的DEM")):
        active_dataset = _as_dict(state_dict.get("active_dataset"))
        if active_dataset:
            return {
                "resolved": True,
                "reason": "matched_active_dataset",
                "referenced_object": {
                    "type": "dataset",
                    "label": str(active_dataset.get("name") or active_dataset.get("id") or "当前数据"),
                    "id": str(active_dataset.get("id") or active_dataset.get("name") or ""),
                    "data": active_dataset,
                    "source": "conversation_state",
                },
            }
        if selected_layer:
            return {"resolved": True, "reason": "matched_frontend_selected_layer", "referenced_object": _frontend_layer_or_bounds_object(state_dict)}

    if selected_model and _has_any(text, ("模型效果", "模型结果", "这个模型", "指标", "效果怎么样")):
        return {"resolved": True, "reason": "matched_frontend_selected_model_result", "referenced_object": _frontend_model_object(selected_model, dashboard_dict)}

    if _has_any(text, ("这个地方", "这个区域", "这个点", "这里", "异常")):
        if selected_feature:
            return {"resolved": True, "reason": "matched_frontend_selected_feature", "referenced_object": _frontend_feature_object(selected_feature)}
        layer_or_bounds = _frontend_layer_or_bounds_object(state_dict)
        if layer_or_bounds:
            return {"resolved": True, "reason": "matched_frontend_map_context", "referenced_object": layer_or_bounds}

    if _has_any(text, ("模型效果", "模型结果", "指标", "效果怎么样")) and selected_model:
        return {"resolved": True, "reason": "matched_frontend_selected_model_result", "referenced_object": _frontend_model_object(selected_model, dashboard_dict)}

    if _has_any(text, ("这个结果", "这张图", "这幅图", "这个图", "结果说明", "说明什么", "怎么看")):
        if selected_model and _has_any(text, ("模型", "指标")):
            return {"resolved": True, "reason": "matched_frontend_selected_model_result", "referenced_object": _frontend_model_object(selected_model, dashboard_dict)}
        if selected_artifact:
            return {"resolved": True, "reason": "matched_frontend_selected_artifact", "referenced_object": _frontend_artifact_object(selected_artifact, dashboard_dict)}
        if selected_model:
            return {"resolved": True, "reason": "matched_frontend_selected_model_result", "referenced_object": _frontend_model_object(selected_model, dashboard_dict)}

    if _has_any(text, ("失败", "报错", "错误", "为什么失败")) or "error" in lower:
        error = state_dict.get("last_error")
        if isinstance(error, dict) and error:
            return {
                "resolved": True,
                "reason": "matched_last_error",
                "referenced_object": {"type": "error", "label": str(error.get("message") or "最近错误"), "data": error},
            }

    if _has_any(text, ("刚才那张图", "那张图", "这个图", "地图", "图怎么看", "图件", "这张图")):
        if selected_artifact:
            return {"resolved": True, "reason": "matched_frontend_selected_artifact", "referenced_object": _frontend_artifact_object(selected_artifact, dashboard_dict)}
        path = str(state_dict.get("last_map_path") or dashboard_dict.get("last_plot") or "")
        if path:
            return {
                "resolved": True,
                "reason": "matched_last_map_path",
                "referenced_object": {"type": "map", "label": path.split("/")[-1].split("\\")[-1], "path": path},
            }
        artifact = _first_artifact(state_dict, dashboard_dict)
        if artifact:
            return {"resolved": True, "reason": "matched_recent_artifact", "referenced_object": _object_from_artifact(artifact, "artifact")}

    if _has_any(text, ("这个结果", "结果", "指标", "模型结果", "说明什么", "解释")):
        if selected_model:
            return {"resolved": True, "reason": "matched_frontend_selected_model_result", "referenced_object": _frontend_model_object(selected_model, dashboard_dict)}
        if selected_artifact:
            return {"resolved": True, "reason": "matched_frontend_selected_artifact", "referenced_object": _frontend_artifact_object(selected_artifact, dashboard_dict)}
        model = _first_model_result(state_dict, dashboard_dict)
        if model:
            return {
                "resolved": True,
                "reason": "matched_recent_model_result",
                "referenced_object": {
                    "type": "model_result",
                    "label": str(model.get("model") or model.get("output_prefix") or "模型结果"),
                    "data": model,
                },
            }
        artifact = _first_artifact(state_dict, dashboard_dict)
        if artifact:
            return {"resolved": True, "reason": "matched_recent_artifact", "referenced_object": _object_from_artifact(artifact)}

    if _has_any(text, ("继续分析", "继续", "下一步", "改进一下", "再做")):
        hint = str(front_context.get("user_focus_hint") or "")
        if active_task or hint:
            label = hint or str(active_task.get("id") or "active task")
            return {
                "resolved": True,
                "reason": "matched_frontend_active_task",
                "referenced_object": {"type": "task", "label": label, "data": active_task, "source": "frontend_context"},
            }
        goal = str(state_dict.get("last_user_goal") or state_dict.get("last_task_type") or "")
        dataset = str(state_dict.get("active_dataset") or "")
        if goal or dataset:
            label = goal or f"继续处理 {dataset}"
            return {
                "resolved": True,
                "reason": "matched_previous_task",
                "referenced_object": {"type": "task", "label": label, "dataset": dataset},
            }

    dataset = str(state_dict.get("active_dataset") or "")
    if dataset and _has_any(text, ("这个", "它", "刚才")):
        return {
            "resolved": True,
            "reason": "matched_active_dataset",
            "referenced_object": {"type": "dataset", "label": dataset, "name": dataset},
        }

    return {"resolved": False, "reason": "no_reference_matched", "referenced_object": None}
