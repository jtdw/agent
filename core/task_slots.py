from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from core.field_semantics import match_user_field_concept, normalize_field_name


@dataclass
class TaskSlots:
    task_type: str = "unclear_request"
    dataset_id: str = ""
    target_concept: str = ""
    target_field: str = ""
    candidate_fields: list[dict[str, Any]] = field(default_factory=list)
    map_type: str = ""
    model_type: str = ""
    target_variable: str = ""
    feature_fields: list[str] = field(default_factory=list)
    date_field: str = ""
    output_name: str = ""
    spatial_validation: bool | None = None
    spatial_operation: str = ""
    filter_condition: str = ""
    output_format: str = ""
    referenced_artifact: dict[str, Any] | None = None
    missing_inputs: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _active_dataset(conversation_state: Any, workspace_summary: Any) -> str:
    state = _as_dict(conversation_state)
    workspace = _as_dict(workspace_summary)
    active = state.get("active_dataset") or workspace.get("active_dataset")
    if isinstance(active, dict):
        return str(active.get("name") or active.get("id") or "")
    if active:
        return str(active)
    dataset = workspace.get("active_dataset")
    if isinstance(dataset, dict):
        return str(dataset.get("name") or "")
    return ""


def _available_fields(workspace_summary: Any) -> list[str]:
    workspace = _as_dict(workspace_summary)
    fields = workspace.get("available_fields")
    if isinstance(fields, list):
        return [str(field) for field in fields if str(field or "").strip()]
    active = workspace.get("active_dataset")
    if isinstance(active, dict):
        meta = active.get("meta") if isinstance(active.get("meta"), dict) else {}
        columns = meta.get("columns") or meta.get("fields") or []
        return [str(field) for field in columns if str(field or "").strip()]
    return []


def _numeric_fields(workspace_summary: Any) -> list[str]:
    workspace = _as_dict(workspace_summary)
    fields = workspace.get("numeric_fields")
    if isinstance(fields, list):
        return [str(field) for field in fields if str(field or "").strip()]
    return []


def _referenced_artifact(conversation_state: Any, workspace_summary: Any) -> dict[str, Any] | None:
    for source in (_as_dict(conversation_state), _as_dict(workspace_summary)):
        ref = source.get("referenced_object")
        if isinstance(ref, dict):
            return ref
        followup = source.get("followup")
        if isinstance(followup, dict) and isinstance(followup.get("referenced_object"), dict):
            return followup["referenced_object"]
        model = source.get("recent_model_result")
        if isinstance(model, dict) and model:
            return {"type": "model_result", "data": model}
    artifacts = _as_list(_as_dict(workspace_summary).get("recent_artifacts"))
    return artifacts[0] if artifacts and isinstance(artifacts[0], dict) else None


def _mentioned_fields(prompt: str, fields: list[str]) -> list[str]:
    text = normalize_field_name(prompt)
    mentioned: list[str] = []
    for field_name in fields:
        normalized = normalize_field_name(field_name)
        if normalized and normalized in text:
            mentioned.append(field_name)
    return mentioned


def _target_after_predict(prompt: str, fields: list[str]) -> str:
    text = str(prompt or "")
    match = re.search(r"\b(?:predict|estimate|model|forecast)\b(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return ""
    tail = normalize_field_name(match.group(1))
    for field_name in fields:
        normalized = normalize_field_name(field_name)
        if normalized and normalized in tail:
            return field_name
    return ""


def _model_type(prompt: str) -> str:
    text = str(prompt or "").lower()
    if "random forest" in text or "rf" in text:
        return "random_forest"
    if "xgboost" in text or "xgb" in text:
        return "xgboost"
    if "regression" in text or "predict" in text or "forecast" in text:
        return "regression"
    return ""


def _explicit_field(prompt: str, labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})\s*(?:是|为|使用|[:：=])?\s*[`'\"]?([A-Za-z_][A-Za-z0-9_.-]*)",
        str(prompt or ""),
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else ""


def _explicit_feature_fields(prompt: str, available_fields: list[str]) -> list[str]:
    match = re.search(
        r"(?:特征列|特征字段|feature\s*(?:columns?|fields?))\s*(?:是|为|使用|包括|[:：=])?\s*(.+?)(?:[。；;\n]|$)",
        str(prompt or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    requested = [token for token in re.split(r"[,，、\s]+", match.group(1).strip()) if token]
    field_lookup = {field.lower(): field for field in available_fields}
    return [field_lookup[token.lower()] for token in requested if token.lower() in field_lookup]


def _explicit_spatial_validation(prompt: str) -> bool | None:
    text = str(prompt or "")
    if not re.search(r"空间\s*(?:分块|交叉)?\s*验证|spatial\s*(?:block|cross)?\s*validation", text, flags=re.IGNORECASE):
        return None
    if re.search(r"(?:关闭|禁用|不要|不启用|取消)\s*空间", text):
        return False
    return True


def _output_format(prompt: str) -> str:
    text = str(prompt or "").lower()
    formats = []
    if any(token in text for token in ("image", "png", "jpg", "map")):
        formats.append("image")
    if any(token in text for token in ("table", "csv", "excel", "xlsx")):
        formats.append("table")
    return "+".join(formats)


def _chinese_spatial_operation(prompt: str) -> str:
    text = str(prompt or "").lower()
    if "\u88c1\u526a" in text:
        return "clip"
    if "\u53e0\u52a0" in text:
        return "overlay"
    if "\u7a7a\u95f4\u8fde\u63a5" in text or "\u8fde\u63a5" in text:
        return "spatial_join"
    if "裁剪" in text:
        return "clip"
    if "叠加" in text:
        return "overlay"
    if "空间连接" in text or "连接" in text:
        return "spatial_join"
    return ""


def _spatial_operation(prompt: str) -> str:
    text = str(prompt or "").lower()
    chinese_operation = _chinese_spatial_operation(prompt)
    if chinese_operation:
        return chinese_operation
    if "clip" in text or "裁剪" in text:
        return "clip"
    if "\u88c1\u526a" in text:
        return "clip"
    if "overlay" in text or "叠加" in text:
        return "overlay"
    if "join" in text or "连接" in text:
        return "spatial_join"
    return ""


def _add_missing(slots: TaskSlots, names: list[str]) -> None:
    slots.missing_inputs = list(dict.fromkeys([*slots.missing_inputs, *[name for name in names if name]]))


def extract_task_slots(
    prompt: str,
    intent_result: Any,
    conversation_state: Any,
    workspace_summary: Any,
) -> dict[str, Any]:
    intent = _as_dict(intent_result)
    task_type = str(intent.get("intent") or "unclear_request")
    fields = _available_fields(workspace_summary)
    numeric_fields = _numeric_fields(workspace_summary)
    dataset_id = _active_dataset(conversation_state, workspace_summary)
    slots = TaskSlots(
        task_type=task_type,
        dataset_id=dataset_id,
        confidence=float(intent.get("confidence") or 0.0),
        referenced_artifact=_referenced_artifact(conversation_state, workspace_summary),
    )

    text = str(prompt or "")
    if task_type == "map_generation":
        slots.map_type = "thematic" if fields else "map"
        semantic = match_user_field_concept(text, fields)
        slots.target_concept = str(semantic.get("concept") or "")
        slots.candidate_fields = [item for item in semantic.get("candidates", []) if isinstance(item, dict)]
        if semantic.get("best_field") and not semantic.get("needs_clarification"):
            slots.target_field = str(semantic["best_field"])
        elif slots.candidate_fields:
            _add_missing(slots, ["map_field"])
        else:
            _add_missing(slots, ["map_field"])

    elif task_type == "modeling":
        slots.model_type = _model_type(text)
        mentioned = _mentioned_fields(text, fields)
        explicit_target = _explicit_field(text, ("目标列", "目标字段", "target column", "target field"))
        target = explicit_target or _target_after_predict(text, fields)
        semantic = match_user_field_concept(text, fields)
        slots.target_concept = str(semantic.get("concept") or "")
        slots.candidate_fields = [item for item in semantic.get("candidates", []) if isinstance(item, dict)]
        if target and target in fields:
            slots.target_variable = target
        elif semantic.get("best_field") and not semantic.get("needs_clarification"):
            slots.target_variable = str(semantic["best_field"])
        explicit_features = _explicit_feature_fields(text, fields)
        features = explicit_features or [field for field in mentioned if field != slots.target_variable]
        numeric_set = set(numeric_fields or fields)
        slots.feature_fields = [field for field in features if field in numeric_set]
        slots.date_field = _explicit_field(text, ("时间列", "日期列", "时间字段", "日期字段", "date column", "date field"))
        slots.output_name = _explicit_field(text, ("输出名称", "输出名", "结果名称", "output name"))
        slots.spatial_validation = _explicit_spatial_validation(text)
        if not slots.target_variable:
            _add_missing(slots, ["target column"])
        if not slots.feature_fields:
            _add_missing(slots, ["feature columns"])

    elif task_type == "data_processing":
        slots.spatial_operation = _spatial_operation(text)
        if slots.spatial_operation == "clip":
            if not dataset_id:
                _add_missing(slots, ["dataset"])
            ref = slots.referenced_artifact if isinstance(slots.referenced_artifact, dict) else {}
            has_clip_ref = bool(ref.get("name") or ref.get("dataset_id") or ref.get("id"))
            if not has_clip_ref and not re.search(r"\b(?:study area|boundary|clip layer|mask)\b|\u7814\u7a76\u533a|\u8fb9\u754c|\u53bf\u57df|\u533a\u53bf", text, flags=re.IGNORECASE):
                _add_missing(slots, ["clip layer"])

    elif task_type in {"result_analysis", "follow_up_question"}:
        if not slots.referenced_artifact:
            _add_missing(slots, ["referenced object"])

    if "export" in text.lower() or "导出" in text:
        slots.output_format = _output_format(text) or "file"
        if not dataset_id and not slots.referenced_artifact:
            _add_missing(slots, ["result object"])

    if not dataset_id and task_type in {"map_generation", "modeling", "data_processing"}:
        _add_missing(slots, ["dataset"])

    return slots.to_dict()
