from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

from core.llm_config import load_llm_provider_config_for_role, validate_llm_config
from core.response_language import enforce_user_text_language, localized_text, normalize_response_language
from core.task_plan_schema import validate_llm_task_plan
from core.zhipu_json_client import LLMProviderError, ZhipuJSONClient


MIN_ACTIVE_PLAN_CONFIDENCE = 0.65


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _active_dataset(context: dict[str, Any]) -> dict[str, Any]:
    active = context.get("active_dataset")
    if isinstance(active, dict) and active.get("name"):
        return active
    for item in context.get("available_datasets") or []:
        if isinstance(item, dict) and item.get("name"):
            return item
    return {}


def _candidate_tool_names(context: dict[str, Any], defaults: list[str]) -> list[str]:
    names = [
        str(item.get("tool_name"))
        for item in context.get("candidate_tool_cards") or []
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    ]
    for name in defaults:
        if name not in names:
            names.append(name)
    return names


def _context_tool_names(context: dict[str, Any]) -> set[str]:
    return {
        str(item.get("tool_name"))
        for item in context.get("candidate_tool_cards") or []
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    }


class _E2ELLMFixtureClient:
    """Explicit opt-in fake Planner/Coordinator for real-backend E2E tests only."""

    def plan_task(self, prompt: str, context: dict[str, Any], deterministic_plan: dict[str, Any]) -> dict[str, Any]:
        text = str(prompt or "").lower()
        raw_text = str(prompt or "")
        active = _active_dataset(context)
        dataset = str(active.get("name") or "dataset")
        dataset_type = str(active.get("type") or "").lower()
        fields = [str(item) for item in context.get("available_fields") or [] if str(item or "").strip()]
        available = [item for item in context.get("available_datasets") or [] if isinstance(item, dict)]
        source = "current_upload"
        if "xgboost" in text or "xgb" in text:
            def _extract_col(label_patterns: list[str]) -> str:
                for pattern in label_patterns:
                    match = re.search(pattern, raw_text, flags=re.IGNORECASE)
                    if match:
                        return str(match.group(1) or "").strip().strip("。；;，, ")
                return ""

            target_col = _extract_col([r"target_col\s*=\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", r"目标列(?:是|为)\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)"])
            feature_cols = _extract_col([r"feature_cols\s*=\s*([A-Za-z0-9_,\-\u4e00-\u9fff]+)", r"特征列(?:使用|是|为)\s*([A-Za-z0-9_,\-\u4e00-\u9fff]+)"])
            output_name = _extract_col([r"output_name\s*=\s*([A-Za-z0-9_\-]+)", r"输出名称(?:是|为)\s*([A-Za-z0-9_\-]+)"]) or "xgboost_result"
            date_col = _extract_col([r"date_col\s*=\s*([A-Za-z0-9_\-]+)", r"时间列(?:是|为)\s*([A-Za-z0-9_\-]+)"])
            lon_col = "lon" if "lon" in fields else ("longitude" if "longitude" in fields else "")
            lat_col = "lat" if "lat" in fields else ("latitude" if "latitude" in fields else "")
            features = [item.strip() for item in feature_cols.split(",") if item.strip()]
            missing = [name for name in [target_col, *features, date_col, lon_col, lat_col] if name and fields and name not in fields]
            candidate_tools = _candidate_tool_names(context, ["train_xgboost_fusion_model", "generic_xgboost_workflow"])
            if not target_col or not features or missing:
                return {
                    "primary_goal": "soil_moisture_xgboost_regression",
                    "intent": "modeling",
                    "operation": "train_model",
                    "input_assets": [{"role": "training_table", "name": dataset, "source": source}],
                    "asset_roles": {dataset: "training_table"},
                    "requested_downloads": [],
                    "study_area": "",
                    "time_range": {},
                    "spatial_resolution": "",
                    "candidate_tools": candidate_tools,
                    "selected_tools": [],
                    "workflow_steps": [],
                    "expected_outputs": [],
                    "requires_confirmation": False,
                    "clarification_question": "请确认目标列、特征列、坐标列和时间列是否都存在于当前上传数据中。",
                    "confidence": 0.84,
                    "source_attribution": {dataset: source},
                    "explicit_history_references": [],
                }
            spatial_validation = "空间分块" in raw_text or "spatial" in text
            args = {
                "dataset_name": dataset,
                "target_col": target_col,
                "feature_cols": ",".join(features),
                "output_name": output_name,
                "date_col": date_col,
                "lon_col": lon_col,
                "lat_col": lat_col,
                "spatial_validation": spatial_validation,
                "validation_method": "spatial_block" if spatial_validation else "",
                "requested_outputs": "predictions,residuals,feature_importance,metrics,model",
            }
            return {
                "primary_goal": "soil_moisture_xgboost_regression",
                "intent": "modeling",
                "operation": "train_model",
                "input_assets": [{"role": "training_table", "name": dataset, "source": source}],
                "asset_roles": {dataset: "training_table", target_col: "soil_moisture_target", **{feature: "model_feature" for feature in features}},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["train_xgboost_fusion_model"],
                "workflow_steps": [
                    {
                        "step_id": "train_xgboost",
                        "tool_name": "train_xgboost_fusion_model",
                        "args": args,
                        "expected_outputs": ["model_file", "prediction_table", "residual_table", "feature_importance", "metrics"],
                    }
                ],
                "expected_outputs": ["model_file", "prediction_table", "residual_table", "feature_importance", "metrics"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {dataset: source, target_col: source, **{feature: source for feature in features}},
                "explicit_history_references": [],
            }
        if ("坡度" in raw_text or "slope" in text) and ("坡向" in raw_text or "aspect" in text):
            candidate_tools = _candidate_tool_names(context, ["dem_terrain_derivatives"])
            return {
                "primary_goal": "dem_slope_aspect",
                "intent": "data_processing",
                "operation": "terrain_analysis",
                "input_assets": [{"role": "dem_raster", "name": dataset, "source": source}],
                "asset_roles": {dataset: "dem_raster"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["dem_terrain_derivatives"],
                "workflow_steps": [
                    {
                        "step_id": "terrain",
                        "tool_name": "dem_terrain_derivatives",
                        "args": {"dem_name": dataset, "output_prefix": f"{dataset}_terrain", "derivatives": "slope,aspect", "slope_units": "degree"},
                        "expected_outputs": ["slope_raster", "aspect_raster"],
                    }
                ],
                "expected_outputs": ["slope_raster", "aspect_raster"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {dataset: source},
                "explicit_history_references": [],
            }
        if "ndvi" in text or "近红外" in raw_text or "红光" in raw_text:
            raster_names = [str(item.get("name") or "") for item in available if str(item.get("type") or "").lower() == "raster"]
            red_name = next((name for name in raster_names if "red" in name.lower() or "红光" in name), "")
            nir_name = next((name for name in raster_names if "nir" in name.lower() or "近红外" in name), "")
            candidate_tools = _candidate_tool_names(context, ["raster_algebra"])
            if not (red_name and nir_name):
                return {
                    "primary_goal": "ndvi_calculation",
                    "intent": "data_processing",
                    "operation": "ndvi_calculation",
                    "input_assets": [],
                    "asset_roles": {},
                    "requested_downloads": [],
                    "study_area": "",
                    "time_range": {},
                    "spatial_resolution": "",
                    "candidate_tools": candidate_tools,
                    "selected_tools": [],
                    "workflow_steps": [],
                    "expected_outputs": [],
                    "requires_confirmation": False,
                    "clarification_question": "请明确哪个栅格或波段是红光，哪个是近红外后再计算 NDVI。",
                    "confidence": 0.9,
                    "source_attribution": {},
                    "explicit_history_references": [],
                }
            return {
                "primary_goal": "ndvi_calculation",
                "intent": "data_processing",
                "operation": "ndvi_calculation",
                "input_assets": [{"role": "red_raster", "name": red_name, "source": source}, {"role": "nir_raster", "name": nir_name, "source": source}],
                "asset_roles": {red_name: "red_raster", nir_name: "nir_raster"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["raster_algebra"],
                "workflow_steps": [
                    {
                        "step_id": "ndvi",
                        "tool_name": "raster_algebra",
                        "args": {"expression": "(nir - red) / (nir + red)", "input_rasters": f"nir={nir_name},red={red_name}", "output_name": "ndvi"},
                        "expected_outputs": ["ndvi_raster"],
                    }
                ],
                "expected_outputs": ["ndvi_raster"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {red_name: source, nir_name: source},
                "explicit_history_references": [],
            }
        if "提取" in raw_text and "站点" in raw_text and "栅格" in raw_text:
            table_name = next((str(item.get("name") or "") for item in available if str(item.get("type") or "").lower() == "table"), "")
            point_name = next((str(item.get("name") or "") for item in available if str(item.get("type") or "").lower() == "vector"), "")
            raster_name = next((str(item.get("name") or "") for item in available if str(item.get("type") or "").lower() == "raster"), "")
            candidate_tools = _candidate_tool_names(context, ["table_to_points", "extract_raster_values_to_points"])
            steps: list[dict[str, Any]] = []
            sample_point = point_name
            if table_name:
                sample_point = f"{table_name}_points"
                steps.append(
                    {
                        "step_id": "make_points",
                        "tool_name": "table_to_points",
                        "args": {"dataset_name": table_name, "x_col": "lon", "y_col": "lat", "crs": "EPSG:3857", "output_name": sample_point},
                        "expected_outputs": ["point_layer"],
                    }
                )
            steps.append(
                {
                    "step_id": "sample",
                    "tool_name": "extract_raster_values_to_points",
                    "args": {"point_name": "$steps.make_points.outputs.result_dataset" if table_name else sample_point, "raster_name": raster_name, "output_name": "station_raster_values", "field_name": "raster_value", "method": "nearest"},
                    "depends_on": ["make_points"] if table_name else [],
                    "expected_outputs": ["sampled_table"],
                }
            )
            return {
                "primary_goal": "station_raster_sampling",
                "intent": "data_processing",
                "operation": "raster_sampling",
                "input_assets": [{"role": "station_points", "name": table_name or point_name, "source": source}, {"role": "feature_raster", "name": raster_name, "source": source}],
                "asset_roles": {table_name or point_name: "station_points", raster_name: "feature_raster"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["table_to_points", "extract_raster_values_to_points"] if table_name else ["extract_raster_values_to_points"],
                "workflow_steps": steps,
                "expected_outputs": ["sampled_table"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {table_name or point_name: source, raster_name: source},
                "explicit_history_references": [],
            }
        if "裁剪" in raw_text and "栅格" in raw_text:
            raster_name = next((str(item.get("name") or "") for item in available if str(item.get("type") or "").lower() == "raster"), dataset)
            vector_name = next((str(item.get("name") or "") for item in available if str(item.get("type") or "").lower() == "vector"), "")
            candidate_tools = _candidate_tool_names(context, ["clip_raster_by_vector"])
            return {
                "primary_goal": "raster_clip",
                "intent": "data_processing",
                "operation": "clip",
                "input_assets": [{"role": "target_raster", "name": raster_name, "source": source}, {"role": "clip_boundary", "name": vector_name, "source": source}],
                "asset_roles": {raster_name: "target_raster", vector_name: "clip_boundary"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["clip_raster_by_vector"],
                "workflow_steps": [
                    {
                        "step_id": "clip",
                        "tool_name": "clip_raster_by_vector",
                        "args": {"raster_name": raster_name, "vector_name": vector_name, "output_name": f"{raster_name}_clipped"},
                        "expected_outputs": ["clipped_raster"],
                    }
                ],
                "expected_outputs": ["clipped_raster"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {raster_name: source, vector_name: source},
                "explicit_history_references": [],
            }
        if "plot" in text or "map" in text or "制图" in text or "地图" in text:
            if dataset_type == "table":
                candidate_tools = _candidate_tool_names(context, ["table_to_points", "plot_dataset"])
                return {
                    "primary_goal": "table_to_points_map",
                    "intent": "map_generation",
                    "operation": "map_workflow",
                    "input_assets": [{"role": "coordinate_table", "name": dataset, "source": source}],
                    "asset_roles": {dataset: "coordinate_table"},
                    "requested_downloads": [],
                    "study_area": "",
                    "time_range": {},
                    "spatial_resolution": "",
                    "candidate_tools": candidate_tools,
                    "selected_tools": ["table_to_points", "plot_dataset"],
                    "workflow_steps": [
                        {
                            "step_id": "make_points",
                            "tool_name": "table_to_points",
                            "args": {"dataset_name": dataset, "x_col": "lon", "y_col": "lat", "crs": "EPSG:4326", "output_name": f"{dataset}_points"},
                            "expected_outputs": ["point_layer"],
                        },
                        {
                            "step_id": "map",
                            "tool_name": "plot_dataset",
                            "args": {"dataset_name": "$steps.make_points.outputs.result_dataset", "column": "pop_density", "output_name": f"{dataset}_population_density_map.png"},
                            "depends_on": ["make_points"],
                            "expected_outputs": ["map_artifact"],
                        },
                    ],
                    "expected_outputs": ["point_layer", "map_artifact"],
                    "requires_confirmation": False,
                    "clarification_question": "",
                    "confidence": 0.9,
                    "source_attribution": {dataset: source},
                    "explicit_history_references": [],
                }
            candidate_tools = _candidate_tool_names(context, ["plot_dataset"])
            column = "pop_density" if "pop_density" in fields else (fields[0] if fields else "")
            return {
                "primary_goal": "vector_map",
                "intent": "map_generation",
                "operation": "map_workflow",
                "input_assets": [{"role": "vector_layer", "name": dataset, "source": source}],
                "asset_roles": {dataset: "vector_layer"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["plot_dataset"],
                "workflow_steps": [
                    {
                        "step_id": "map",
                        "tool_name": "plot_dataset",
                        "args": {"dataset_name": dataset, "column": column, "output_name": f"{dataset}_map.png"},
                        "expected_outputs": ["map_artifact"],
                    }
                ],
                "expected_outputs": ["map_artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {dataset: source},
                "explicit_history_references": [],
            }
        actual_tools = _context_tool_names(context)
        candidate_tools = _candidate_tool_names(context, ["describe_dataset"])
        if "describe_dataset" not in actual_tools and "plot_dataset" in actual_tools:
            column = "pop_density" if "pop_density" in fields else (fields[0] if fields else "")
            return {
                "primary_goal": "dataset_inspection_map",
                "intent": "inspection",
                "operation": "inspect_dataset",
                "input_assets": [{"role": "dataset", "name": dataset, "source": source}],
                "asset_roles": {dataset: "dataset"},
                "requested_downloads": [],
                "study_area": "",
                "time_range": {},
                "spatial_resolution": "",
                "candidate_tools": candidate_tools,
                "selected_tools": ["plot_dataset"],
                "workflow_steps": [
                    {
                        "step_id": "inspect_map",
                        "tool_name": "plot_dataset",
                        "args": {"dataset_name": dataset, "column": column, "output_name": f"{dataset}_inspection_map.png"},
                        "expected_outputs": ["map_artifact"],
                    }
                ],
                "expected_outputs": ["map_artifact"],
                "requires_confirmation": False,
                "clarification_question": "",
                "confidence": 0.9,
                "source_attribution": {dataset: source},
                "explicit_history_references": [],
            }
        return {
            "primary_goal": "dataset_inspection",
            "intent": "inspection",
            "operation": "inspect_dataset",
            "input_assets": [{"role": "dataset", "name": dataset, "source": source}],
            "asset_roles": {dataset: "dataset"},
            "requested_downloads": [],
            "study_area": "",
            "time_range": {},
            "spatial_resolution": "",
            "candidate_tools": candidate_tools,
            "selected_tools": ["describe_dataset"],
            "workflow_steps": [
                {"step_id": "describe", "tool_name": "describe_dataset", "args": {"dataset_name": dataset}, "expected_outputs": ["dataset_summary"]}
            ],
            "expected_outputs": ["dataset_summary"],
            "requires_confirmation": False,
            "clarification_question": "",
            "confidence": 0.9,
            "source_attribution": {dataset: source},
            "explicit_history_references": [],
        }

    def invoke(self, messages: Any) -> str:
        raw = messages[-1][1] if isinstance(messages, list) and messages else messages
        payload = json.loads(raw) if isinstance(raw, str) else raw
        remaining = payload.get("remaining_steps") if isinstance(payload, dict) else []
        current = payload.get("current_step") if isinstance(payload, dict) else {}
        if remaining and isinstance(current, dict) and current.get("step_id"):
            return json.dumps(
                {
                    "decision": "continue",
                    "next_step_id": current.get("step_id"),
                    "selected_next_action": "",
                    "required_tool": current.get("tool_name"),
                    "required_inputs": current.get("validated_tool_args") or current.get("args") or {},
                    "reason": "Run the next validated fixture step.",
                    "user_question": "",
                    "confidence": 0.9,
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "decision": "stop_success",
                "next_step_id": "",
                "selected_next_action": "",
                "required_tool": "",
                "required_inputs": {},
                "reason": "All fixture steps completed.",
                "user_question": "",
                "confidence": 0.9,
            },
            ensure_ascii=False,
        )


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "content"):
        raw = getattr(raw, "content")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _call_client(client: Any, prompt: str, context: dict[str, Any], deterministic_plan: dict[str, Any]) -> Any:
    payload = {
        "instruction": "Return one JSON TaskPlan only. Plan tools, but do not claim that any tool has executed.",
        "response_language": normalize_response_language(context.get("response_language"), prompt),
        "prompt": prompt,
        "context": {
            "agent_policy": context.get("agent_policy"),
            "active_dataset": context.get("active_dataset"),
            "available_asset_profiles": context.get("available_asset_profiles"),
            "available_fields": context.get("available_fields"),
            "context_sources": context.get("context_sources"),
            "knowledge_snippets": context.get("knowledge_snippets"),
            "candidate_tool_cards": context.get("candidate_tool_cards"),
            "download_candidates": context.get("download_candidates"),
            "area_candidates": context.get("area_candidates"),
        },
        "existing_deterministic_plan": deterministic_plan,
        "schema": {
            "task_type": "string",
            "goal": "string",
            "selected_assets": "array of {role,name,evidence}",
            "tools_read": "array of tool_name strings",
            "planned_steps": "array of {step_id, tool_name, args}",
            "requires_confirmation": "boolean",
            "clarification_question": "string",
            "assumptions": "array",
            "expected_outputs": "array",
            "forbidden_tools": "array",
            "explanation": "string",
            "phase2_required_fields": [
                "primary_goal",
                "intent",
                "operation",
                "input_assets",
                "asset_roles",
                "requested_downloads",
                "download_requests",
                "study_area",
                "time_range",
                "spatial_resolution",
                "candidate_tools",
                "selected_tools",
                "workflow_steps",
                "expected_outputs",
                "requires_confirmation",
                "execution_required",
                "response_mode",
                "clarification_question",
                "confidence",
                "source_attribution",
                "explicit_history_references",
                "response_language",
            ],
            "download_request_fields": [
                "area_asset_id",
                "area_source",
                "product_id",
                "requested_resolution",
                "resolved_resolution",
                "time_range",
                "download_parameters",
                "source_attribution",
                "expected_outputs",
                "requires_confirmation",
            ],
        },
    }
    plan_task = getattr(type(client), "plan_task", None)
    if callable(plan_task):
        return plan_task(client, prompt, context, deterministic_plan)
    invoke = getattr(client, "invoke", None)
    if callable(invoke):
        language = payload["response_language"]
        return invoke(
            [
                (
                    "system",
                    "You are a GIS LLM-first task planner. You only produce plans; tools execute later after validation. "
                    f"Set response_language={language}. User-facing clarification_question must use that language.",
                ),
                ("user", json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)),
            ]
        )
    if callable(client):
        return client(prompt, context, deterministic_plan)
    return None


def _blocked_plan(reason: str, message: str, *, errors: list[dict[str, Any]] | None = None, response_language: str = "en-US") -> dict[str, Any]:
    return {
        "task_type": "unclear_request",
        "required_inputs": [],
        "missing_inputs": [reason],
        "recommended_tools": [],
        "tool_preconditions": {},
        "execution_steps": [],
        "expected_outputs": [],
        "should_ask_clarification": True,
        "clarification_question": message,
        "resolved_fields": {},
        "resolved_objects": {},
        "slots": {},
        "tool_plan": [],
        "validated_tool_args": {},
        "workflow_plan": [],
        "slot_validation_errors": errors or [],
        "semantic_parse": {},
        "download_plan": {},
        "requested_downloads": [],
        "requires_confirmation": False,
        "response_language": response_language,
    }


def _provider_failure_message(kind: str, response_language: str) -> str:
    zh = str(response_language).startswith("zh")
    if kind == "safety_blocked":
        return "模型内容安全策略拦截了本次请求，因此没有执行任何工具。请调整表达后重试。 " if zh else "The model safety policy blocked this request, so no tools were executed."
    if kind == "rate_limited":
        return "模型服务当前触发限流，因此没有执行任何工具。请稍后重试。 " if zh else "The model service is rate limited, so no tools were executed. Please try again later."
    if kind == "timeout":
        return "模型服务响应超时，因此没有执行任何工具。请稍后重试。 " if zh else "The model service timed out, so no tools were executed. Please try again later."
    if kind == "invalid_response":
        return "模型返回格式无效，因此没有执行任何工具。请稍后重试。 " if zh else "The model returned an invalid response, so no tools were executed."
    return localized_text("planner_error", response_language)


def _client_usage(client: Any) -> dict[str, Any]:
    usage = getattr(client, "last_usage", None)
    cached = getattr(client, "last_cached_tokens", 0)
    latency_ms = getattr(client, "last_latency_ms", 0)
    retry_count = getattr(client, "last_retry_count", 0)
    model = getattr(client, "last_model", "")
    status = getattr(client, "last_status", "")
    if not isinstance(usage, dict):
        usage = {}
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0
    payload = {
        "usage": usage,
        "cached_tokens": _safe_int(cached),
        "latency_ms": _safe_int(latency_ms),
        "retry_count": _safe_int(retry_count),
        "model": str(model or ""),
        "status": str(status or ""),
    }
    return payload if any(value for value in payload.values()) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _answer_only_intent(prompt: str) -> str:
    text = str(prompt or "").strip().lower()
    if not text:
        return ""
    compact = re.sub(r"[\s，。！？!?,.]+", "", text)
    if compact in {"你好", "您好", "嗨", "hello", "hi", "hey"}:
        return "usage_help"
    question_markers = (
        "什么是",
        "是什么",
        "介绍",
        "解释",
        "说明",
        "支持哪些",
        "能下载哪些",
        "有哪些功能",
        "你能做什么",
        "你能做些什么",
        "你可以做什么",
        "你可以做些什么",
        "可以做什么",
        "可以做些什么",
        "有什么用",
        "有啥用",
        "有什么用途",
        "用途",
        "应用",
        "如何",
        "怎么",
        "帮助",
    )
    english_markers = ("what is", "what are", "how to", "how do", "which data", "what data", "what can", "use case", "use cases", "help")
    if not any(marker in text for marker in question_markers + english_markers):
        return ""
    execution_verbs = ("下载", "计算", "裁剪", "重投影", "重采样", "训练", "建模", "运行", "提取", "生成", "制图", "缓冲", "空间连接", "分析我上传")
    if any(verb in text for verb in execution_verbs) and not any(marker in text for marker in ("什么是", "是什么", "如何", "怎么", "支持哪些", "能下载哪些", "what is", "how to", "which data", "what data")):
        return ""
    if any(
        marker in text
        for marker in (
            "支持哪些",
            "能下载哪些",
            "有哪些功能",
            "你能做什么",
            "你能做些什么",
            "你可以做什么",
            "你可以做些什么",
            "可以做什么",
            "可以做些什么",
            "which data",
            "what data",
        )
    ):
        return "capability_question"
    if any(marker in text for marker in ("如何", "怎么", "帮助", "how to", "how do", "help")):
        return "usage_help"
    if any(marker in text for marker in ("结果", "指标", "为什么失败", "result", "metric")):
        return "result_explanation"
    return "knowledge_qa"


def _answer_only_task_plan(prompt: str, context: dict[str, Any], *, response_language: str) -> dict[str, Any] | None:
    intent = _answer_only_intent(prompt)
    if not intent:
        return None
    goal = "回答用户的 GIS 知识或使用问题" if response_language.startswith("zh") else "Answer the user's GIS knowledge or usage question"
    return {
        "primary_goal": goal,
        "intent": intent,
        "operation": "answer_question",
        "execution_required": False,
        "response_mode": "answer_only",
        "input_assets": [],
        "asset_roles": {},
        "requested_downloads": [],
        "download_requests": [],
        "study_area": "",
        "time_range": {},
        "spatial_resolution": "",
        "candidate_tools": [],
        "selected_tools": [],
        "workflow_steps": [],
        "expected_outputs": ["chat_answer"],
        "requires_confirmation": False,
        "clarification_question": "",
        "confidence": 0.82,
        "source_attribution": {},
        "explicit_history_references": [],
        "response_language": response_language,
        "llm_explanation": "Non-execution answer-only recovery plan.",
    }


def _validated_answer_only_result(prompt: str, context: dict[str, Any], *, response_language: str, reason: str) -> dict[str, Any] | None:
    answer_plan = _answer_only_task_plan(prompt, context, response_language=response_language)
    if not answer_plan:
        return None
    validation = validate_llm_task_plan(answer_plan, context)
    if not validation.get("ok"):
        return None
    return {
        "status": "ready",
        "mode": "active",
        "planner_source": "answer_only_planner",
        "executes_tools": False,
        "reason": reason,
        "plan": validation["plan"],
    }


def _pending_confirmation_plan(prompt: str, context: dict[str, Any], *, response_language: str) -> dict[str, Any] | None:
    pending = context.get("awaiting_confirmation") if isinstance(context.get("awaiting_confirmation"), dict) else {}
    confirmation_id = str(pending.get("confirmation_id") or "").strip()
    if not confirmation_id:
        return None
    text = str(prompt or "").strip().lower()
    compact = "".join(text.split())
    if compact not in {"继续", "确认", "开始", "开始下载", "继续下载", "确认下载", "proceed", "continue", "confirm", "start"} and not ("该区域" in text and "下载" in text):
        return None
    return {
        "primary_goal": str(pending.get("primary_goal") or "确认并执行待确认计划"),
        "intent": "confirm_pending_plan",
        "operation": "confirm_pending_plan",
        "execution_required": True,
        "response_mode": "execute_confirmed_plan",
        "confirmation_id": confirmation_id,
        "input_assets": [],
        "asset_roles": {},
        "requested_downloads": [],
        "download_requests": [],
        "study_area": "",
        "time_range": {},
        "spatial_resolution": "",
        "candidate_tools": [],
        "selected_tools": [],
        "workflow_steps": [],
        "expected_outputs": ["download_job", "tool_result"],
        "requires_confirmation": False,
        "clarification_question": "",
        "confidence": 0.88,
        "source_attribution": {},
        "explicit_history_references": [],
        "response_language": response_language,
        "llm_explanation": "Confirm the awaiting PendingConfirmation by id; execution uses the stored validated TaskPlan snapshot.",
    }


def _validated_pending_confirmation_result(prompt: str, context: dict[str, Any], *, response_language: str, reason: str) -> dict[str, Any] | None:
    pending_plan = _pending_confirmation_plan(prompt, context, response_language=response_language)
    if not pending_plan:
        return None
    validation = validate_llm_task_plan(pending_plan, context)
    if not validation.get("ok"):
        return None
    return {
        "status": "ready",
        "mode": "active",
        "planner_source": "pending_confirmation_planner",
        "executes_tools": False,
        "reason": reason,
        "plan": validation["plan"],
    }


def _catalog_time_range(prompt: str) -> dict[str, str]:
    text = str(prompt or "")
    iso_dates = re.findall(r"(20\d{2}|19\d{2})[-/.](1[0-2]|0?[1-9])[-/.](3[01]|[12]\d|0?[1-9])", text)
    if iso_dates:
        values = [f"{year}-{int(month):02d}-{int(day):02d}" for year, month, day in iso_dates]
        return {"start": values[0], "end": values[-1]}
    zh_dates = re.findall(r"(20\d{2}|19\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]\d|0?[1-9])\s*[日号]?", text)
    if zh_dates:
        values = [f"{year}-{int(month):02d}-{int(day):02d}" for year, month, day in zh_dates]
        return {"start": values[0], "end": values[-1]}
    range_match = re.search(r"(20\d{2}|19\d{2})\s*年\s*(0?[1-9]|1[0-2])\s*月\s*(?:至|到|-|—|~)\s*(0?[1-9]|1[0-2])\s*月", text)
    if range_match:
        year, start_month, end_month = range_match.groups()
        return {"start": f"{year}-{int(start_month):02d}-01", "end": f"{year}-{int(end_month):02d}-28"}
    return {}


def _catalog_backed_download_plan(prompt: str, context: dict[str, Any], *, response_language: str) -> dict[str, Any] | None:
    area_candidates = [item for item in _as_list(context.get("area_candidates")) if isinstance(item, dict)]
    product_candidates = [item for item in _as_list(context.get("download_candidates")) if isinstance(item, dict)]
    tool_names = {
        str(item.get("tool_name") or "")
        for item in _as_list(context.get("candidate_tool_cards"))
        if isinstance(item, dict) and str(item.get("tool_name") or "").strip()
    }
    if "submit_commercial_download_job" not in tool_names or not area_candidates or not product_candidates:
        return None

    same_name_candidates = [str(item.get("name") or "") for item in area_candidates]
    if len(area_candidates) > 1 and same_name_candidates[0] and same_name_candidates.count(same_name_candidates[0]) > 1:
        parents = "、".join(
            str(item.get("parent") or item.get("province") or item.get("city") or item.get("asset_id") or "")
            for item in area_candidates[:5]
        )
        question = (
            f"找到多个名为{same_name_candidates[0]}的区域，请确认上级行政区：{parents}。"
            if response_language.startswith("zh")
            else f"Multiple areas named {same_name_candidates[0]} were found. Please confirm the parent region: {parents}."
        )
        return _blocked_plan("ambiguous_area", question, response_language=response_language)

    area = area_candidates[0]
    product = product_candidates[0]
    product_id = str(product.get("product_id") or "").strip()
    area_asset_id = str(area.get("asset_id") or area.get("geometry_asset_id") or "").strip()
    if not product_id or not area_asset_id:
        return None

    supported_resolutions = [str(item) for item in _as_list(product.get("supported_resolutions")) if str(item).strip()]
    resolved_resolution = supported_resolutions[0] if supported_resolutions else ""
    temporal_requirement = str(product.get("temporal_requirement") or "none")
    time_range: dict[str, Any] = _catalog_time_range(prompt)
    missing_time = temporal_requirement in {"date", "date_range"} and not time_range
    area_source = str(area.get("area_source") or area.get("source") or "system_default")
    area_attribution = "user_selected_default_library" if area_source == "user_selected_default_library" else "system_default"
    display_name = str(product.get("display_name_zh") or product_id)
    area_name = str(area.get("name") or area_asset_id)
    primary_goal = f"下载{area_name}{resolved_resolution} DEM" if "dem" in product_id.lower() and resolved_resolution else f"下载{area_name}{display_name}"
    output_name = f"{area_name}_{product_id}".replace(" ", "_")
    request = {
        "area_asset_id": area_asset_id,
        "area_source": area_source,
        "product_id": product_id,
        "requested_resolution": resolved_resolution,
        "resolved_resolution": resolved_resolution,
        "time_range": time_range,
        "download_parameters": {"output_name": output_name},
        "source_attribution": {"area": area_attribution, "product": "system_default"},
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": True,
    }
    if missing_time:
        question = (
            f"下载{display_name}需要时间范围，请提供开始和结束日期，例如 2020年6月至8月。"
            if response_language.startswith("zh")
            else f"Downloading {display_name} requires a time range. Please provide a start and end date."
        )
        selected_tools: list[str] = []
        workflow_steps: list[dict[str, Any]] = []
        requires_confirmation = False
        confidence = 0.72
    else:
        question = (
            f"已识别{area_name}{display_name}下载计划。该任务需要使用数据源账号或登录态并可能消耗配额，请确认是否继续。"
            if response_language.startswith("zh")
            else f"I identified a download plan for {display_name} in {area_name}. This may use a data-source account or quota; please confirm whether to continue."
        )
        selected_tools = ["submit_commercial_download_job"]
        workflow_steps = [
            {
                "step_id": f"submit_{product_id}",
                "tool_name": "submit_commercial_download_job",
                "args": {
                    "product_id": product_id,
                    "area_asset_id": area_asset_id,
                    "resolution": resolved_resolution,
                    "output_name": output_name,
                },
                "expected_outputs": ["download_job", "artifact"],
            }
        ]
        requires_confirmation = True
        confidence = 0.82

    return {
        "primary_goal": primary_goal,
        "intent": "data_download",
        "operation": "download_data",
        "input_assets": [],
        "asset_roles": {},
        "requested_downloads": [request],
        "download_requests": [request],
        "study_area": area_asset_id,
        "time_range": time_range,
        "spatial_resolution": resolved_resolution,
        "candidate_tools": list(dict.fromkeys(["submit_commercial_download_job", *sorted(tool_names)])),
        "selected_tools": selected_tools,
        "workflow_steps": workflow_steps,
        "expected_outputs": ["download_job", "artifact"],
        "requires_confirmation": requires_confirmation,
        "clarification_question": question,
        "confidence": confidence,
        "source_attribution": {area_asset_id: area_attribution, product_id: "system_default"},
        "explicit_history_references": [],
        "response_language": response_language,
        "llm_explanation": "Catalog-backed recovery plan built from AreaResolver, Product Catalog, and Tool Cards after LLM planner failure.",
    }


def _validated_catalog_download_result(prompt: str, context: dict[str, Any], *, response_language: str, reason: str) -> dict[str, Any] | None:
    catalog_plan = _catalog_backed_download_plan(prompt, context, response_language=response_language)
    if not catalog_plan:
        return None
    validation = validate_llm_task_plan(catalog_plan, context)
    if not validation.get("ok"):
        return None
    return {
        "status": "ready",
        "mode": "active",
        "planner_source": "catalog_download_planner",
        "executes_tools": False,
        "reason": reason,
        "plan": validation["plan"],
    }


def build_llm_task_plan(
    prompt: str,
    context: dict[str, Any],
    *,
    client: Any | None = None,
    min_confidence: float = MIN_ACTIVE_PLAN_CONFIDENCE,
) -> dict[str, Any]:
    planner_source = "injected_client" if client is not None else "default_llm"
    response_language = normalize_response_language(context.get("response_language"), prompt)
    context = {**context, "response_language": response_language}
    pending_result = _validated_pending_confirmation_result(prompt, context, response_language=response_language, reason="awaiting_confirmation_context")
    if pending_result:
        return pending_result
    answer_result = _validated_answer_only_result(prompt, context, response_language=response_language, reason="local_answer_only_preflight")
    if answer_result:
        return answer_result
    if client is None:
        client = build_default_llm_task_planner_client()
    if client is None:
        pending_result = _validated_pending_confirmation_result(prompt, context, response_language=response_language, reason="llm_planner_client_unavailable")
        if pending_result:
            return pending_result
        answer_result = _validated_answer_only_result(prompt, context, response_language=response_language, reason="llm_planner_client_unavailable")
        if answer_result:
            return answer_result
        catalog_result = _validated_catalog_download_result(prompt, context, response_language=response_language, reason="llm_planner_client_unavailable")
        if catalog_result:
            return catalog_result
        return {
            "status": "unavailable",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": "llm_planner_client_unavailable",
            "plan": _blocked_plan(
                "llm_planner_unavailable",
                localized_text("planner_unavailable", response_language),
                response_language=response_language,
            ),
        }

    try:
        raw = _call_client(client, prompt, context, {})
    except LLMProviderError as exc:
        pending_result = _validated_pending_confirmation_result(prompt, context, response_language=response_language, reason=exc.kind)
        if pending_result:
            return pending_result
        answer_result = _validated_answer_only_result(prompt, context, response_language=response_language, reason=exc.kind)
        if answer_result:
            return answer_result
        if exc.kind == "timeout":
            catalog_result = _validated_catalog_download_result(prompt, context, response_language=response_language, reason=exc.kind)
            if catalog_result:
                catalog_result["llm_usage"] = _client_usage(client)
                return catalog_result
        return {
            "status": exc.kind,
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": exc.kind,
            "llm_usage": _client_usage(client),
            "plan": _blocked_plan(
                exc.kind,
                _provider_failure_message(exc.kind, response_language),
                errors=[{"code": str(exc.kind).upper(), "message": str(exc)}],
                response_language=response_language,
            ),
        }
    except Exception as exc:
        pending_result = _validated_pending_confirmation_result(prompt, context, response_language=response_language, reason=type(exc).__name__)
        if pending_result:
            return pending_result
        answer_result = _validated_answer_only_result(prompt, context, response_language=response_language, reason=type(exc).__name__)
        if answer_result:
            return answer_result
        catalog_result = _validated_catalog_download_result(prompt, context, response_language=response_language, reason=type(exc).__name__)
        if catalog_result:
            return catalog_result
        return {
            "status": "error",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": type(exc).__name__,
            "plan": _blocked_plan(
                "llm_planner_error",
                localized_text("planner_error", response_language),
                response_language=response_language,
            ),
        }

    payload = _parse_payload(raw)
    if payload is None:
        pending_result = _validated_pending_confirmation_result(prompt, context, response_language=response_language, reason="invalid_llm_output")
        if pending_result:
            return pending_result
        answer_result = _validated_answer_only_result(prompt, context, response_language=response_language, reason="invalid_llm_output")
        if answer_result:
            return answer_result
        catalog_result = _validated_catalog_download_result(prompt, context, response_language=response_language, reason="invalid_llm_output")
        if catalog_result:
            return catalog_result
        return {
            "status": "invalid_json",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": "invalid_json",
            "llm_usage": _client_usage(client),
            "plan": _blocked_plan(
                "invalid_llm_output",
                _provider_failure_message("invalid_response", response_language),
                response_language=response_language,
            ),
        }

    validation = validate_llm_task_plan(payload, context)
    if not validation.get("ok"):
        errors = validation.get("errors", [])
        pending_result = _validated_pending_confirmation_result(prompt, context, response_language=response_language, reason="invalid_llm_plan")
        if pending_result:
            pending_result["errors"] = errors
            return pending_result
        answer_result = _validated_answer_only_result(prompt, context, response_language=response_language, reason="invalid_llm_plan")
        if answer_result:
            answer_result["errors"] = errors
            return answer_result
        catalog_result = _validated_catalog_download_result(prompt, context, response_language=response_language, reason="invalid_llm_plan")
        if catalog_result:
            catalog_result["errors"] = errors
            return catalog_result
        return {
            "status": "invalid_plan",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "errors": errors,
            "llm_usage": _client_usage(client),
            "fallback_plan": validation.get("fallback_plan"),
            "plan": validation.get("fallback_plan")
            or _blocked_plan(
                "invalid_llm_plan",
                localized_text("invalid_llm_plan", response_language),
                errors=errors,
                response_language=response_language,
            ),
        }

    plan = validation["plan"]
    confidence = float(plan.get("confidence") or 0.0)
    if confidence < min_confidence:
        pending_result = _validated_pending_confirmation_result(prompt, context, response_language=response_language, reason="low_confidence")
        if pending_result:
            return pending_result
        answer_result = _validated_answer_only_result(prompt, context, response_language=response_language, reason="low_confidence")
        if answer_result:
            return answer_result
        catalog_result = _validated_catalog_download_result(prompt, context, response_language=response_language, reason="low_confidence")
        if catalog_result:
            return catalog_result
        low_confidence_plan = {**plan}
        low_confidence_plan["workflow_plan"] = []
        low_confidence_plan["tool_plan"] = []
        low_confidence_plan["validated_tool_args"] = {}
        low_confidence_plan["should_ask_clarification"] = True
        low_confidence_plan["clarification_question"] = enforce_user_text_language(
            low_confidence_plan.get("clarification_question") or localized_text("low_confidence", response_language),
            response_language,
            "low_confidence",
        )
        low_confidence_plan["response_language"] = response_language
        low_confidence_plan["slot_validation_errors"] = [
            _error
            for _error in low_confidence_plan.get("slot_validation_errors", [])
            if isinstance(_error, dict)
        ] + [{"code": "LLM_PLAN_LOW_CONFIDENCE", "message": "LLM plan confidence is below the execution threshold.", "confidence": confidence}]
        return {
            "status": "low_confidence",
            "mode": "active",
            "planner_source": planner_source,
            "executes_tools": False,
            "llm_usage": _client_usage(client),
            "plan": low_confidence_plan,
        }

    return {
        "status": "ready",
        "mode": "active",
        "planner_source": planner_source,
        "executes_tools": False,
        "llm_usage": _client_usage(client),
        "plan": plan,
    }


def build_default_llm_task_planner_client(*, chat_model_cls: Any | None = None, env: Mapping[str, str] | None = None, operation: str = "planner") -> Any | None:
    source = env or os.environ
    if _truthy(source.get("GIS_AGENT_E2E_LLM_FIXTURES")):
        return _E2ELLMFixtureClient()
    config = load_llm_provider_config_for_role(operation, env)
    validation = validate_llm_config(config)
    if validation.get("status") == "invalid" or config.provider == "fake" or not config.api_key_present:
        return None

    if config.provider == "zai" and chat_model_cls is None:
        return ZhipuJSONClient(config, api_key=str((env or os.environ).get(config.api_key_env) or ""), operation=operation)

    model_cls = chat_model_cls
    if model_cls is None:
        try:
            from langchain_openai import ChatOpenAI
        except Exception:
            return None
        model_cls = ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": config.model,
        "api_key": str((env or os.environ).get(config.api_key_env) or ""),
        "temperature": 0,
        "timeout": config.timeout,
        "max_retries": config.max_retries,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    try:
        return model_cls(**kwargs)
    except Exception:
        return None


def build_shadow_llm_task_plan(
    prompt: str,
    context: dict[str, Any],
    deterministic_plan: dict[str, Any],
    *,
    client: Any | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    if enabled is None:
        enabled = _truthy(os.getenv("GIS_AGENT_ENABLE_LLM_PLANNER_SHADOW"))
    if not enabled:
        return {"status": "disabled", "mode": "shadow", "planner_source": "disabled", "executes_tools": False}
    planner_source = "injected_client" if client is not None else "default_llm"
    if client is None:
        client = build_default_llm_task_planner_client()
    if client is None:
        return {
            "status": "unavailable",
            "mode": "shadow",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": "llm_planner_client_unavailable",
        }

    try:
        raw = _call_client(client, prompt, context, deterministic_plan)
    except Exception as exc:
        return {
            "status": "error",
            "mode": "shadow",
            "planner_source": planner_source,
            "executes_tools": False,
            "reason": type(exc).__name__,
        }

    payload = _parse_payload(raw)
    if payload is None:
        return {"status": "invalid_json", "mode": "shadow", "planner_source": planner_source, "executes_tools": False}

    validation = validate_llm_task_plan(payload, context)
    if not validation.get("ok"):
        return {
            "status": "invalid_plan",
            "mode": "shadow",
            "planner_source": planner_source,
            "executes_tools": False,
            "errors": validation.get("errors", []),
            "fallback_plan": validation.get("fallback_plan"),
        }
    return {
        "status": "ready",
        "mode": "shadow",
        "planner_source": planner_source,
        "executes_tools": False,
        "plan": validation["plan"],
    }
