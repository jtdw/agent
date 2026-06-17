from __future__ import annotations

import re
from typing import Any

from core.field_semantics import match_user_field_concept
from core.object_resolver import resolve_object_reference
from core.task_slots import extract_task_slots
from core.tool_contracts import ToolPrecondition
from core.tool_preconditions import (
    validate_dataset_exists,
    validate_model_target,
    validate_required_fields,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_dataset(context: dict[str, Any]) -> bool:
    return bool(context.get("active_dataset")) or int(_as_dict(context.get("workspace")).get("dataset_count") or 0) > 0


def _dataset_name(context: dict[str, Any]) -> str:
    dataset = context.get("active_dataset")
    if isinstance(dataset, dict):
        return str(dataset.get("name") or "")
    return ""


def _dataset_type(context: dict[str, Any], manager: Any | None = None) -> str:
    dataset = context.get("active_dataset")
    if isinstance(dataset, dict):
        data_type = str(dataset.get("type") or dataset.get("data_type") or "").lower()
        if data_type:
            return data_type
    dataset_name = _dataset_name(context)
    if manager is not None and dataset_name:
        try:
            return str(manager.get(dataset_name).data_type or "").lower()
        except Exception:
            return ""
    return ""


def _prompt_has_explicit_field_hint(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(
        token in text
        for token in (
            "字段",
            "列",
            "用 ",
            "按",
            "longitude",
            "latitude",
            "target",
            "目标变量",
            "经度",
            "纬度",
            "瀛楁",
            "鐩爣鍙橀噺",
        )
    )


def _prompt_has_target_hint(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(
        token in text
        for token in (
            "目标变量",
            "target",
            "因变量",
            "soil_moisture",
            "y=",
            "label",
            "预测字段",
            "预测列",
            "鐩爣鍙橀噺",
            "棰勬祴瀛楁",
        )
    )


def _default_plan(task_type: str) -> dict[str, Any]:
    return {
        "task_type": task_type,
        "required_inputs": [],
        "missing_inputs": [],
        "recommended_tools": [],
        "tool_preconditions": {},
        "execution_steps": [],
        "expected_outputs": [],
        "should_ask_clarification": False,
        "clarification_question": "",
        "resolved_fields": {},
        "resolved_objects": {},
        "slots": {},
        "tool_plan": [],
        "validated_tool_args": {},
        "workflow_plan": [],
        "slot_validation_errors": [],
    }


def _semantic_candidates(context: dict[str, Any], prompt: str) -> dict[str, Any]:
    existing = context.get("semantic_field_candidates")
    if isinstance(existing, dict):
        return existing
    fields = context.get("available_fields")
    if isinstance(fields, list):
        return match_user_field_concept(prompt, fields)
    return match_user_field_concept(prompt, [])


def _field_candidate_question(kind: str, candidates: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for item in candidates[:5]:
        field = str(item.get("field") or "")
        if not field:
            continue
        score = item.get("score")
        labels.append(f"{field}({score})" if score is not None else field)
    candidate_text = "、".join(labels) if labels else "暂无候选字段"
    if kind == "map":
        return f"我找到了多个可能的制图字段候选：{candidate_text}。请确认要使用哪一个字段。"
    return f"我找到了多个可能的目标变量候选：{candidate_text}。请确认要预测哪一个字段。"


def _resolve_semantic_field_for_plan(
    plan: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
    *,
    field_key: str,
    kind: str,
) -> bool:
    semantic = _semantic_candidates(context, prompt)
    best_field = str(semantic.get("best_field") or "")
    candidates = [item for item in semantic.get("candidates", []) if isinstance(item, dict)]
    confidence = float(semantic.get("confidence") or 0.0)
    if not best_field:
        return False
    if confidence >= 0.78 and not bool(semantic.get("needs_clarification")):
        plan.setdefault("resolved_fields", {})[field_key] = best_field
        plan["resolved_fields"][f"{field_key}_source_concept"] = semantic.get("concept") or ""
        plan["resolved_fields"][f"{field_key}_confidence"] = round(confidence, 3)
        label = "制图字段" if kind == "map" else "目标变量"
        plan["execution_steps"].append(f"根据字段语义匹配，将使用候选{label} {best_field}。")
        return True
    if candidates:
        _add_missing_inputs(plan, [field_key], _field_candidate_question(kind, candidates))
        plan.setdefault("field_candidates", {})[field_key] = candidates[:5]
        return True
    return False


def _slot_context(context: dict[str, Any], dataset: str, referenced_object: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    state = {"active_dataset": dataset}
    if isinstance(referenced_object, dict):
        state["referenced_object"] = referenced_object
    workspace = dict(context)
    workspace_summary = _as_dict(context.get("workspace"))
    if "dataset_count" in workspace_summary:
        workspace["dataset_count"] = workspace_summary.get("dataset_count")
    return state, workspace


def _seed_resolved_fields_from_slots(plan: dict[str, Any], slots: dict[str, Any]) -> None:
    if slots.get("target_field"):
        plan.setdefault("resolved_fields", {})["map_field"] = slots["target_field"]
        plan["resolved_fields"]["map_field_source_concept"] = slots.get("target_concept") or ""
        plan["resolved_fields"]["map_field_confidence"] = slots.get("confidence") or 0.0
    if slots.get("target_variable"):
        plan.setdefault("resolved_fields", {})["target_col"] = slots["target_variable"]
    feature_fields = slots.get("feature_fields")
    if isinstance(feature_fields, list) and feature_fields:
        plan.setdefault("resolved_fields", {})["feature_fields"] = [str(field) for field in feature_fields]


def _resolve_objects_for_plan(prompt: str, context: dict[str, Any], manager: Any | None = None) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for object_type in ("dataset", "layer", "field", "clip_boundary", "artifact", "model_result"):
        result = resolve_object_reference(prompt, context, manager=manager, object_type=object_type)
        if result.get("ok") or result.get("needs_clarification"):
            resolved[object_type] = result
    return resolved


def _apply_resolved_field(plan: dict[str, Any], resolved_objects: dict[str, Any], *, field_key: str, kind: str) -> bool:
    field_result = resolved_objects.get("field")
    if not isinstance(field_result, dict):
        return False
    if field_result.get("ok") and field_result.get("name"):
        plan.setdefault("resolved_fields", {})[field_key] = str(field_result["name"])
        plan["resolved_fields"][f"{field_key}_source_concept"] = str(_as_dict(field_result.get("data")).get("semantic", {}).get("concept") or "")
        plan["resolved_fields"][f"{field_key}_confidence"] = float(field_result.get("confidence") or 0.0)
        return True
    if field_result.get("needs_clarification"):
        candidates = [item for item in field_result.get("candidates", []) if isinstance(item, dict)]
        _add_missing_inputs(plan, [field_key], _field_candidate_question(kind, candidates))
        plan.setdefault("field_candidates", {})[field_key] = candidates[:5]
        return True
    return False


def _safe_output_prefix(dataset: str, suffix: str) -> str:
    base = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(dataset or "result")).strip("_")
    return f"{base or 'result'}_{suffix}"


def _validate_slot_field_membership(plan: dict[str, Any], context: dict[str, Any], fields: list[str]) -> bool:
    available = {str(field) for field in context.get("available_fields", []) if str(field or "").strip()}
    missing = [field for field in fields if field and field not in available]
    if not missing:
        return True
    plan["slot_validation_errors"].append(
        {
            "error_code": "SLOT_FIELD_NOT_AVAILABLE",
            "missing_fields": missing,
            "available_fields": sorted(available),
        }
    )
    _add_missing_inputs(plan, ["field"], f"字段 {', '.join(missing)} 不在当前数据集中，请从可用字段中选择。")
    return False


def _manager_precondition_errors(manager: Any | None, tool_name: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    if manager is None:
        return []
    errors: list[dict[str, Any]] = []
    dataset_name = str(args.get("dataset_name") or "")
    if dataset_name:
        errors.extend(validate_dataset_exists(manager, dataset_name))
    if tool_name == "plot_dataset" and args.get("column"):
        errors.extend(validate_required_fields(manager, dataset_name, [str(args["column"])]))
    elif tool_name in {"train_xgboost_fusion_model", "train_rf_fusion_model"}:
        target = str(args.get("target_col") or "")
        features = [field.strip() for field in str(args.get("feature_cols") or "").split(",") if field.strip()]
        errors.extend(validate_model_target(manager, dataset_name, target))
        errors.extend(validate_required_fields(manager, dataset_name, features))
    elif tool_name == "vector_clip_by_vector":
        errors.extend(validate_dataset_exists(manager, str(args.get("clip_name") or "")))
    elif tool_name == "export_dataset":
        errors.extend(validate_dataset_exists(manager, dataset_name))
    return errors


def _accept_tool_args(plan: dict[str, Any], manager: Any | None, tool_name: str, args: dict[str, Any]) -> None:
    errors = _manager_precondition_errors(manager, tool_name, args)
    if errors:
        plan["slot_validation_errors"].extend(errors)
        first = errors[0]
        _add_missing_inputs(
            plan,
            ["tool preconditions"],
            str(first.get("user_message") or "工具参数未通过前置条件校验，请补充或更正输入。"),
        )
        return
    plan["validated_tool_args"][tool_name] = args
    plan["tool_plan"].append({"tool_name": tool_name, "args": args})


def _remove_tool_args(plan: dict[str, Any], tool_name: str) -> None:
    validated = plan.get("validated_tool_args")
    if isinstance(validated, dict):
        validated.pop(tool_name, None)
    tool_plan = plan.get("tool_plan")
    if isinstance(tool_plan, list):
        plan["tool_plan"] = [item for item in tool_plan if not (isinstance(item, dict) and item.get("tool_name") == tool_name)]


def _build_validated_tool_args(plan: dict[str, Any], slots: dict[str, Any], context: dict[str, Any], manager: Any | None = None) -> None:
    if plan.get("should_ask_clarification"):
        return
    dataset = str(slots.get("dataset_id") or _dataset_name(context) or "")
    task_type = str(slots.get("task_type") or plan.get("task_type") or "")
    if task_type == "data_upload_analysis":
        if not dataset:
            return
        args = {"dataset_name": dataset}
        _accept_tool_args(plan, manager, "describe_dataset", args)
    elif task_type == "map_generation":
        column = str(slots.get("target_field") or plan.get("resolved_fields", {}).get("map_field") or "")
        if not dataset or not column:
            return
        if not _validate_slot_field_membership(plan, context, [column]) or plan.get("should_ask_clarification"):
            return
        args = {
            "dataset_name": dataset,
            "column": column,
            "title": str(slots.get("target_concept") or column),
            "output_name": _safe_output_prefix(dataset, "map.png"),
        }
        _accept_tool_args(plan, manager, "plot_dataset", args)
        plan["execution_steps"].append(f"根据任务槽位解析，将使用字段 {column}。")
    elif task_type == "modeling":
        target = str(slots.get("target_variable") or plan.get("resolved_fields", {}).get("target_col") or "")
        features = slots.get("feature_fields") or plan.get("resolved_fields", {}).get("feature_fields") or []
        features = [str(field) for field in features if str(field or "").strip()]
        if not dataset or not target or not features:
            if not target:
                _add_missing_inputs(plan, ["target column"])
            if not features:
                _add_missing_inputs(plan, ["feature columns"])
            return
        if not _validate_slot_field_membership(plan, context, [target, *features]) or plan.get("should_ask_clarification"):
            return
        model_tool = "train_rf_fusion_model" if slots.get("model_type") == "random_forest" else "train_xgboost_fusion_model"
        args = {
            "dataset_name": dataset,
            "target_col": target,
            "feature_cols": ",".join(features),
            "output_name": _safe_output_prefix(dataset, "model"),
        }
        _accept_tool_args(plan, manager, model_tool, args)
    elif task_type == "data_processing" and slots.get("spatial_operation") == "clip":
        ref = slots.get("referenced_artifact") if isinstance(slots.get("referenced_artifact"), dict) else {}
        resolved_clip = _as_dict(_as_dict(plan.get("resolved_objects")).get("clip_boundary"))
        clip_name = str(
            _as_dict(resolved_clip.get("data")).get("dataset_id")
            or resolved_clip.get("name")
            or ref.get("name")
            or ref.get("dataset_id")
            or ref.get("id")
            or ""
        )
        if not dataset or not clip_name:
            if not dataset:
                _add_missing_inputs(plan, ["dataset"])
            if not clip_name:
                _add_missing_inputs(plan, ["clip layer"])
            return
        args = {
            "dataset_name": dataset,
            "clip_name": clip_name,
            "output_name": _safe_output_prefix(dataset, "clipped"),
        }
        _accept_tool_args(plan, manager, "vector_clip_by_vector", args)
    elif slots.get("output_format") and dataset:
        suffix = ".csv" if "table" in str(slots.get("output_format")) else ".png"
        args = {"dataset_name": dataset, "output_path": f"exports/{_safe_output_prefix(dataset, 'export')}{suffix}"}
        _accept_tool_args(plan, manager, "export_dataset", args)


def _prompt_requests_map(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(
        token in text
        for token in (
            "map",
            "plot",
            "\u5236\u56fe",
            "\u753b\u56fe",
            "\u753b",
            "\u5730\u56fe",
            "\u5206\u5e03\u56fe",
            "\u4e13\u9898\u56fe",
            "\u53ef\u89c6\u5316",
            "鍦板浘",
            "鐢诲浘",
        )
    )


def _prompt_requests_interpretation(prompt: str, secondary_intents: list[str]) -> bool:
    text = str(prompt or "").lower()
    return "result_analysis" in secondary_intents or any(token in text for token in ("explain", "interpret", "解释", "说明", "解读", "怎么看", "瑙ｉ噴"))


def _prompt_requests_export(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(token in text for token in ("export", "save", "download", "导出", "保存", "瀵煎嚭"))


def _export_suffix(prompt: str, *, default: str = "") -> str:
    text = str(prompt or "").lower()
    if any(token in text for token in ("geojson", ".geojson")):
        return ".geojson"
    if any(token in text for token in ("shp", "shapefile", ".shp")):
        return ".shp"
    if any(token in text for token in ("csv", ".csv", "table", "表格")):
        return ".csv"
    if any(token in text for token in ("xlsx", "excel", ".xlsx")):
        return ".xlsx"
    if any(token in text for token in ("png", ".png", "image", "图片", "图件")):
        return ".png"
    return default


def _export_path(manager: Any | None, stem: str, suffix: str) -> str:
    filename = f"{_safe_output_prefix(stem, 'export')}{suffix or '.dat'}"
    if manager is not None and hasattr(manager, "derived_dir"):
        return str(manager.derived_dir / "exports" / filename)
    return f"exports/{filename}"


def _prompt_requests_gcp(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(
        token in text
        for token in (
            "gcp",
            "conformal",
            "uncertainty",
            "prediction interval",
            "prediction intervals",
            "不确定性",
            "共形预测",
            "预测区间",
        )
    )


def _recent_model_for_gcp(context: dict[str, Any], resolved_objects: dict[str, Any]) -> dict[str, Any]:
    resolved = _as_dict(_as_dict(resolved_objects.get("model_result")).get("data"))
    if resolved:
        return resolved
    return _as_dict(context.get("recent_model_result"))


def _model_value(model: dict[str, Any], key: str) -> str:
    summary = _as_dict(model.get("summary"))
    diagnostics = _as_dict(model.get("diagnostics"))
    outputs = _as_dict(model.get("outputs"))
    value = model.get(key) or summary.get(key) or diagnostics.get(key) or outputs.get(key) or ""
    return str(value)


def _build_gcp_args_from_recent_model(model: dict[str, Any]) -> dict[str, Any]:
    output_prefix = str(model.get("output_prefix") or _model_value(model, "output_name") or "model")
    result_dataset = _model_value(model, "result_dataset") or output_prefix
    observed_col = _model_value(model, "target_col")
    predicted_col = (
        _model_value(model, "prediction_column")
        or _model_value(model, "cv_prediction_column")
        or (f"{output_prefix}_xgb" if output_prefix else "")
    )
    args = {
        "calibration_dataset": result_dataset,
        "observed_col": observed_col,
        "predicted_cols": predicted_col,
        "output_name": _safe_output_prefix(output_prefix, "gcp"),
        "calibration_ratio": 0.3,
        "alpha": 0.1,
    }
    date_col = _model_value(model, "date_col")
    if date_col:
        args["date_col"] = date_col
    return args


def _infer_date_field(context: dict[str, Any]) -> str:
    fields = [str(field) for field in context.get("available_fields", []) if str(field or "").strip()]
    for candidate in ("date", "time", "datetime", "日期", "时间"):
        for field in fields:
            if field.lower() == candidate.lower():
                return field
    for field in fields:
        lowered = field.lower()
        if "date" in lowered or "time" in lowered:
            return field
    return ""


def _build_gcp_workflow(plan: dict[str, Any], gcp_args: dict[str, Any]) -> bool:
    required = ["calibration_dataset", "observed_col", "predicted_cols", "output_name"]
    missing = [key for key in required if not str(gcp_args.get(key) or "").strip()]
    if missing:
        _add_missing_inputs(
            plan,
            missing,
            "请先完成一次模型预测，或明确提供 GCP 所需的结果数据集、观测列和预测列。",
        )
        return False

    plan["should_ask_clarification"] = False
    plan["missing_inputs"] = []
    plan["clarification_question"] = ""
    plan["recommended_tools"] = ["geographical_conformal_prediction"]
    plan["required_inputs"] = ["model prediction result", "observed column", "prediction column"]
    plan["execution_steps"] = [
        "读取最近一次模型预测结果。",
        "使用观测列与预测列执行 GCP 不确定性分析。",
        "输出预测区间、覆盖率、区间宽度和 GCP 指标表。",
    ]
    plan["expected_outputs"] = ["GCP interval dataset", "GCP metrics dataset", "GCP summary"]
    plan["validated_tool_args"]["geographical_conformal_prediction"] = gcp_args
    plan["tool_plan"].append({"tool_name": "geographical_conformal_prediction", "args": gcp_args})
    plan["workflow_plan"] = [
        {
            "step_id": "run_gcp",
            "tool_name": "geographical_conformal_prediction",
            "step_type": "uncertainty_analysis",
            "validated_tool_args": gcp_args,
            "expected_outputs": ["model_result_id", "result_dataset", "metrics_dataset"],
            "stop_on_failure": True,
        },
        {
            "step_id": "interpret_gcp_result",
            "tool_name": "interpret_result",
            "validated_tool_args": {"referenced_step": "run_gcp"},
            "depends_on": ["run_gcp"],
            "expected_outputs": ["GCP result explanation"],
            "stop_on_failure": False,
        },
    ]
    return True


def _build_modeling_workflow(plan: dict[str, Any], prompt: str, secondary_intents: list[str], manager: Any | None = None) -> bool:
    validated = _as_dict(plan.get("validated_tool_args"))
    model_tool = "train_rf_fusion_model" if "train_rf_fusion_model" in validated else "train_xgboost_fusion_model" if "train_xgboost_fusion_model" in validated else ""
    if not model_tool:
        return False
    model_args = validated[model_tool]
    map_requested = _prompt_requests_map(prompt)
    workflow = [
        {"step_id": "check_dataset", "tool_name": "describe_dataset", "validated_tool_args": {"dataset_name": str(model_args.get("dataset_name") or "")}, "expected_outputs": ["dataset summary"], "stop_on_failure": True},
        {
            "step_id": "field_match",
            "tool_name": "field_match",
            "validated_tool_args": {"target_col": model_args.get("target_col"), "feature_cols": model_args.get("feature_cols"), "resolved_fields": plan.get("resolved_fields", {})},
            "depends_on": ["check_dataset"],
            "expected_outputs": ["resolved model fields"],
            "stop_on_failure": True,
        },
        {
            "step_id": "train_model",
            "tool_name": model_tool,
            "step_type": "modeling",
            "validated_tool_args": model_args,
            "depends_on": ["field_match"],
            "expected_outputs": ["model_result_id", "result_dataset", "metrics_dataset"],
            "stop_on_failure": True,
        },
    ]
    if map_requested:
        workflow.append(
            {
                "step_id": "generate_prediction_map",
                "tool_name": "plot_dataset",
                "step_type": "map_generation",
                "validated_tool_args": {
                    "dataset_name": "$steps.train_model.outputs.result_dataset",
                    "column": "$steps.train_model.outputs.prediction_column",
                    "title": "model prediction",
                    "output_name": _safe_output_prefix(str(model_args.get("output_name") or "model"), "prediction_map.png"),
                },
                "depends_on": ["train_model"],
                "expected_outputs": ["prediction map artifact"],
                "stop_on_failure": True,
            }
        )
    workflow.append(
        {
            "step_id": "interpret_model_result",
            "tool_name": "interpret_result",
            "validated_tool_args": {"referenced_step": "train_model"},
            "depends_on": ["generate_prediction_map" if map_requested else "train_model"],
            "expected_outputs": ["model result explanation"],
            "stop_on_failure": False,
        }
    )
    if _prompt_requests_export(prompt):
        suffix = _export_suffix(prompt, default=".csv")
        if suffix == ".png" and map_requested:
            workflow.append(
                {
                    "step_id": "export_map",
                    "tool_name": "export_artifact",
                    "step_type": "export_map",
                    "validated_tool_args": {"source_path": "$steps.generate_prediction_map.artifacts.0.path", "output_path": _export_path(manager, str(model_args.get("output_name") or "model_prediction"), ".png")},
                    "depends_on": ["generate_prediction_map"],
                    "expected_outputs": ["exported map"],
                    "stop_on_failure": True,
                }
            )
        else:
            workflow.append(
                {
                    "step_id": "export_prediction_table",
                    "tool_name": "export_dataset",
                    "step_type": "export_table",
                    "validated_tool_args": {"dataset_name": "$steps.train_model.outputs.result_dataset", "output_path": _export_path(manager, str(model_args.get("output_name") or "model_prediction"), suffix)},
                    "depends_on": ["train_model"],
                    "expected_outputs": ["exported prediction dataset"],
                    "stop_on_failure": True,
                }
            )
    plan["workflow_plan"] = workflow
    return True


def _field_by_alias(fields: list[Any], aliases: tuple[str, ...]) -> str:
    lowered = {str(field).lower(): str(field) for field in fields if str(field or "").strip()}
    for alias in aliases:
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    for field in lowered.values():
        normalized = field.lower().replace("_", "").replace("-", "")
        if any(alias.lower().replace("_", "").replace("-", "") == normalized for alias in aliases):
            return field
    return ""


def _first_dataset_by_type(context: dict[str, Any], dataset_type: str) -> str:
    for item in context.get("available_datasets") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or item.get("data_type") or "").lower() == dataset_type:
            return str(item.get("name") or item.get("dataset_id") or "")
    return ""


def _available_dataset_names_by_type(context: dict[str, Any], dataset_type: str) -> list[str]:
    names: list[str] = []
    active = context.get("active_dataset")
    if isinstance(active, dict) and str(active.get("type") or active.get("data_type") or "").lower() == dataset_type:
        name = str(active.get("name") or active.get("dataset_id") or "")
        if name:
            names.append(name)
    for item in context.get("available_datasets") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or item.get("data_type") or "").lower() != dataset_type:
            continue
        name = str(item.get("name") or item.get("dataset_id") or "")
        if name and name not in names:
            names.append(name)
    return names


def _active_or_first_raster(context: dict[str, Any]) -> str:
    if _dataset_type(context) == "raster":
        dataset = _dataset_name(context)
        if dataset:
            return dataset
    return _first_dataset_by_type(context, "raster")


def _prompt_requests_dem_derivatives(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(token in text for token in ("slope", "aspect", "terrain", "坡度", "坡向", "地形因子", "地形"))


def _prompt_requests_raster_reproject(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(token in text for token in ("reproject", "projection", "crs", "epsg", "重投影", "投影转换", "坐标系转换"))


def _prompt_requests_raster_algebra(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(token in text for token in ("ndvi", "raster algebra", "map algebra", "栅格代数", "波段计算", "归一化植被指数"))


def _target_crs_from_prompt(prompt: str) -> str:
    match = re.search(r"epsg\s*[:：]?\s*(\d{3,6})", str(prompt or ""), flags=re.IGNORECASE)
    return f"EPSG:{match.group(1)}" if match else ""


def _dem_derivatives_from_prompt(prompt: str) -> str:
    text = str(prompt or "").lower()
    derivatives: list[str] = []
    if "slope" in text or "坡度" in text:
        derivatives.append("slope")
    if "aspect" in text or "坡向" in text:
        derivatives.append("aspect")
    if "terrain" in text or "地形" in text:
        for item in ("slope", "aspect", "terrain"):
            if item not in derivatives:
                derivatives.append(item)
    return ",".join(derivatives or ["slope", "aspect"])


def _raster_dataset_for_variable(variable: str, raster_names: list[str]) -> str:
    key = re.sub(r"[^0-9a-z]+", "", str(variable or "").lower())
    for name in raster_names:
        normalized = re.sub(r"[^0-9a-z]+", "", name.lower())
        if key and key in normalized:
            return name
    return ""


def _raster_algebra_args_from_prompt(prompt: str, context: dict[str, Any]) -> dict[str, str]:
    raw = str(prompt or "")
    text = raw.lower()
    output_name = "ndvi" if "ndvi" in text or "归一化植被指数" in raw else "raster_algebra"
    expression = ""
    if "=" in raw:
        expression = raw.split("=", 1)[1].strip()
    if not expression and output_name == "ndvi":
        expression = "(nir - red) / (nir + red)"
    expression = expression.lower()
    variables = sorted({item for item in re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", expression) if item not in {"np", "where", "clip", "log", "sqrt", "abs", "minimum", "maximum"}})
    raster_names = _available_dataset_names_by_type(context, "raster")
    mapping: list[str] = []
    for variable in variables:
        dataset_name = _raster_dataset_for_variable(variable, raster_names)
        if dataset_name:
            mapping.append(f"{variable}={dataset_name}")
    return {"expression": expression, "input_rasters": ",".join(mapping), "output_name": output_name}


def _prompt_requests_dem_derivatives(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(
        token in text
        for token in (
            "slope",
            "aspect",
            "terrain",
            "dem",
            "\u5761\u5ea6",
            "\u5761\u5411",
            "\u5730\u5f62\u56e0\u5b50",
            "\u5730\u5f62",
        )
    )


def _prompt_requests_raster_mosaic(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(token in text for token in ("mosaic", "merge raster", "\u62fc\u63a5", "\u5408\u5e76", "\u9576\u5d4c", "\u5206\u5e45"))


def _prompt_requests_raster_reproject(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(token in text for token in ("reproject", "projection", "crs", "epsg", "\u91cd\u6295\u5f71", "\u6295\u5f71\u8f6c\u6362", "\u5750\u6807\u7cfb\u8f6c\u6362"))


def _prompt_requests_raster_algebra(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(token in text for token in ("ndvi", "raster algebra", "map algebra", "\u6805\u683c\u4ee3\u6570", "\u6ce2\u6bb5\u8ba1\u7b97", "\u5f52\u4e00\u5316\u690d\u88ab\u6307\u6570"))


def _target_crs_from_prompt(prompt: str) -> str:
    match = re.search(r"epsg\s*[:\uff1a]?\s*(\d{3,6})", str(prompt or ""), flags=re.IGNORECASE)
    return f"EPSG:{match.group(1)}" if match else ""


def _dem_derivatives_from_prompt(prompt: str) -> str:
    text = str(prompt or "").lower()
    derivatives: list[str] = []
    if "slope" in text or "\u5761\u5ea6" in text:
        derivatives.append("slope")
    if "aspect" in text or "\u5761\u5411" in text:
        derivatives.append("aspect")
    if "terrain" in text or "\u5730\u5f62" in text:
        for item in ("slope", "aspect", "terrain"):
            if item not in derivatives:
                derivatives.append(item)
    return ",".join(derivatives or ["slope", "aspect"])


def _prompt_requests_table_to_points_and_raster_extract(prompt: str) -> bool:
    text = str(prompt or "").lower()
    point_request = any(token in text for token in ("table to points", "to points", "\u8f6c\u6210\u70b9", "\u8f6c\u70b9", "\u751f\u6210\u70b9"))
    raster_request = any(token in text for token in ("extract raster", "raster value", "\u63d0\u53d6", "\u6805\u683c\u503c", "\u6805\u683c"))
    return point_request and raster_request


def _build_table_points_map_workflow(
    plan: dict[str, Any],
    prompt: str,
    context: dict[str, Any],
    secondary_intents: list[str],
    manager: Any | None = None,
) -> bool:
    if _dataset_type(context, manager) != "table":
        return False
    if not _prompt_requests_map(prompt) and str(plan.get("task_type") or "") != "map_generation":
        return False

    _remove_tool_args(plan, "plot_dataset")

    dataset = _dataset_name(context)
    fields = context.get("available_fields") if isinstance(context.get("available_fields"), list) else []
    x_col = _field_by_alias(fields, ("lon", "lng", "long", "longitude", "x", "\u7ecf\u5ea6"))
    y_col = _field_by_alias(fields, ("lat", "latitude", "y", "\u7eac\u5ea6"))
    missing: list[str] = []
    if not dataset:
        missing.append("table dataset")
    if not x_col or not y_col:
        missing.append("coordinate field")
    if missing:
        _add_missing_inputs(
            plan,
            missing,
            "Please confirm the table dataset and its longitude/latitude fields before I convert it to points and map it.",
        )
        return True

    if not plan.get("resolved_fields", {}).get("map_field"):
        _resolve_semantic_field_for_plan(plan, prompt, context, field_key="map_field", kind="map")
    if plan.get("should_ask_clarification"):
        return True

    column = str(plan.get("resolved_fields", {}).get("map_field") or "")
    if not column:
        _add_missing_inputs(
            plan,
            ["map field"],
            "Please specify which numeric field to map after converting the CSV table to points.",
        )
        return True
    if not _validate_slot_field_membership(plan, context, [column]) or plan.get("should_ask_clarification"):
        return True

    point_name = _safe_output_prefix(dataset, "points")
    plan["validated_tool_args"]["table_to_points"] = {
        "dataset_name": dataset,
        "x_col": x_col,
        "y_col": y_col,
        "crs": "EPSG:4326",
        "output_name": point_name,
    }
    plan["validated_tool_args"]["plot_dataset"] = {
        "dataset_name": "$steps.make_points.outputs.result_dataset",
        "column": column,
        "title": str(plan.get("resolved_fields", {}).get("map_field_source_concept") or column),
        "output_name": _safe_output_prefix(dataset, "points_map.png"),
    }
    workflow = [
        {
            "step_id": "make_points",
            "tool_name": "table_to_points",
            "step_type": "data_processing",
            "validated_tool_args": plan["validated_tool_args"]["table_to_points"],
            "expected_outputs": ["point dataset"],
            "stop_on_failure": True,
        },
        {
            "step_id": "generate_map",
            "tool_name": "plot_dataset",
            "step_type": "map_generation",
            "depends_on": ["make_points"],
            "validated_tool_args": plan["validated_tool_args"]["plot_dataset"],
            "expected_outputs": ["map artifact"],
            "stop_on_failure": True,
        },
    ]
    if _prompt_requests_interpretation(prompt, secondary_intents):
        workflow.append(
            {
                "step_id": "interpret_map_result",
                "tool_name": "interpret_result",
                "validated_tool_args": {"referenced_step": "generate_map"},
                "depends_on": ["generate_map"],
                "expected_outputs": ["result explanation"],
                "stop_on_failure": False,
            }
        )
    plan["workflow_plan"] = workflow
    return True


def _build_table_raster_extraction_workflow(plan: dict[str, Any], prompt: str, context: dict[str, Any]) -> bool:
    if str(plan.get("task_type") or "") != "data_processing":
        return False
    if not _prompt_requests_table_to_points_and_raster_extract(prompt):
        return False
    dataset = _dataset_name(context)
    fields = context.get("available_fields") if isinstance(context.get("available_fields"), list) else []
    x_col = _field_by_alias(fields, ("lon", "lng", "long", "longitude", "x", "\u7ecf\u5ea6"))
    y_col = _field_by_alias(fields, ("lat", "latitude", "y", "\u7eac\u5ea6"))
    raster_name = _first_dataset_by_type(context, "raster")
    missing: list[str] = []
    if not dataset:
        missing.append("table dataset")
    if not x_col:
        missing.append("x coordinate field")
    if not y_col:
        missing.append("y coordinate field")
    if not raster_name:
        missing.append("raster dataset")
    if missing:
        _add_missing_inputs(plan, missing)
        return True
    point_name = _safe_output_prefix(dataset, "points")
    field_name = f"{raster_name}_value"
    plan["validated_tool_args"]["table_to_points"] = {
        "dataset_name": dataset,
        "x_col": x_col,
        "y_col": y_col,
        "crs": "EPSG:4326",
        "output_name": point_name,
    }
    plan["validated_tool_args"]["extract_raster_values_to_points"] = {
        "point_name": "$steps.make_points.outputs.result_dataset",
        "raster_name": raster_name,
        "output_name": _safe_output_prefix(dataset, "raster_values"),
        "field_name": field_name,
    }
    plan["workflow_plan"] = [
        {
            "step_id": "make_points",
            "tool_name": "table_to_points",
            "step_type": "data_processing",
            "validated_tool_args": plan["validated_tool_args"]["table_to_points"],
            "expected_outputs": ["point dataset"],
            "stop_on_failure": True,
        },
        {
            "step_id": "extract_raster_values",
            "tool_name": "extract_raster_values_to_points",
            "step_type": "data_processing",
            "depends_on": ["make_points"],
            "validated_tool_args": plan["validated_tool_args"]["extract_raster_values_to_points"],
            "expected_outputs": ["sampled point dataset"],
            "stop_on_failure": True,
        },
    ]
    return True


def _build_raster_processing_workflow(plan: dict[str, Any], prompt: str, context: dict[str, Any], manager: Any | None = None) -> bool:
    if str(plan.get("task_type") or "") != "data_processing":
        return False

    raster_name = _active_or_first_raster(context)
    workflow_tool = ""
    args: dict[str, Any] = {}
    step_id = ""
    expected_outputs: list[str] = []

    if _prompt_requests_raster_mosaic(prompt):
        raster_names = _available_dataset_names_by_type(context, "raster")
        if len(raster_names) < 2:
            _add_missing_inputs(plan, ["two or more raster datasets"])
            return True
        workflow_tool = "raster_mosaic"
        step_id = "mosaic_rasters"
        args = {
            "raster_names": ",".join(raster_names),
            "output_name": "dem_mosaic" if any("dem" in name.lower() for name in raster_names) else _safe_output_prefix(raster_names[0], "mosaic"),
            "vector_name": "",
            "method": "first",
        }
        expected_outputs = ["mosaic raster"]
    elif _prompt_requests_dem_derivatives(prompt):
        if not raster_name:
            _add_missing_inputs(plan, ["raster dataset"])
            return True
        workflow_tool = "dem_terrain_derivatives"
        step_id = "derive_dem_terrain"
        args = {
            "dem_name": raster_name,
            "output_prefix": raster_name,
            "derivatives": _dem_derivatives_from_prompt(prompt),
        }
        expected_outputs = ["slope raster", "aspect raster"]
    elif _prompt_requests_raster_reproject(prompt):
        target_crs = _target_crs_from_prompt(prompt)
        if not raster_name or not target_crs:
            missing = []
            if not raster_name:
                missing.append("raster dataset")
            if not target_crs:
                missing.append("target CRS")
            _add_missing_inputs(plan, missing)
            return True
        workflow_tool = "raster_reproject"
        step_id = "reproject_raster"
        epsg_suffix = target_crs.split(":", 1)[-1]
        args = {
            "raster_name": raster_name,
            "target_crs": target_crs,
            "output_name": _safe_output_prefix(raster_name, epsg_suffix),
            "resampling": "bilinear",
        }
        expected_outputs = ["reprojected raster"]
    elif _prompt_requests_raster_algebra(prompt):
        args = _raster_algebra_args_from_prompt(prompt, context)
        if not args.get("expression") or not args.get("input_rasters"):
            missing = []
            if not args.get("expression"):
                missing.append("raster algebra expression")
            if not args.get("input_rasters"):
                missing.append("input rasters")
            _add_missing_inputs(plan, missing)
            return True
        workflow_tool = "raster_algebra"
        step_id = "calculate_raster_algebra"
        expected_outputs = ["derived raster"]
    else:
        return False

    _accept_tool_args(plan, manager, workflow_tool, args)
    if plan.get("should_ask_clarification"):
        return True
    plan["workflow_plan"] = [
        {
            "step_id": step_id,
            "tool_name": workflow_tool,
            "step_type": "data_processing",
            "validated_tool_args": args,
            "expected_outputs": expected_outputs,
            "stop_on_failure": True,
        }
    ]
    return True


def _build_workflow_plan(plan: dict[str, Any], prompt: str, context: dict[str, Any], secondary_intents: list[str], manager: Any | None = None) -> None:
    if plan.get("should_ask_clarification"):
        return
    if str(plan.get("task_type") or "") == "modeling" and _build_modeling_workflow(plan, prompt, secondary_intents, manager=manager):
        return
    if _build_table_points_map_workflow(plan, prompt, context, secondary_intents, manager=manager):
        return
    if _build_table_raster_extraction_workflow(plan, prompt, context):
        return
    if _build_raster_processing_workflow(plan, prompt, context, manager=manager):
        return
    clip_args = _as_dict(plan.get("validated_tool_args")).get("vector_clip_by_vector")
    if not isinstance(clip_args, dict):
        return
    map_requested = _prompt_requests_map(prompt)
    export_requested = _prompt_requests_export(prompt)
    if not map_requested and not export_requested:
        return
    if not plan.get("resolved_fields", {}).get("map_field") and not _resolve_semantic_field_for_plan(
        plan,
        prompt,
        context,
        field_key="map_field",
        kind="map",
    ) and map_requested:
        return
    if plan.get("should_ask_clarification"):
        return
    column = str(plan.get("resolved_fields", {}).get("map_field") or "")
    if map_requested and not column:
        return
    output_name = _safe_output_prefix(str(clip_args.get("output_name") or clip_args.get("dataset_name") or "result"), "map.png")
    workflow = [
        {
            "step_id": "check_dataset",
            "tool_name": "describe_dataset",
            "validated_tool_args": {"dataset_name": str(clip_args.get("dataset_name") or "")},
            "expected_outputs": ["dataset summary"],
            "stop_on_failure": True,
        },
        {
            "step_id": "clip_vector",
            "tool_name": "vector_clip_by_vector",
            "validated_tool_args": clip_args,
            "depends_on": ["check_dataset"],
            "expected_outputs": ["result_dataset", "feature_count"],
            "stop_on_failure": True,
        },
    ]
    if map_requested:
        workflow.append(
            {
                "step_id": "generate_map",
                "tool_name": "plot_dataset",
                "validated_tool_args": {
                    "dataset_name": "$steps.clip_vector.outputs.result_dataset",
                    "column": column,
                    "title": str(plan.get("resolved_fields", {}).get("map_field_source_concept") or column),
                    "output_name": output_name,
                },
                "depends_on": ["clip_vector"],
                "expected_outputs": ["map artifact"],
                "stop_on_failure": True,
            }
        )
    if _prompt_requests_interpretation(prompt, secondary_intents):
        workflow.append(
            {
                "step_id": "interpret_map_result",
                "tool_name": "interpret_result",
                "validated_tool_args": {"referenced_step": "generate_map"},
                "depends_on": ["generate_map"],
                "expected_outputs": ["result explanation"],
                "stop_on_failure": False,
            }
        )
    if export_requested:
        suffix = _export_suffix(prompt, default=".geojson")
        if suffix == ".png" and map_requested:
            workflow.append(
                {
                    "step_id": "export_map",
                    "tool_name": "export_artifact",
                    "step_type": "export_map",
                    "validated_tool_args": {"source_path": "$steps.generate_map.artifacts.0.path", "output_path": _export_path(manager, str(clip_args.get("output_name") or "map"), ".png")},
                    "depends_on": ["generate_map"],
                    "expected_outputs": ["exported map artifact"],
                    "stop_on_failure": True,
                }
            )
        else:
            workflow.append(
                {
                    "step_id": "export_vector",
                    "tool_name": "export_dataset",
                    "step_type": "export_vector",
                    "validated_tool_args": {"dataset_name": "$steps.clip_vector.outputs.result_dataset", "output_path": _export_path(manager, str(clip_args.get("output_name") or "clipped"), suffix)},
                    "depends_on": ["clip_vector"],
                    "expected_outputs": ["exported vector dataset"],
                    "stop_on_failure": True,
                }
            )
    plan["workflow_plan"] = workflow


def _attach_tool_preconditions(plan: dict[str, Any]) -> None:
    specs = {
        "describe_dataset": ToolPrecondition(
            name="describe_dataset",
            required_inputs=["dataset_name"],
            optional_inputs=[],
        ),
        "plot_dataset": ToolPrecondition(
            name="plot_dataset",
            required_inputs=["dataset_name"],
            required_dataset_type="vector|raster",
            required_crs="required for vector plotting",
            required_fields=["column when thematic mapping is requested"],
            optional_inputs=["title", "output_name"],
        ),
        "train_xgboost_fusion_model": ToolPrecondition(
            name="train_xgboost_fusion_model",
            required_inputs=["dataset_name", "target_col", "feature_cols", "output_name"],
            required_dataset_type="table|vector",
            required_fields=["target_col", "feature_cols"],
            required_crs="required when spatial_validation=True and dataset is vector",
            required_geometry="Point when spatial_validation=True and dataset is vector",
            optional_inputs=["date_col", "split_date", "spatial_validation", "model hyperparameters"],
        ),
        "table_to_points": ToolPrecondition(
            name="table_to_points",
            required_inputs=["dataset_name", "x_col", "y_col", "crs", "output_name"],
            required_dataset_type="table",
            required_fields=["x_col", "y_col"],
            required_crs="required as output CRS",
            optional_inputs=[],
        ),
        "vector_clip_by_vector": ToolPrecondition(
            name="vector_clip_by_vector",
            required_inputs=["dataset_name", "clip_name", "output_name"],
            required_dataset_type="vector",
            required_crs="required for both source and clip layer",
            required_geometry="valid vector geometry",
            optional_inputs=[],
        ),
        "vector_overlay": ToolPrecondition(
            name="vector_overlay",
            required_inputs=["dataset_name", "overlay_name", "how", "output_name"],
            required_dataset_type="vector + vector",
            required_crs="required for both vector layers",
            required_geometry="valid vector geometry",
            optional_inputs=["how: intersection|union|difference|identity|symmetric_difference"],
        ),
        "vector_dissolve": ToolPrecondition(
            name="vector_dissolve",
            required_inputs=["dataset_name", "by_field", "output_name"],
            required_dataset_type="vector",
            required_fields=["by_field"],
            required_crs="required",
            required_geometry="valid vector geometry",
            optional_inputs=[],
        ),
        "vector_spatial_join": ToolPrecondition(
            name="vector_spatial_join",
            required_inputs=["target_name", "join_name", "predicate", "output_name"],
            required_dataset_type="vector + vector",
            required_crs="required for both vector layers",
            required_geometry="valid vector geometry",
            optional_inputs=["how: left|right|inner"],
        ),
        "summarize_points_within_polygons": ToolPrecondition(
            name="summarize_points_within_polygons",
            required_inputs=["point_name", "polygon_name", "output_name"],
            required_dataset_type="point vector + polygon vector",
            required_crs="required for both vector layers",
            required_geometry="Point + Polygon/MultiPolygon",
            optional_inputs=["count_field", "numeric_field", "stat"],
        ),
        "extract_raster_values_to_points": ToolPrecondition(
            name="extract_raster_values_to_points",
            required_inputs=["point_name", "raster_name", "output_name", "field_name"],
            required_dataset_type="point vector + raster",
            required_crs="required for point layer; raster must be readable",
            required_geometry="Point",
            optional_inputs=["band"],
        ),
        "clip_raster_by_vector": ToolPrecondition(
            name="clip_raster_by_vector",
            required_inputs=["raster_name", "vector_name", "output_name"],
            required_dataset_type="raster + vector",
            required_crs="required for both raster and vector",
            required_geometry="valid vector polygon or mask geometry",
            optional_inputs=[],
        ),
        "raster_histogram": ToolPrecondition(
            name="raster_histogram",
            required_inputs=["dataset_name", "band"],
            required_dataset_type="raster",
            optional_inputs=["output_name"],
        ),
        "raster_zonal_stats": ToolPrecondition(
            name="raster_zonal_stats",
            required_inputs=["raster_name", "polygon_name", "output_name"],
            required_dataset_type="raster + polygon vector",
            required_crs="required for raster and polygon layer",
            required_geometry="Polygon/MultiPolygon",
            optional_inputs=["stat", "band", "field_name"],
        ),
        "export_dataset": ToolPrecondition(
            name="export_dataset",
            required_inputs=["dataset_name", "output_path"],
            optional_inputs=[],
        ),
        "train_rf_fusion_model": ToolPrecondition(
            name="train_rf_fusion_model",
            required_inputs=["dataset_name", "target_col", "feature_cols", "output_name"],
            required_dataset_type="table|vector",
            required_fields=["target_col", "feature_cols"],
            optional_inputs=["date_col", "split_date", "model hyperparameters"],
        ),
    }
    plan["tool_preconditions"] = {
        tool_name: specs[tool_name].to_dict()
        for tool_name in plan.get("recommended_tools", [])
        if tool_name in specs
    }


def _add_missing_inputs(plan: dict[str, Any], missing_inputs: list[str], question: str | None = None) -> None:
    merged = list(dict.fromkeys([*plan.get("missing_inputs", []), *missing_inputs]))
    plan["missing_inputs"] = merged
    plan["should_ask_clarification"] = True
    if question:
        plan["clarification_question"] = question
    elif not plan.get("clarification_question"):
        plan["clarification_question"] = "请补充缺少的信息：" + "、".join(merged) + "。"


def _append_secondary_steps(plan: dict[str, Any], secondary_intents: list[str]) -> None:
    for secondary in secondary_intents:
        if secondary == "data_processing":
            plan["execution_steps"].append("完成必要的数据清洗、转换、裁剪、叠加或提取处理。")
            plan["expected_outputs"].append("派生数据集")
            for tool in ("describe_dataset", "vector_clip_by_vector", "vector_overlay"):
                if tool not in plan["recommended_tools"]:
                    plan["recommended_tools"].append(tool)
        elif secondary == "map_generation":
            plan["execution_steps"].append("基于处理后的数据生成图件，并登记为最近图件。")
            plan["expected_outputs"].append("地图图件")
            if "plot_dataset" not in plan["recommended_tools"]:
                plan["recommended_tools"].append("plot_dataset")
        elif secondary == "result_analysis":
            plan["execution_steps"].append("解释输出图件、表格或模型结果的含义、局限和下一步建议。")
            plan["expected_outputs"].append("结果解释")
        elif secondary == "modeling":
            plan["execution_steps"].append("在目标变量和特征列明确后训练模型并输出诊断结果。")
            plan["expected_outputs"].append("模型指标")


def build_task_plan(prompt: str, intent: dict[str, Any], context: dict[str, Any], manager: Any | None = None) -> dict[str, Any]:
    task_type = str(intent.get("intent") or "unclear_request")
    text = str(prompt or "")
    dataset = _dataset_name(context)
    plan = _default_plan(task_type)
    confidence = float(intent.get("confidence") or 0.0)
    referenced_object = intent.get("referenced_object") or context.get("referenced_object")
    secondary_intents = [item for item in intent.get("secondary_intents", []) if isinstance(item, str)]
    resolved_objects = _resolve_objects_for_plan(text, context, manager=manager)
    plan["resolved_objects"] = resolved_objects
    field_object = resolved_objects.get("field")
    if isinstance(field_object, dict) and field_object.get("ok"):
        if task_type == "map_generation":
            _apply_resolved_field(plan, resolved_objects, field_key="map_field", kind="map")
        elif task_type == "modeling":
            _apply_resolved_field(plan, resolved_objects, field_key="target_col", kind="target")
    slot_state, slot_workspace = _slot_context(context, dataset, referenced_object)
    slots = extract_task_slots(text, intent, slot_state, slot_workspace)
    if _as_dict(resolved_objects.get("clip_boundary")).get("ok") and "clip layer" in slots.get("missing_inputs", []):
        slots["missing_inputs"] = [item for item in slots.get("missing_inputs", []) if item != "clip layer"]
    plan["slots"] = slots
    _seed_resolved_fields_from_slots(plan, slots)

    if referenced_object:
        plan["required_inputs"].append("referenced object")
        plan["referenced_object"] = referenced_object

    if confidence < 0.55:
        _add_missing_inputs(
            plan,
            ["clear task"],
            "你的需求还不够明确。请说明要检查数据、处理分析、制图、建模、下载数据，还是解释已有结果。",
        )
        return plan

    if task_type == "modeling" and _prompt_requests_gcp(text):
        model = _recent_model_for_gcp(context, resolved_objects)
        gcp_args = _build_gcp_args_from_recent_model(model)
        if not gcp_args.get("date_col"):
            inferred_date = _infer_date_field(context)
            if inferred_date:
                gcp_args["date_col"] = inferred_date
        if _build_gcp_workflow(plan, gcp_args):
            _attach_tool_preconditions(plan)
        return plan

    intent_missing = [str(item) for item in intent.get("missing_inputs", []) if item]
    if task_type in {"map_generation", "data_processing", "modeling"} and not _has_dataset(context):
        _add_missing_inputs(
            plan,
            ["dataset"],
            "请先上传或导入一个可用数据集，或说明要使用工作区中的哪个数据集。",
        )
        plan["required_inputs"].append("dataset")
        return plan

    if task_type == "data_upload_analysis":
        plan.update(
            required_inputs=["dataset"],
            recommended_tools=["describe_dataset", "detect_coordinate_fields", "profile_missing_values", "preview_table"],
            execution_steps=[
                f"检查数据集 {dataset or '当前数据集'} 的类型、字段、坐标、时间和缺失值。",
                "判断它适合制图、空间处理、建模还是结果解释。",
            ],
            expected_outputs=["数据体检摘要", "可执行下一步建议"],
        )
    elif task_type == "map_generation":
        tools = ["plot_dataset"]
        if "栅格" in text or "直方图" in text or "raster" in text.lower():
            tools = ["raster_histogram", "plot_dataset"]
        plan.update(
            required_inputs=["dataset", "map field or visual target"],
            recommended_tools=tools,
            execution_steps=[
                f"确认 {dataset or '当前数据集'} 的空间类型和可视化字段。",
                "生成图件并登记为最近图件。",
            ],
            expected_outputs=["地图图件", "空间分布解释"],
        )
        if not plan.get("resolved_fields", {}).get("map_field") and not _prompt_has_explicit_field_hint(text) and not _resolve_semantic_field_for_plan(
            plan,
            text,
            context,
            field_key="map_field",
            kind="map",
        ):
            _add_missing_inputs(
                plan,
                ["map field"],
                "请指定要制图的字段或主题；如果不确定，我可以先预览字段并推荐适合制图的列。",
            )
    elif task_type == "modeling":
        plan.update(
            required_inputs=["dataset", "target column", "feature columns"],
            recommended_tools=["profile_missing_values", "train_xgboost_fusion_model", "train_rf_fusion_model"],
            execution_steps=[
                f"检查 {dataset or '当前数据集'} 的缺失值和候选特征。",
                "确认目标变量与特征列后训练模型。",
                "输出指标、特征重要性和残差诊断。",
            ],
            expected_outputs=["预测结果表", "模型指标", "特征重要性", "残差空间分布"],
        )
        if not plan.get("resolved_fields", {}).get("target_col") and not _prompt_has_target_hint(text) and not _resolve_semantic_field_for_plan(
            plan,
            text,
            context,
            field_key="target_col",
            kind="target",
        ):
            _add_missing_inputs(
                plan,
                ["target column"],
                "请指定要预测的目标变量字段；如果不确定，我可以先列出数值字段候选。",
            )
        if not plan.get("resolved_fields", {}).get("feature_fields"):
            _add_missing_inputs(plan, ["feature columns"])
    elif task_type == "data_processing":
        plan.update(
            required_inputs=["dataset", "processing operation"],
            recommended_tools=[
                "describe_dataset",
                "vector_clip_by_vector",
                "vector_overlay",
                "extract_raster_values_to_points",
                "table_to_points",
            ],
            execution_steps=[
                "先确认输入数据类型、坐标系和字段。",
                "按处理目标选择裁剪、叠加、提取、转换或清洗工具。",
            ],
            expected_outputs=["派生数据集", "处理日志", "结果解释"],
        )
    elif task_type == "result_analysis":
        plan.update(
            required_inputs=["result object"],
            recommended_tools=["workspace_status"],
            execution_steps=[
                "定位最近图件、表格或模型结果。",
                "解释关键指标、空间格局、输出文件和局限。",
            ],
            expected_outputs=["结果解释", "下一步建议"],
        )
        if not context.get("recent_model_result") and not context.get("recent_artifacts") and not referenced_object:
            _add_missing_inputs(
                plan,
                ["result object"],
                "请说明要解释哪个结果；也可以先生成图件、模型结果或处理输出后再追问。",
            )
    elif task_type == "follow_up_question":
        plan.update(
            required_inputs=["referenced object or previous task"],
            recommended_tools=[],
            execution_steps=["沿用最近任务、数据集、图件、模型结果或错误记录回答追问。"],
            expected_outputs=["承接上下文的回答"],
        )
        if not referenced_object:
            _add_missing_inputs(
                plan,
                ["referenced object"],
                "请说明“这个”指的是哪个数据、图件、模型结果或处理步骤。",
            )
    elif task_type == "troubleshooting":
        plan.update(
            required_inputs=["error"],
            recommended_tools=[],
            execution_steps=["读取最近错误和任务上下文。", "解释失败原因并给出最小修复步骤。"],
            expected_outputs=["失败原因", "修复建议"],
        )
        if not context.get("recent_error") and not referenced_object:
            _add_missing_inputs(
                plan,
                ["error"],
                "请提供报错信息，或先运行一次任务让我记录失败原因。",
            )
    elif task_type == "data_download":
        plan.update(
            required_inputs=["resource type", "region/time/account if needed"],
            recommended_tools=["download_backend_status", "list_remote_resource_catalog"],
            execution_steps=["识别数据类型、区域和时间范围。", "优先检查本地文件库和可用下载源。"],
            expected_outputs=["下载计划", "数据集或下载任务"],
        )
    elif task_type == "general_gis_question":
        plan.update(
            recommended_tools=[],
            execution_steps=["基于 GIS 常识回答；如涉及工作区数据，则先说明依据。"],
            expected_outputs=["概念解释或方法建议"],
        )
    else:
        _add_missing_inputs(
            plan,
            ["clear task"],
            "请补充你想完成的 GIS 任务：检查数据、处理分析、制图、建模、下载数据，还是解释已有结果？",
        )

    if intent_missing:
        _add_missing_inputs(plan, intent_missing)
    if secondary_intents:
        _append_secondary_steps(plan, secondary_intents)
    slot_missing = [str(item) for item in slots.get("missing_inputs", []) if item]
    if slot_missing:
        _add_missing_inputs(plan, slot_missing)

    plan["required_inputs"] = list(dict.fromkeys(plan.get("required_inputs", [])))
    plan["missing_inputs"] = list(dict.fromkeys(plan.get("missing_inputs", [])))
    plan["recommended_tools"] = list(dict.fromkeys(plan.get("recommended_tools", [])))
    plan["expected_outputs"] = list(dict.fromkeys(plan.get("expected_outputs", [])))
    _build_validated_tool_args(plan, slots, context, manager=manager)
    _build_workflow_plan(plan, text, context, secondary_intents, manager=manager)
    _attach_tool_preconditions(plan)
    return plan
