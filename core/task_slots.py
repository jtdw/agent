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
    time_column: str = ""
    spatial_columns: list[str] = field(default_factory=list)
    validation_method: str = ""
    output_name: str = ""
    requested_outputs: list[str] = field(default_factory=list)
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


def _field_lookup(fields: list[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for field_name in fields:
        lookup[normalize_field_name(field_name)] = field_name
        lookup[str(field_name).lower()] = field_name
    return lookup


def _parse_field_list(value: str, fields: list[str]) -> list[str]:
    lookup = _field_lookup(fields)
    parsed: list[str] = []
    for token in re.split(r"[,，、\s]+", str(value or "")):
        clean = token.strip(" ，,。.;；：:=[]()（）")
        if not clean:
            continue
        field = lookup.get(normalize_field_name(clean)) or lookup.get(clean.lower())
        if field and field not in parsed:
            parsed.append(field)
    return parsed


def _field_after_label(prompt: str, labels: tuple[str, ...], fields: list[str]) -> str:
    extra_labels: list[str] = []
    label_text = " ".join(labels).lower()
    if any(token in label_text for token in ("target", "label", "鐩", "棰")):
        extra_labels.extend(["目标列", "目标变量", "预测列", "预测字段", "标签列"])
    if any(token in label_text for token in ("date", "time", "鏃")):
        extra_labels.extend(["时间列", "时间字段", "日期列"])
    labels = tuple(dict.fromkeys([*labels, *extra_labels]))
    chinese_label_pattern = "|".join(re.escape(label) for label in labels)
    chinese_match = re.search(rf"(?:{chinese_label_pattern})\s*(?:是|为|使用|=|:|：)?\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", str(prompt or ""), flags=re.IGNORECASE)
    if chinese_match:
        parsed = _parse_field_list(chinese_match.group(1), fields)
        if parsed:
            return parsed[0]
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})\s*(?:是|为|使用|=|:|：)?\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", str(prompt or ""), flags=re.IGNORECASE)
    if not match:
        return ""
    parsed = _parse_field_list(match.group(1), fields)
    return parsed[0] if parsed else ""


def _feature_fields_from_prompt(prompt: str, fields: list[str]) -> list[str]:
    chinese_match = re.search(r"(?:特征列|特征字段|候选特征|输入特征)\s*(?:使用|是|为|包括|包含|=|:|：)?\s*([^。；;\n]+)", str(prompt or ""), flags=re.IGNORECASE)
    if chinese_match:
        parsed = _parse_field_list(chinese_match.group(1), fields)
        if parsed:
            return parsed
    match = re.search(r"(?:特征列|特征字段|feature(?:_cols| columns)?)\s*(?:使用|是|为|=|:|：)?\s*([^。；;\n]+)", str(prompt or ""), flags=re.IGNORECASE)
    if not match:
        return []
    return _parse_field_list(match.group(1), fields)


def _output_name(prompt: str) -> str:
    chinese_match = re.search(r"(?:输出名称|输出名|保存为|命名为)\s*(?:是|为|=|:|：)?\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", str(prompt or ""), flags=re.IGNORECASE)
    if chinese_match:
        return chinese_match.group(1).strip(" 。，;；)")
    match = re.search(r"(?:输出名称|输出名|输出|保存为|命名为|output(?:_name)?\s*[:=]?)\s*(?:是|为|=|:|：)?\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", str(prompt or ""), flags=re.IGNORECASE)
    return match.group(1).strip(" ，,。.;；") if match else ""


def _validation_method(prompt: str) -> str:
    text = str(prompt or "").lower()
    if "空间分块" in text or "空间块" in text or "spatial block" in text or "spatial_block" in text:
        return "spatial_block"
    if "交叉验证" in text or "cross validation" in text or "cross-validation" in text or "cv" in text:
        return "cross_validation"
    if "空间分块" in text or "spatial block" in text or "spatial_block" in text:
        return "spatial_block"
    if "交叉验证" in text or "cross validation" in text or "cv" in text:
        return "cross_validation"
    return ""


def _requested_outputs(prompt: str) -> list[str]:
    text = str(prompt or "").lower()
    outputs: list[str] = []
    checks = [
        ("predictions", ("预测结果", "prediction", "predictions")),
        ("residuals", ("残差", "residual")),
        ("feature_importance", ("特征重要性", "feature importance")),
        ("metrics", ("精度指标", "指标", "metrics")),
        ("model_file", ("模型文件", "model file", "joblib", "pkl")),
    ]
    for name, terms in checks:
        if any(term in text for term in terms):
            outputs.append(name)
    return outputs


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
    wants_xgb = "xgboost" in text or "xgb" in text
    if wants_xgb and any(token in text for token in ("generic", "general", "universal", "通用", "分类", "classification", "classifier")):
        return "generic_xgboost"
    if "xgboost" in text or "xgb" in text:
        return "xgboost"
    if "random forest" in text or re.search(r"\brf\b", text):
        return "random_forest"
    if "regression" in text or "predict" in text or "forecast" in text:
        return "regression"
    return ""


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
        target = _field_after_label(text, ("目标列", "目标变量", "预测列", "预测字段", "target_col", "target", "label"), fields) or _target_after_predict(text, fields)
        semantic = match_user_field_concept(text, fields)
        slots.target_concept = str(semantic.get("concept") or "")
        slots.candidate_fields = [item for item in semantic.get("candidates", []) if isinstance(item, dict)]
        if target:
            slots.target_variable = target
        elif semantic.get("best_field") and not semantic.get("needs_clarification"):
            slots.target_variable = str(semantic["best_field"])
        explicit_features = _feature_fields_from_prompt(text, fields)
        features = explicit_features or [field for field in mentioned if field != slots.target_variable]
        numeric_set = set(numeric_fields or fields)
        slots.feature_fields = [field for field in features if field in numeric_set]
        slots.time_column = _field_after_label(text, ("时间列", "时间字段", "date_col", "time_column"), fields)
        slots.validation_method = _validation_method(text)
        slots.output_name = _output_name(text)
        slots.requested_outputs = _requested_outputs(text)
        spatial_columns = []
        for candidate in ("lon", "lng", "longitude", "x"):
            field = _field_lookup(fields).get(candidate)
            if field:
                spatial_columns.append(field)
                break
        for candidate in ("lat", "latitude", "y"):
            field = _field_lookup(fields).get(candidate)
            if field:
                spatial_columns.append(field)
                break
        slots.spatial_columns = spatial_columns
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
