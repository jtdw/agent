from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .field_semantics import match_user_field_concept, normalize_field_name


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _empty(object_type: str, reason: str, *, candidates: list[dict[str, Any]] | None = None, clarify: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "type": object_type,
        "name": "",
        "id": "",
        "path": "",
        "data": {},
        "confidence": 0.0,
        "candidates": candidates or [],
        "source": "",
        "missing_reason": reason,
        "needs_clarification": clarify,
    }


def _ok(object_type: str, item: dict[str, Any], *, confidence: float, source: str, name: str = "", id_value: str = "") -> dict[str, Any]:
    resolved_name = name or str(item.get("name") or item.get("dataset_id") or item.get("id") or item.get("artifact_id") or "")
    resolved_id = id_value or str(item.get("id") or item.get("artifact_id") or item.get("dataset_id") or item.get("model_result_id") or resolved_name)
    return {
        "ok": True,
        "type": object_type,
        "name": resolved_name,
        "id": resolved_id,
        "path": str(item.get("path") or ""),
        "data": item,
        "confidence": round(confidence, 3),
        "candidates": [],
        "source": source,
        "missing_reason": "",
        "needs_clarification": False,
    }


def _active_dataset(context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    active = state.get("active_dataset") or context.get("active_dataset")
    if isinstance(active, dict):
        return active
    if str(active or "").strip():
        return {"name": str(active)}
    return {}


def _selected_layer(context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    selected = state.get("selected_layer") or _as_dict(context.get("active_selection")).get("selected_layer")
    return selected if isinstance(selected, dict) else {}


def _collect_datasets(context: dict[str, Any], manager: Any | None) -> list[dict[str, Any]]:
    datasets: list[dict[str, Any]] = []
    active = _active_dataset(context, {})
    if active:
        datasets.append(active)
    datasets.extend(item for item in _as_list(context.get("available_datasets")) if isinstance(item, dict))
    latest = context.get("latest_derived_datasets")
    datasets.extend(item for item in _as_list(latest) if isinstance(item, dict))
    if manager is not None:
        try:
            datasets.extend(item for item in manager.list_datasets() if isinstance(item, dict))
        except Exception:
            pass

    by_name: dict[str, dict[str, Any]] = {}
    for item in datasets:
        name = str(item.get("name") or item.get("dataset_id") or "")
        if name and name not in by_name:
            by_name[name] = item
    return list(by_name.values())


def _collect_artifacts(context: dict[str, Any], state: dict[str, Any], manager: Any | None) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for key in ("selected_artifact", "referenced_object"):
        item = state.get(key) or context.get(key)
        if isinstance(item, dict) and item:
            artifacts.append(item)
    artifacts.extend(item for item in _as_list(context.get("recent_artifacts")) if isinstance(item, dict))
    artifacts.extend(item for item in _as_list(state.get("active_artifacts")) if isinstance(item, dict))
    if manager is not None:
        try:
            artifacts.extend(item for item in manager.list_artifacts() if isinstance(item, dict))
        except Exception:
            pass
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in artifacts:
        key = str(item.get("artifact_id") or item.get("path") or item.get("name") or id(item))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _text_blob(item: dict[str, Any]) -> str:
    parts = [
        item.get("name"),
        item.get("dataset_id"),
        item.get("id"),
        item.get("artifact_id"),
        item.get("path"),
        item.get("title"),
        item.get("description"),
        item.get("type"),
        item.get("category"),
    ]
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    parts.extend([meta.get("tool_name"), meta.get("operation"), meta.get("source")])
    return " ".join(str(part or "") for part in parts)


def _explicit_mentions(prompt: str) -> list[str]:
    return [item.strip() for item in re.findall(r"@\{([^}]+)\}", str(prompt or "")) if item.strip()]


def _dataset_ref_values(item: dict[str, Any]) -> set[str]:
    values = {
        str(item.get("name") or ""),
        str(item.get("dataset_id") or ""),
        str(item.get("id") or ""),
        Path(str(item.get("path") or "")).stem,
    }
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    values.update({str(meta.get("original_filename") or ""), Path(str(meta.get("original_filename") or "")).stem})
    return {normalize_field_name(value) for value in values if str(value or "").strip()}


def _match_explicit_dataset_reference(prompt: str, datasets: list[dict[str, Any]]) -> dict[str, Any] | None:
    mentions = [normalize_field_name(item) for item in _explicit_mentions(prompt)]
    if not mentions:
        return None
    for mention in mentions:
        matches = [item for item in datasets if mention in _dataset_ref_values(item)]
        if len(matches) == 1:
            return _ok("dataset", matches[0], confidence=1.0, source="explicit_mention")
        if len(matches) > 1:
            candidates = [
                {"name": str(item.get("name") or item.get("dataset_id") or ""), "type": item.get("type") or item.get("data_type") or "", "score": 1.0, "data": item}
                for item in matches
            ]
            return _empty("dataset", "Multiple dataset candidates matched explicit mention.", candidates=candidates[:5], clarify=True)
    return _empty("dataset", "Explicit dataset mention was not found in the workspace.")


def _looks_clipped(item: dict[str, Any]) -> bool:
    blob = normalize_field_name(_text_blob(item))
    return any(token in blob for token in ("clip", "clipped", "vectorclip", "裁剪"))


def _dataset_candidate_score(prompt: str, item: dict[str, Any], object_type: str) -> float:
    text = normalize_field_name(prompt)
    blob = normalize_field_name(_text_blob(item))
    name = normalize_field_name(item.get("name") or item.get("dataset_id") or Path(str(item.get("path") or "")).stem)
    score = 0.0
    if name and name in text:
        score = max(score, 0.94)
    if name and name in blob and name in text:
        score = max(score, 0.9)
    if object_type == "clip_boundary":
        study_tokens = ("研究区", "studyarea", "aoi", "roi")
        boundary_tokens = ("边界", "boundary", "border", "countyboundary", "region")
        county_tokens = ("县域", "区县", "county", "district")
        if any(token in text for token in study_tokens) and any(token in blob for token in ("studyarea", "aoi", "roi", "研究区")):
            score = max(score, 0.96)
        if any(token in text for token in boundary_tokens) and any(token in blob for token in boundary_tokens):
            score = max(score, 0.86)
        if any(token in text for token in county_tokens) and any(token in blob for token in county_tokens):
            score = max(score, 0.84)
    if object_type in {"dataset", "layer"} and any(token in text for token in ("当前图层", "currentlayer")) and str(item.get("type") or item.get("data_type") or "") == "vector":
        score = max(score, 0.82)
    return score


def _resolve_dataset(prompt: str, context: dict[str, Any], state: dict[str, Any], manager: Any | None, object_type: str) -> dict[str, Any]:
    active = _active_dataset(context, state)
    text = normalize_field_name(prompt)
    datasets = _collect_datasets(context, manager)
    if object_type == "dataset":
        explicit = _match_explicit_dataset_reference(prompt, datasets)
        if explicit is not None:
            return explicit
    if object_type == "dataset" and active and any(token in text for token in ("这个数据", "当前数据", "thisdata", "currentdata", "dataset")):
        return _ok("dataset", active, confidence=0.96, source="active_dataset")

    if object_type == "layer":
        selected = _selected_layer(context, state)
        if selected:
            return _ok("layer", selected, confidence=0.96, source="active_selection")
        if active and str(active.get("type") or active.get("data_type") or "") == "vector":
            return _ok("layer", active, confidence=0.82, source="active_dataset")

    scored = [
        {"name": str(item.get("name") or item.get("dataset_id") or ""), "type": item.get("type") or item.get("data_type") or "", "score": _dataset_candidate_score(prompt, item, object_type), "data": item}
        for item in datasets
    ]
    scored = [item for item in scored if float(item["score"]) >= 0.55 and str(item["name"])]
    scored.sort(key=lambda item: (-float(item["score"]), str(item["name"])))
    if not scored:
        if object_type == "dataset" and active:
            return _ok("dataset", active, confidence=0.7, source="active_dataset")
        return _empty(object_type, f"No matching {object_type} found.")
    if len(scored) > 1 and float(scored[0]["score"]) - float(scored[1]["score"]) < 0.08:
        return _empty(object_type, f"Multiple {object_type} candidates found.", candidates=scored[:5], clarify=True)
    best = scored[0]
    resolved_type = "dataset" if object_type == "clip_boundary" else object_type
    return _ok(resolved_type, best["data"], confidence=float(best["score"]), source="object_resolver", name=str(best["name"]))


def _resolve_field(prompt: str, context: dict[str, Any]) -> dict[str, Any]:
    fields = [str(field) for field in _as_list(context.get("available_fields")) if str(field or "").strip()]
    semantic = match_user_field_concept(prompt, fields)
    candidates = [item for item in semantic.get("candidates", []) if isinstance(item, dict)]
    best_field = str(semantic.get("best_field") or "")
    confidence = float(semantic.get("confidence") or 0.0)
    if best_field and confidence >= 0.78 and not semantic.get("needs_clarification"):
        return _ok("field", {"name": best_field, "field": best_field, "semantic": semantic}, confidence=confidence, source="field_semantics", name=best_field, id_value=best_field)
    if candidates:
        return _empty("field", "Multiple field candidates found." if semantic.get("needs_clarification") else "Field confidence is too low.", candidates=candidates[:5], clarify=True)
    return _empty("field", "No matching field found.")


def _resolve_artifact(prompt: str, context: dict[str, Any], state: dict[str, Any], manager: Any | None, object_type: str) -> dict[str, Any]:
    artifacts = _collect_artifacts(context, state, manager)
    text = normalize_field_name(prompt)
    if object_type in {"artifact", "map_result"} and any(token in text for token in ("刚才的结果", "这个结果", "lastresult", "result")):
        clipped = [item for item in artifacts if _looks_clipped(item)]
        if any(token in text for token in ("裁剪", "clip", "clipped")) and clipped:
            return _ok("artifact", clipped[0], confidence=0.94, source="recent_artifact")
        if artifacts:
            return _ok("artifact", artifacts[0], confidence=0.82, source="recent_artifact")
    if any(token in text for token in ("刚才裁剪后的结果", "裁剪后的数据", "clippedresult", "clippeddata")):
        for item in artifacts:
            if _looks_clipped(item):
                return _ok("artifact", item, confidence=0.94, source="recent_artifact")
    return _empty(object_type, f"No matching {object_type} found.")


def resolve_object_reference(
    prompt: str,
    context: Any,
    manager: Any | None = None,
    state: Any | None = None,
    object_type: str = "any",
) -> dict[str, Any]:
    ctx = _as_dict(context)
    st = _as_dict(state)
    requested = object_type or "any"
    if requested == "field":
        return _resolve_field(prompt, ctx)
    if requested in {"dataset", "layer", "clip_boundary"}:
        return _resolve_dataset(prompt, ctx, st, manager, requested)
    if requested in {"artifact", "map_result"}:
        return _resolve_artifact(prompt, ctx, st, manager, requested)
    if requested == "model_result":
        model = st.get("selected_model_result") or ctx.get("recent_model_result")
        if isinstance(model, dict) and model:
            return _ok("model_result", model, confidence=0.9, source="conversation_state")
        return _empty("model_result", "No matching model result found.")

    for candidate_type in ("field", "artifact", "clip_boundary", "dataset"):
        result = resolve_object_reference(prompt, ctx, manager=manager, state=st, object_type=candidate_type)
        if result.get("ok") or result.get("needs_clarification"):
            return result
    return _empty("any", "No matching object found.")
