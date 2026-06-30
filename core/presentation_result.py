from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.response_language import localized_text, normalize_response_language
from core.zhipu_json_client import LLMProviderError


PresentationStatus = Literal["succeeded", "failed", "running", "awaiting_confirmation", "blocked"]


class Ref(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    title: str = ""
    type: str = ""
    source_step_id: str = ""
    source_tool: str = ""


class LayerRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer_id: str
    name: str = ""
    source_step_id: str = ""
    source_tool: str = ""


class TableRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str
    title: str = ""
    source_step_id: str = ""
    source_tool: str = ""


class ImageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    title: str = ""
    source_step_id: str = ""
    source_tool: str = ""


class PresentationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "presentation-result/v1"
    response_language: str = "en-US"
    status: PresentationStatus
    concise_summary: str = ""
    executed_steps: list[dict[str, str]] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    result_highlights: list[str] = Field(default_factory=list)
    artifact_refs: list[Ref] = Field(default_factory=list)
    map_layer_refs: list[LayerRef] = Field(default_factory=list)
    table_refs: list[TableRef] = Field(default_factory=list)
    image_refs: list[ImageRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_summary: str = ""
    next_action_suggestions: list[str] = Field(default_factory=list)
    clarification_question: str = ""


class LLMPresentationResult(PresentationResult):
    confidence: float = Field(0.0, ge=0.0, le=1.0)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_text(value: Any, limit: int = 180) -> str:
    text = str(value or "").strip()
    for marker in (
        "workspace\\",
        "workspace/",
        ":\\",
        "/tmp/",
        "/home/",
        "/var/",
        "/etc/",
        "/root/",
        "/users/",
        "\\users\\",
        "session_",
        "user_id",
        "session_id",
        "Traceback",
    ):
        if marker in text:
            return ""
    return text[:limit]


def _path_lookup_key(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("\\", "/").lower()


def _safe_ref_list(items: Any, *, id_key: str, label_keys: tuple[str, ...]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _as_list(items):
        if not isinstance(item, dict):
            continue
        ref_id = _clean_text(item.get(id_key) or item.get("id"), 120)
        if not ref_id or ref_id in seen:
            continue
        seen.add(ref_id)
        ref: dict[str, str] = {id_key: ref_id}
        for key in label_keys:
            value = _clean_text(item.get(key), 120)
            if value:
                ref[key] = value
        output.append(ref)
    return output


def _parse_llm_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, LLMPresentationResult):
        return raw.model_dump(mode="json")
    if isinstance(raw, PresentationResult):
        return raw.model_dump(mode="json")
    if isinstance(raw, dict):
        return raw
    content = getattr(raw, "content", raw)
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _invoke_presentation_client(client: Any, payload: dict[str, Any]) -> Any:
    if client is None:
        raise RuntimeError("presentation client unavailable")
    if hasattr(client, "with_structured_output"):
        structured = client.with_structured_output(LLMPresentationResult)
        if hasattr(structured, "invoke"):
            return structured.invoke(payload)
        if callable(structured):
            return structured(payload)
    if hasattr(client, "invoke"):
        return client.invoke(
            [
                (
                    "system",
                    "You are a GIS Result Interpreter. Return only a PresentationResult JSON object. "
                    "Use only the canonical execution facts provided. Do not invent files, metrics, layers, links, or IDs.",
                ),
                ("user", json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)),
            ]
        )
    if callable(client):
        return client(payload)
    raise RuntimeError("presentation client is not callable")


def _status(coordinator_status: str, results: list[dict[str, Any]]) -> PresentationStatus:
    statuses = [str(item.get("status") or "") for item in results]
    if "awaiting_confirmation" in statuses:
        return "awaiting_confirmation"
    if "blocked" in statuses:
        return "blocked"
    if "failed" in statuses:
        return "failed"
    if "running" in statuses:
        return "running"
    raw = str(coordinator_status or "").strip()
    if raw in {"succeeded", "failed", "running", "awaiting_confirmation", "blocked"}:
        return raw  # type: ignore[return-value]
    return "succeeded" if results else "blocked"


def _metric_highlights(outputs: dict[str, Any]) -> list[str]:
    candidates: list[dict[str, Any]] = []
    for key in ("metrics", "model_metrics", "scores"):
        item = outputs.get(key)
        if isinstance(item, dict):
            candidates.append(item)
        elif isinstance(item, list):
            candidates.extend(entry for entry in item if isinstance(entry, dict))
    if isinstance(outputs.get("diagnostics"), dict):
        candidates.append(outputs["diagnostics"])
    highlights: list[str] = []
    for metrics in candidates:
        for key in (
            "RMSE",
            "MAE",
            "R2",
            "R",
            "NSE",
            "Bias",
            "PICP",
            "MPIW",
            "target_coverage",
            "empirical_coverage",
            "mean_interval_width",
            "median_interval_width",
            "interval_width_std",
            "interval_score",
            "effective_method",
            "method",
        ):
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                highlights.append(f"{key}={value:.4g}")
            elif isinstance(value, str) and value.strip():
                highlights.append(f"{key}={value.strip()[:40]}")
    return highlights


def _is_image_artifact_type(value: str) -> bool:
    return str(value or "").strip().lower() in {"image", "png", "jpg", "jpeg", "webp"}


def _collect_errors(result: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for error in _as_list(result.get("errors")):
        if not isinstance(error, dict):
            continue
        code = _clean_text(error.get("code"), 80)
        message = _clean_text(error.get("message") or error.get("title"), 180)
        if code or message:
            messages.append(" - ".join(item for item in (code, message) if item))
    return messages


def build_presentation_result(
    *,
    task_goal: str,
    task_plan_summary: dict[str, Any],
    coordinator_status: str,
    normalized_results: list[Any],
    legacy_payload: dict[str, Any] | None = None,
    response_language: str = "en-US",
) -> dict[str, Any]:
    del legacy_payload
    results = [item for item in normalized_results if isinstance(item, dict)]
    status = _status(coordinator_status, results)
    executed_steps: list[dict[str, str]] = []
    data_sources: list[str] = []
    result_highlights: list[str] = []
    artifact_refs: list[dict[str, str]] = []
    map_layer_refs: list[dict[str, str]] = []
    table_refs: list[dict[str, str]] = []
    image_refs: list[dict[str, str]] = []
    warnings: list[str] = []
    next_actions: list[str] = []
    error_parts: list[str] = []
    seen_artifacts: set[str] = set()
    seen_layers: set[str] = set()
    seen_tables: set[str] = set()
    seen_images: set[str] = set()

    for result in results:
        step_id = _clean_text(result.get("step_id"), 80)
        tool_name = _clean_text(result.get("tool_name"), 100)
        step_status = _clean_text(result.get("status"), 40)
        if step_id or tool_name:
            executed_steps.append({"step_id": step_id, "tool_name": tool_name, "status": step_status})
        for asset_id in _as_list(result.get("input_asset_ids")):
            clean = _clean_text(asset_id, 100)
            if clean:
                data_sources.append(clean)
        outputs = _as_dict(result.get("outputs"))
        for key in ("name", "dataset_name", "result_dataset", "source_dataset"):
            value = _clean_text(outputs.get(key), 100)
            if value:
                data_sources.append(value)
        result_highlights.extend(_metric_highlights(outputs))
        diagnostics = _as_dict(result.get("diagnostics"))
        result_highlights.extend(_metric_highlights(diagnostics))
        for key in ("result_dataset", "model_result_id", "feature_count", "row_count", "target", "representative_date", "valid_prediction_pixels"):
            value = _clean_text(outputs.get(key), 100)
            if value:
                result_highlights.append(f"{key}={value}")
        for artifact in _as_list(result.get("artifacts")):
            if not isinstance(artifact, dict):
                continue
            artifact_type = _clean_text(artifact.get("type") or artifact.get("kind"), 60)
            artifact_id = _clean_text(artifact.get("artifact_id") or artifact.get("id"), 120)
            if not artifact_id or artifact_id in seen_artifacts:
                continue
            seen_artifacts.add(artifact_id)
            title = _clean_text(artifact.get("title") or artifact.get("filename") or artifact.get("name"), 120)
            artifact_refs.append(
                {
                    "artifact_id": artifact_id,
                    "title": title,
                    "type": artifact_type,
                    "source_step_id": step_id,
                    "source_tool": tool_name,
                }
            )
            if _is_image_artifact_type(artifact_type) and artifact_id not in seen_images:
                seen_images.add(artifact_id)
                image_refs.append({"artifact_id": artifact_id, "title": title, "source_step_id": step_id, "source_tool": tool_name})
        for layer in _as_list(result.get("map_layers")):
            if not isinstance(layer, dict):
                continue
            layer_id = _clean_text(layer.get("layer_id") or layer.get("id"), 120)
            if not layer_id or layer_id in seen_layers:
                continue
            seen_layers.add(layer_id)
            map_layer_refs.append({"layer_id": layer_id, "name": _clean_text(layer.get("name"), 120), "source_step_id": step_id, "source_tool": tool_name})
        for table in _as_list(result.get("tables")):
            if not isinstance(table, dict):
                continue
            table_id = _clean_text(table.get("table_id") or table.get("id"), 120)
            if not table_id or table_id in seen_tables:
                continue
            seen_tables.add(table_id)
            table_refs.append({"table_id": table_id, "title": _clean_text(table.get("title") or table.get("name"), 120), "source_step_id": step_id, "source_tool": tool_name})
        for image in _as_list(result.get("images")):
            if not isinstance(image, dict):
                continue
            artifact_id = _clean_text(image.get("artifact_id") or image.get("id"), 120)
            if not artifact_id or artifact_id in seen_images or artifact_id not in seen_artifacts:
                continue
            seen_images.add(artifact_id)
            image_refs.append({"artifact_id": artifact_id, "title": _clean_text(image.get("title") or image.get("name"), 120), "source_step_id": step_id, "source_tool": tool_name})
        warnings.extend(_clean_text(item, 180) for item in _as_list(result.get("warnings")))
        next_actions.extend(_clean_text(item, 180) for item in _as_list(result.get("next_actions")))
        if step_status in {"failed", "blocked"}:
            errors = _collect_errors(result)
            if errors:
                error_parts.append(f"{step_id or tool_name}: {errors[0]}")

    response_language = normalize_response_language(response_language, task_goal)
    zh = response_language.startswith("zh")
    if status in {"failed", "blocked"} and not error_parts:
        error_parts.append(localized_text("execution_stopped", response_language))
    clarification = ""
    if status in {"awaiting_confirmation", "blocked"}:
        clarification = next((item for item in next_actions if item), "")

    primary_goal = _clean_text(task_plan_summary.get("primary_goal") or task_plan_summary.get("operation") or task_goal, 160)
    display_goal = primary_goal or ("请求的 GIS 任务" if zh else "the requested GIS task")
    if status == "succeeded":
        summary = f"已完成{display_goal}，共执行 {len(executed_steps)} 个步骤。" if zh else f"Completed {display_goal} using {len(executed_steps)} executed step(s)."
    elif status == "running":
        summary = f"{display_goal}仍在运行。" if zh else f"{display_goal} is still running."
    elif status == "awaiting_confirmation":
        summary = f"{display_goal}正在等待确认。" if zh else f"{display_goal} is awaiting user confirmation."
    elif status == "blocked":
        summary = f"{display_goal}已被阻断。" if zh else f"{display_goal} is blocked."
    else:
        summary = f"{display_goal}执行失败。" if zh else f"{display_goal} failed."

    payload = PresentationResult(
        response_language=response_language,
        status=status,
        concise_summary=summary,
        executed_steps=executed_steps,
        data_sources=list(dict.fromkeys(item for item in data_sources if item)),
        result_highlights=list(dict.fromkeys(item for item in result_highlights if item)),
        artifact_refs=artifact_refs,
        map_layer_refs=map_layer_refs,
        table_refs=table_refs,
        image_refs=image_refs,
        warnings=list(dict.fromkeys(item for item in warnings if item)),
        error_summary="; ".join(error_parts),
        next_action_suggestions=list(dict.fromkeys(item for item in next_actions if item))[:8],
        clarification_question=clarification,
    )
    return payload.model_dump(mode="json")


def _ids_from_presentation(payload: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "artifact_refs": {str(item.get("artifact_id") or "") for item in _as_list(payload.get("artifact_refs")) if isinstance(item, dict) and str(item.get("artifact_id") or "").strip()},
        "map_layer_refs": {str(item.get("layer_id") or "") for item in _as_list(payload.get("map_layer_refs")) if isinstance(item, dict) and str(item.get("layer_id") or "").strip()},
        "table_refs": {str(item.get("table_id") or "") for item in _as_list(payload.get("table_refs")) if isinstance(item, dict) and str(item.get("table_id") or "").strip()},
        "image_refs": {str(item.get("artifact_id") or "") for item in _as_list(payload.get("image_refs")) if isinstance(item, dict) and str(item.get("artifact_id") or "").strip()},
    }


def _filter_ref_list(items: list[Any], *, id_key: str, allowed: set[str]) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        ref_id = _clean_text(item.get(id_key), 120)
        if not ref_id or ref_id not in allowed or ref_id in seen:
            continue
        seen.add(ref_id)
        filtered.append({str(key): _clean_text(value, 160) for key, value in item.items() if str(key) in {id_key, "title", "type", "name", "source_step_id", "source_tool"}})
    return filtered


def _known_step_ids(results: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("step_id") or "") for item in results if str(item.get("step_id") or "").strip()}


def _safe_llm_presentation(
    *,
    base: dict[str, Any],
    llm_payload: dict[str, Any],
    normalized_results: list[dict[str, Any]],
    min_confidence: float,
) -> dict[str, Any] | None:
    try:
        parsed = LLMPresentationResult.model_validate(llm_payload)
    except Exception:
        return None
    if parsed.confidence < min_confidence:
        return None
    candidate = parsed.model_dump(mode="json")
    candidate.pop("confidence", None)
    allowed_ids = _ids_from_presentation(base)
    base_highlights = {str(item) for item in _as_list(base.get("result_highlights"))}
    base_data_sources = {str(item) for item in _as_list(base.get("data_sources"))}
    step_ids = _known_step_ids(normalized_results)
    candidate["status"] = base.get("status") or candidate.get("status")
    candidate["result_highlights"] = [item for item in _as_list(candidate.get("result_highlights")) if str(item) in base_highlights]
    candidate["data_sources"] = [item for item in _as_list(candidate.get("data_sources")) if str(item) in base_data_sources]
    candidate["executed_steps"] = [
        item
        for item in _as_list(candidate.get("executed_steps"))
        if isinstance(item, dict) and str(item.get("step_id") or "") in step_ids
    ] or base.get("executed_steps", [])
    candidate["artifact_refs"] = _filter_ref_list(_as_list(candidate.get("artifact_refs")), id_key="artifact_id", allowed=allowed_ids["artifact_refs"])
    candidate["map_layer_refs"] = _filter_ref_list(_as_list(candidate.get("map_layer_refs")), id_key="layer_id", allowed=allowed_ids["map_layer_refs"])
    candidate["table_refs"] = _filter_ref_list(_as_list(candidate.get("table_refs")), id_key="table_id", allowed=allowed_ids["table_refs"])
    candidate["image_refs"] = _filter_ref_list(_as_list(candidate.get("image_refs")), id_key="artifact_id", allowed=allowed_ids["image_refs"])
    candidate["warnings"] = [item for item in _as_list(candidate.get("warnings")) if str(item) in {str(base_item) for base_item in _as_list(base.get("warnings"))}]
    candidate["next_action_suggestions"] = [
        item
        for item in _as_list(candidate.get("next_action_suggestions"))
        if str(item) in {str(base_item) for base_item in _as_list(base.get("next_action_suggestions"))}
    ]
    if base.get("error_summary") and not candidate.get("error_summary"):
        candidate["error_summary"] = base.get("error_summary")
    if base.get("clarification_question") and not candidate.get("clarification_question"):
        candidate["clarification_question"] = base.get("clarification_question")
    try:
        return PresentationResult.model_validate(candidate).model_dump(mode="json")
    except Exception:
        return None


def build_llm_presentation_result(
    *,
    task_goal: str,
    task_plan_summary: dict[str, Any],
    coordinator_status: str,
    normalized_results: list[dict[str, Any]],
    deterministic_result: dict[str, Any],
    client: Any | None = None,
    min_confidence: float = 0.65,
    response_language: str = "en-US",
) -> dict[str, Any] | None:
    if client is None:
        try:
            from .llm_task_planner import build_default_llm_task_planner_client

            client = build_default_llm_task_planner_client(operation="result_interpreter")
        except Exception:
            client = None
    if client is None:
        return None
    payload = {
        "task_goal": _clean_text(task_goal, 240),
        "task_plan_summary": task_plan_summary,
        "coordinator_status": _clean_text(coordinator_status, 60),
        "response_language": normalize_response_language(response_language, task_goal),
        "canonical_facts": normalized_results,
        "deterministic_presentation": deterministic_result,
        "presentation_schema": LLMPresentationResult.model_json_schema(),
        "rules": [
            "Use only artifact_id, layer_id, table_id, image artifact_id values present in canonical_facts.",
            "Do not invent metrics, files, download links, map layers, table refs, or image refs.",
            "Return confidence below 0.65 if the canonical facts are insufficient.",
            "All user-facing text must use response_language.",
        ],
    }
    try:
        raw = _invoke_presentation_client(client, payload)
    except LLMProviderError:
        return None
    except Exception:
        return None
    parsed = _parse_llm_payload(raw)
    if parsed is None:
        return None
    return _safe_llm_presentation(base=deterministic_result, llm_payload=parsed, normalized_results=normalized_results, min_confidence=min_confidence)


def build_execution_summary(presentation_result: dict[str, Any]) -> dict[str, Any]:
    payload = _as_dict(presentation_result)
    return {
        "schema_version": "execution-summary/v1",
        "response_language": _clean_text(payload.get("response_language"), 20),
        "status": _clean_text(payload.get("status"), 40),
        "summary": _clean_text(payload.get("concise_summary"), 220),
        "executed_step_count": len(_as_list(payload.get("executed_steps"))),
        "artifact_count": len(_as_list(payload.get("artifact_refs"))),
        "map_layer_count": len(_as_list(payload.get("map_layer_refs"))),
        "table_count": len(_as_list(payload.get("table_refs"))),
        "image_count": len(_as_list(payload.get("image_refs"))),
        "warning_count": len(_as_list(payload.get("warnings"))),
        "error_summary": _clean_text(payload.get("error_summary"), 260),
        "clarification_question": _clean_text(payload.get("clarification_question"), 220),
        "next_action_count": len(_as_list(payload.get("next_action_suggestions"))),
    }


def sanitize_normalized_results(normalized_results: list[Any]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in normalized_results:
        if not isinstance(item, dict):
            continue
        artifact_ids_by_path: dict[str, str] = {}
        for artifact in _as_list(item.get("artifacts")):
            if not isinstance(artifact, dict):
                continue
            artifact_id = _clean_text(artifact.get("artifact_id") or artifact.get("id"), 120)
            path_key = _path_lookup_key(artifact.get("path") or artifact.get("absolute_path") or artifact.get("relative_path"))
            if artifact_id and path_key:
                artifact_ids_by_path[path_key] = artifact_id
        outputs = {
            str(key): value
            for key, value in _as_dict(item.get("outputs")).items()
            if str(key) not in {"path", "absolute_path", "relative_path", "download_url", "job_id", "user_id", "session_id"}
            and _clean_text(value, 200)
        }
        diagnostics = {
            str(key): value
            for key, value in _as_dict(item.get("diagnostics")).items()
            if str(key) not in {"traceback", "stack", "stacktrace", "log_path", "path", "storage_state_path", "user_id", "session_id"}
            and _clean_text(value, 200)
        }
        artifacts = []
        for artifact in _as_list(item.get("artifacts")):
            if not isinstance(artifact, dict):
                continue
            artifact_id = _clean_text(artifact.get("artifact_id") or artifact.get("id"), 120)
            if not artifact_id:
                continue
            artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "title": _clean_text(artifact.get("title") or artifact.get("filename") or artifact.get("name"), 120),
                    "type": _clean_text(artifact.get("type") or artifact.get("kind"), 60),
                }
            )
        images = []
        for image in _as_list(item.get("images")):
            image_dict = image if isinstance(image, dict) else {"path": image}
            artifact_id = _clean_text(image_dict.get("artifact_id") or image_dict.get("id"), 120)
            if not artifact_id:
                artifact_id = artifact_ids_by_path.get(_path_lookup_key(image_dict.get("path")))
            if not artifact_id:
                continue
            images.append(
                {
                    "artifact_id": artifact_id,
                    "title": _clean_text(image_dict.get("title") or image_dict.get("name"), 120),
                }
            )
        sanitized.append(
            {
                "status": _clean_text(item.get("status"), 40),
                "errors": [{"code": _clean_text(error.get("code"), 80), "message": _clean_text(error.get("message"), 180)} for error in _as_list(item.get("errors")) if isinstance(error, dict)],
                "warnings": [_clean_text(value, 180) for value in _as_list(item.get("warnings")) if _clean_text(value, 180)],
                "artifacts": artifacts,
                "map_layers": _safe_ref_list(item.get("map_layers"), id_key="layer_id", label_keys=("name", "title", "type")),
                "tables": _safe_ref_list(item.get("tables"), id_key="table_id", label_keys=("title", "name", "type")),
                "images": images,
                "outputs": outputs,
                "diagnostics": diagnostics,
                "next_actions": [_clean_text(value, 180) for value in _as_list(item.get("next_actions")) if _clean_text(value, 180)],
                "step_id": _clean_text(item.get("step_id"), 80),
                "tool_name": _clean_text(item.get("tool_name"), 100),
                "input_asset_ids": [_clean_text(value, 100) for value in _as_list(item.get("input_asset_ids")) if _clean_text(value, 100)],
            }
        )
    return sanitized


def build_presentation_bundle(
    *,
    task_goal: str,
    task_plan_summary: dict[str, Any],
    coordinator_status: str,
    normalized_results: list[Any],
    llm_client: Any | None = None,
    min_confidence: float = 0.65,
    response_language: str = "",
) -> dict[str, Any]:
    response_language = normalize_response_language(response_language or task_plan_summary.get("response_language"), task_goal)
    safe_results = sanitize_normalized_results(normalized_results)
    deterministic = build_presentation_result(
        task_goal=task_goal,
        task_plan_summary=task_plan_summary,
        coordinator_status=coordinator_status,
        normalized_results=safe_results,
        response_language=response_language,
    )
    presentation = build_llm_presentation_result(
        task_goal=task_goal,
        task_plan_summary=task_plan_summary,
        coordinator_status=coordinator_status,
        normalized_results=safe_results,
        deterministic_result=deterministic,
        client=llm_client,
        min_confidence=min_confidence,
        response_language=response_language,
    )
    source = "llm" if presentation is not None else "deterministic"
    if presentation is None:
        presentation = deterministic
    execution_summary = build_execution_summary(presentation)
    return {
        "schema_version": "presentation-bundle/v1",
        "normalized_results": safe_results,
        "presentation_result": presentation,
        "execution_summary": execution_summary,
        "reply": format_presentation_reply(presentation),
        "presentation_source": source,
        "result_rendering_path": "presentation_result",
    }


def build_presentation_bundle_from_raw_execution(
    *,
    plan: dict[str, Any],
    raw_results: Any,
    task_goal: str,
    task_plan_summary: dict[str, Any],
    coordinator_status: str = "",
    llm_client: Any | None = None,
    min_confidence: float = 0.65,
    response_language: str = "",
) -> dict[str, Any]:
    from .execution_trace import build_execution_trace

    trace = build_execution_trace(plan, raw_results)
    status = coordinator_status or str(trace.status)
    return build_presentation_bundle(
        task_goal=task_goal,
        task_plan_summary=task_plan_summary,
        coordinator_status=status,
        normalized_results=[item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in trace.results],
        llm_client=llm_client,
        min_confidence=min_confidence,
        response_language=response_language or plan.get("response_language") or task_plan_summary.get("response_language") or "",
    )


def format_presentation_reply(presentation_result: dict[str, Any]) -> str:
    payload = _as_dict(presentation_result)
    language = normalize_response_language(payload.get("response_language"), payload.get("concise_summary"))
    zh = language.startswith("zh")
    labels = {
        "key_results": "关键结果" if zh else "Key results",
        "data_sources": "数据来源" if zh else "Data sources",
        "artifacts": "成果文件" if zh else "Artifacts",
        "warnings": "警告" if zh else "Warnings",
        "error": "错误" if zh else "Error",
        "needs_attention": "需要确认" if zh else "Needs attention",
        "next_actions": "建议下一步" if zh else "Next actions",
    }
    lines = [str(payload.get("concise_summary") or localized_text("task_result_ready", language))]
    highlights = [str(item) for item in _as_list(payload.get("result_highlights")) if str(item).strip()]
    if highlights:
        lines.extend(["", f"{labels['key_results']}:", *[f"- {item}" for item in highlights[:8]]])
    data_sources = [str(item) for item in _as_list(payload.get("data_sources")) if str(item).strip()]
    if data_sources:
        lines.extend(["", f"{labels['data_sources']}:", *[f"- {item}" for item in data_sources[:8]]])
    artifacts = [item for item in _as_list(payload.get("artifact_refs")) if isinstance(item, dict)]
    if artifacts:
        lines.extend(["", f"{labels['artifacts']}:", *[f"- {item.get('title') or item.get('artifact_id')}" for item in artifacts[:8]]])
    warnings = [str(item) for item in _as_list(payload.get("warnings")) if str(item).strip()]
    if warnings:
        lines.extend(["", f"{labels['warnings']}:", *[f"- {item}" for item in warnings[:5]]])
    error_summary = str(payload.get("error_summary") or "").strip()
    if error_summary:
        lines.extend(["", f"{labels['error']}:", error_summary])
    question = str(payload.get("clarification_question") or "").strip()
    if question:
        lines.extend(["", f"{labels['needs_attention']}:", question])
    actions = [str(item) for item in _as_list(payload.get("next_action_suggestions")) if str(item).strip()]
    if actions:
        lines.extend(["", f"{labels['next_actions']}:", *[f"- {item}" for item in actions[:5]]])
    return "\n".join(lines)
