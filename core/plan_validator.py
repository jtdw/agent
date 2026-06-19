from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.product_catalog import product_by_id


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
