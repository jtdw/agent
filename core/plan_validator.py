from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.product_catalog import product_by_id
from core.dataset_availability import availability_for_product, availability_time_error


DOWNLOAD_TOOLS = {
    "download_backend_status",
    "list_remote_resource_catalog",
    "submit_commercial_download_job",
    "run_commercial_download_job",
    "run_gscloud_dem_capture_job",
    "capture_domestic_browser_download",
    "download_domestic_url",
    "submit_commercial_download_job",
}

OPERATION_TOOL_PREFIXES = {
    "train_model": {"generic_xgboost_workflow", "run_stm_soil_moisture_xgboost_workflow", "train_xgboost_fusion_model", "train_rf_fusion_model"},
    "download_data": DOWNLOAD_TOOLS,
    "table_to_points": {"table_to_points"},
    "make_map": {"plot_dataset"},
    "clip": {"vector_clip_by_vector", "clip_raster_by_vector"},
    "raster_calculation": {"raster_algebra"},
    "ndvi_calculation": {"raster_algebra"},
    "terrain_analysis": {"dem_terrain_derivatives", "raster_reproject"},
    "raster_reproject": {"raster_reproject"},
    "raster_resample": {"raster_reproject"},
    "vector_buffer": {"vector_buffer", "reproject_vector"},
    "spatial_join": {"vector_spatial_join", "reproject_vector"},
    "raster_sampling": {"extract_raster_values_to_points", "batch_register_points_to_rasters", "table_to_points", "raster_reproject"},
    "gcp_uncertainty": {"geographical_conformal_prediction"},
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _error(code: str, message: str, **detail: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **detail}


def _tool_names(plan: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for field in ("workflow_plan", "tool_plan"):
        for step in _as_list(plan.get(field)):
            if isinstance(step, dict) and str(step.get("tool_name") or "").strip():
                names.append(str(step["tool_name"]).strip())
    for name in _as_list(plan.get("selected_tools")):
        if str(name or "").strip():
            names.append(str(name).strip())
    return list(dict.fromkeys(names))


def _steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for field in ("workflow_plan", "tool_plan"):
        for step in _as_list(plan.get(field)):
            if isinstance(step, dict):
                items.append(step)
    return items


def _step_args(step: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(step.get("tool_name") or "")
    validated = _as_dict(plan.get("validated_tool_args"))
    args = validated.get(tool_name)
    if isinstance(args, dict):
        return args
    args = step.get("validated_tool_args") if isinstance(step.get("validated_tool_args"), dict) else step.get("args")
    return args if isinstance(args, dict) else {}


def _available_dataset_names(context: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    active = _as_dict(context.get("active_dataset"))
    if active.get("name"):
        names.add(str(active["name"]))
    for item in _as_list(context.get("available_datasets")):
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return names


def _blocked_execution_plan(plan: dict[str, Any]) -> dict[str, Any]:
    blocked = deepcopy(plan)
    blocked["workflow_plan"] = []
    blocked["tool_plan"] = []
    blocked["validated_tool_args"] = {}
    return blocked


def _trace(plan: dict[str, Any], context: dict[str, Any], blocked_tools: list[str]) -> dict[str, Any]:
    return {
        "primary_goal": plan.get("primary_goal") or plan.get("task_type"),
        "intent": plan.get("task_type"),
        "operation": plan.get("operation"),
        "input_assets": _as_list(plan.get("input_assets")),
        "source_attribution": _as_dict(plan.get("source_attribution")),
        "requested_downloads": _as_list(plan.get("requested_downloads")) or _as_list(_as_dict(plan.get("download_plan")).get("requested_downloads")),
        "selected_tools": _tool_names(plan),
        "blocked_tools": blocked_tools,
        "context_sources": {
            "has_active_dataset": bool(context.get("active_dataset")),
            "available_dataset_count": len(_as_list(context.get("available_datasets"))),
            "knowledge_snippet_count": len(_as_list(context.get("knowledge_snippets"))),
            "candidate_tool_count": len(_as_list(context.get("candidate_tool_cards"))),
            "download_candidate_count": len(_as_list(context.get("download_candidates"))),
        },
    }


def validate_task_plan_before_execution(plan: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    blocked_tools: list[str] = []
    tool_names = _tool_names(plan)
    execution_required = bool(plan.get("execution_required", True))
    response_mode = str(plan.get("response_mode") or "").strip()
    if execution_required is False or response_mode == "answer_only":
        if tool_names:
            errors.append(_error("ANSWER_ONLY_PLAN_HAS_TOOLS", "Answer-only TaskPlan must not select executable tools.", tools=tool_names))
            blocked_tools.extend(tool_names)
        execution_plan = _blocked_execution_plan(plan) if errors else deepcopy(plan)
        execution_plan["execution_required"] = False
        execution_plan["response_mode"] = "answer_only"
        execution_plan["tool_plan"] = []
        execution_plan["workflow_plan"] = []
        execution_plan["validated_tool_args"] = {}
        return {
            "ok": not errors,
            "status": "valid_answer_only" if not errors else "blocked",
            "errors": errors,
            "blocked_tools": list(dict.fromkeys([name for name in blocked_tools if name])),
            "execution_plan": execution_plan,
            "trace": _trace(plan, context, blocked_tools),
        }
    requested_downloads = _as_list(plan.get("requested_downloads")) or _as_list(_as_dict(plan.get("download_plan")).get("requested_downloads"))

    download_tools = [name for name in tool_names if name in DOWNLOAD_TOOLS or "download" in name.lower() or "gscloud" in name.lower()]
    if download_tools and not requested_downloads:
        blocked_tools.extend(download_tools)
        errors.append(
            _error(
                "DOWNLOAD_TOOL_WITHOUT_REQUESTED_DOWNLOADS",
                "Plan selected a download tool but requested_downloads is empty.",
                tools=download_tools,
            )
        )

    current_roles = {str(asset.get("role") or "") for asset in _as_list(plan.get("input_assets")) if isinstance(asset, dict) and asset.get("source") == "current_upload"}
    if requested_downloads and current_roles:
        download_roles = {str(item.get("role") or item.get("resource_type") or "") for item in requested_downloads if isinstance(item, dict)}
        if current_roles & download_roles:
            errors.append(
                _error(
                    "CURRENT_UPLOAD_SUPERSEDES_DOWNLOAD",
                    "Plan attempted to download data even though the current upload provides the same role.",
                    roles=sorted(current_roles & download_roles),
                )
            )

    operation = str(plan.get("operation") or "").strip()
    allowed_for_operation = OPERATION_TOOL_PREFIXES.get(operation)
    if allowed_for_operation:
        mismatched = [name for name in tool_names if name and name not in allowed_for_operation]
        if mismatched:
            blocked_tools.extend(mismatched)
            errors.append(
                _error(
                    "TOOL_OPERATION_MISMATCH",
                    "Selected tool is inconsistent with the TaskPlan operation.",
                    operation=operation,
                    tools=mismatched,
                )
            )

    explicit_history = set(str(item) for item in _as_list(plan.get("explicit_history_references")) if str(item).strip())
    history_assets = [
        asset
        for asset in _as_list(plan.get("input_assets"))
        if isinstance(asset, dict) and asset.get("source") == "explicit_history_reference"
    ]
    if history_assets and not explicit_history:
        errors.append(
            _error(
                "IMPLICIT_HISTORY_REFERENCE_BLOCKED",
                "Plan used history assets without explicit user history references.",
                assets=[asset.get("name") for asset in history_assets],
            )
        )

    available_names = _available_dataset_names(context)
    missing_assets = [
        str(asset.get("name"))
        for asset in _as_list(plan.get("input_assets"))
        if isinstance(asset, dict)
        and asset.get("source") == "current_upload"
        and available_names
        and str(asset.get("name") or "") not in available_names
    ]
    if missing_assets:
        errors.append(_error("INPUT_ASSET_NOT_IN_CONTEXT", "Plan referenced a current upload not present in context metadata.", assets=missing_assets))

    if bool(plan.get("requires_confirmation")) and not context.get("confirmed_action_id"):
        blocked_tools.extend(tool_names)
        errors.append(_error("CONFIRMATION_REQUIRED", "Plan requires confirmation before execution."))

    for step in _steps(plan):
        tool_name = str(step.get("tool_name") or "")
        args = _step_args(step, plan)
        if tool_name == "raster_reproject":
            resampling = str(args.get("resampling") or "bilinear").strip().lower()
            if resampling not in {"nearest", "bilinear", "cubic", "average", "mode", "max", "min", "med", "q1", "q3", "sum", "rms"}:
                blocked_tools.append(tool_name)
                errors.append(_error("RESAMPLING_UNSUPPORTED", "Raster resampling method is not supported.", tool_name=tool_name, resampling=resampling))
            target_resolution = str(args.get("target_resolution") or "").strip()
            if target_resolution:
                parts = [item.strip() for item in target_resolution.replace("x", ",").replace("X", ",").replace(" ", ",").split(",") if item.strip()]
                if len(parts) == 1:
                    parts = [parts[0], parts[0]]
                try:
                    parsed = [float(parts[0]), float(parts[1])]
                    if parsed[0] <= 0 or parsed[1] <= 0:
                        raise ValueError("target_resolution must be positive")
                except Exception:
                    blocked_tools.append(tool_name)
                    errors.append(_error("TARGET_RESOLUTION_INVALID", "Raster target_resolution must be a positive number or pair in target CRS units.", tool_name=tool_name, target_resolution=target_resolution))

    for index, request in enumerate(requested_downloads):
        if not isinstance(request, dict):
            continue
        product_id = str(request.get("product_id") or request.get("product_key") or "").strip()
        product = product_by_id(product_id)
        if not product:
            errors.append(_error("DOWNLOAD_PRODUCT_NOT_SUPPORTED", "Download product is not in the Product Catalog.", product_id=product_id, index=index))
            continue
        resolution = str(request.get("resolved_resolution") or request.get("requested_resolution") or "").strip()
        supported = {str(item) for item in product.get("supported_resolutions", [])}
        if resolution and supported and resolution not in supported:
            errors.append(
                _error(
                    "DOWNLOAD_RESOLUTION_UNSUPPORTED",
                    "Requested resolution is not supported by the selected product.",
                    product_id=product_id,
                    requested_resolution=resolution,
                    supported_resolutions=sorted(supported),
                    index=index,
                )
            )
        temporal_requirement = str(product.get("temporal_requirement") or "none")
        time_range = _as_dict(request.get("time_range"))
        if temporal_requirement in {"date", "date_range"}:
            if not (str(time_range.get("start") or "").strip() and str(time_range.get("end") or "").strip()):
                blocked_tools.extend(tool_names)
                errors.append(
                    _error(
                        "DOWNLOAD_TIME_RANGE_REQUIRED",
                        "该产品需要明确时间范围后才能下载。",
                        product_id=product_id,
                        product_name=product.get("display_name_zh"),
                        temporal_requirement=temporal_requirement,
                        index=index,
                    )
                )
            else:
                availability_profile = availability_for_product(product_id)
                availability_error = availability_time_error(product_id, time_range, availability_profile)
                if availability_error:
                    blocked_tools.extend(tool_names)
                    start = availability_error.get("start") or "未知"
                    end = availability_error.get("end") or "未知"
                    errors.append(
                        _error(
                            "DOWNLOAD_TIME_RANGE_OUT_OF_AVAILABILITY",
                            f"该产品已验证可用时间范围为 {start} 至 {end}，请求时间不在可下载范围内。",
                            product_id=product_id,
                            product_name=product.get("display_name_zh"),
                            requested_time_range=time_range,
                            availability=availability_error,
                            index=index,
                        )
                    )

    blocked_tools = list(dict.fromkeys([name for name in blocked_tools if name]))
    ok = not errors
    execution_plan = deepcopy(plan) if ok else _blocked_execution_plan(plan)
    return {
        "ok": ok,
        "errors": errors,
        "blocked_tools": blocked_tools,
        "execution_plan": execution_plan,
        "trace": _trace(plan, context, blocked_tools),
    }
