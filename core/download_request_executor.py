from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.area_resolver import area_by_asset_id
from core.commercial.scene_jobs import (
    start_gscloud_mod021km_process,
    start_gscloud_modev1f_process,
    start_gscloud_modl1d_process,
    start_gscloud_sentinel2_process,
)
from core.commercial.service import CommercialService
from core.commercial.tile_jobs import start_gscloud_tile_process
from core.execution_trace import build_execution_trace
from core.management_views import download_job_to_management_view
from core.product_catalog import product_by_id
from core.tool_context import ToolRuntimeContext, context_from_manager
from core.tool_contracts import download_job_to_tool_result, tool_result_error


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _user_id(runtime_context: ToolRuntimeContext | None, manager: Any) -> str:
    return str(
        getattr(runtime_context, "current_user_id", "")
        or getattr(manager, "current_user_id", "")
        or "anonymous"
    ).strip() or "anonymous"


def _session_id(runtime_context: ToolRuntimeContext | None, manager: Any) -> str:
    return str(
        getattr(runtime_context, "current_session_id", "")
        or getattr(manager, "current_session_id", "")
        or ""
    ).strip()


def _ensure_commercial_user(service: CommercialService, user_id: str) -> None:
    try:
        service.get_user(user_id)
        return
    except Exception:
        pass
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in user_id) or "anonymous"
    service.create_user(f"{safe}@local.invalid", plan="basic", user_id=user_id)


def _time_range(request: dict[str, Any]) -> tuple[str, str]:
    time_range = _as_dict(request.get("time_range"))
    return str(time_range.get("start") or request.get("start_date") or ""), str(time_range.get("end") or request.get("end_date") or "")


def _context_area(context: dict[str, Any], area_asset_id: str) -> dict[str, Any]:
    for item in _as_list(context.get("area_candidates")):
        if isinstance(item, dict) and item.get("asset_id") == area_asset_id:
            return item
    return area_by_asset_id(area_asset_id) or {}


def _region_name(area: dict[str, Any], request: dict[str, Any]) -> str:
    return str(area.get("name") or request.get("area_name") or request.get("area_asset_id") or "").strip()


def _registered_artifact(manager: Any, path: Path, *, job_id: str, product_id: str, title: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = manager.register_artifact(
        path=str(path),
        artifact_id=f"artifact_{job_id}_{product_id}",
        type="download",
        title=title,
        metadata={"job_id": job_id, "product_id": product_id},
    )
    return {
        "artifact_id": str(artifact.get("artifact_id") or ""),
        "type": "download",
        "title": str(artifact.get("title") or title),
        "path": str(artifact.get("path") or path),
    }


def _fixture_job_result(
    manager: Any,
    service: CommercialService,
    job: dict[str, Any],
    *,
    product: dict[str, Any],
    fixture_status: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    status = str(fixture_status or "").strip().lower()
    if status in {"succeeded", "success", "completed"}:
        product_id = str(product.get("product_id") or "download")
        path = Path(manager.derived_dir) / "downloads" / str(job["job_id"]) / f"{product_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture download result for {product_id}\n", encoding="utf-8")
        artifact = _registered_artifact(
            manager,
            path,
            job_id=str(job["job_id"]),
            product_id=product_id,
            title=str(product.get("display_name_zh") or product_id),
        )
        result = {
            "path": str(path),
            "output_path": str(path),
            "artifacts": [artifact],
            "product_id": product_id,
            "artifact_quality": [{"ok": True, "path": str(path), "reason": "fixture_validated"}],
        }
        return service.run_job_with_result(str(job["job_id"]), result), None, None
    if status in {"waiting_login", "login_required", "awaiting_confirmation"}:
        service._update_job(
            str(job["job_id"]),
            status="waiting_login",
            progress=5,
            stage="login_required",
            error_message="需要先完成数据源登录后才能继续下载。",
        )
        return service.get_job(str(job["job_id"])), None, None
    if status in {"no_data", "failed", "remote_no_data"}:
        return service.fail_job(str(job["job_id"]), "远端数据源在该区域或时间范围内没有可下载数据。"), None, None
    service._update_job(str(job["job_id"]), status="running", progress=10, stage="fixture_running")
    return service.get_job(str(job["job_id"])), None, None


def _start_real_adapter(
    service: CommercialService,
    job: dict[str, Any],
    *,
    product: dict[str, Any],
    request: dict[str, Any],
    area: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    job_id = str(job["job_id"])
    adapter = str(product.get("download_adapter") or "")
    params = _as_dict(request.get("download_parameters"))
    region = _region_name(area, request)
    start_date, end_date = _time_range(request)
    state_path = service.resolve_job_storage_state_path(job_id)
    if not state_path or not Path(state_path).exists():
        service._update_job(
            job_id,
            status="waiting_login",
            progress=5,
            stage="login_required",
            error_message="需要先完成数据源登录后才能继续下载。",
        )
        return service.get_job(job_id), None, None
    if adapter == "gscloud_dem_tile":
        tile_job = start_gscloud_tile_process(
            workdir=service.workdir,
            job_id=job_id,
            region=region,
            region_dataset=str(area.get("geometry_asset_id") or area.get("dataset_name") or ""),
            dataset_id=str(params.get("dataset_id") or "310"),
            max_tiles=int(params.get("max_tiles") or 0),
            timeout_seconds=int(params.get("timeout_seconds") or 1800),
            headless=bool(params.get("headless", True)),
            auto_load=bool(params.get("auto_load", True)),
        )
        service._update_job(job_id, status="running", progress=5, stage="starting_auto_tile_worker")
        return service.get_job(job_id), None, tile_job
    scene_starters: dict[str, Callable[..., dict[str, Any]]] = {
        "gscloud_lst_1km_10day": start_gscloud_modl1d_process,
        "gscloud_evi_250m_10day": start_gscloud_modev1f_process,
        "gscloud_surface_reflectance_1km": start_gscloud_mod021km_process,
        "gscloud_sentinel2_msi": start_gscloud_sentinel2_process,
    }
    starter = scene_starters.get(str(product.get("product_id") or ""))
    if starter is None:
        return service.fail_job(job_id, f"产品 {product.get('product_id')} 暂无可执行下载适配器。"), None, None
    scene_job = starter(
        workdir=service.workdir,
        job_id=job_id,
        region=region,
        start_date=start_date,
        end_date=end_date,
        max_scenes=int(params.get("max_scenes") or 1),
        timeout_seconds=int(params.get("timeout_seconds") or 1800),
        headless=bool(params.get("headless", True)),
        auto_load=bool(params.get("auto_load", True)),
    )
    service._update_job(job_id, status="running", progress=5, stage="starting_scene_worker")
    return service.get_job(job_id), scene_job, None


def execute_single_download_request(
    manager: Any,
    request: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    runtime_context: ToolRuntimeContext | None = None,
    step_id: str = "",
) -> dict[str, Any]:
    context = context or {}
    runtime_context = runtime_context or context_from_manager(manager)
    product = product_by_id(str(request.get("product_id") or request.get("product_key") or ""))
    if not product:
        return tool_result_error(
            "submit_commercial_download_job",
            inputs=request,
            error_code="DOWNLOAD_PRODUCT_NOT_SUPPORTED",
            error_title="下载产品不支持",
            user_message="该数据产品当前没有可执行的下载适配器。",
        ).to_dict()
    service = CommercialService(Path(manager.workdir))
    user_id = _user_id(runtime_context, manager)
    _ensure_commercial_user(service, user_id)
    area = _context_area(context, str(request.get("area_asset_id") or ""))
    params = _as_dict(request.get("download_parameters"))
    start_date, end_date = _time_range(request)
    job = service.submit_job(
        user_id=user_id,
        source_key=str(product.get("source") or "gscloud"),
        resource_type=str(product.get("resource_type") or ""),
        region=_region_name(area, request),
        start_date=start_date,
        end_date=end_date,
        account_mode=str(params.get("account_mode") or "auto"),
        request_text="validated_llm_task_plan_download_request",
        output_name=str(params.get("output_name") or product.get("product_id") or ""),
        session_id=_session_id(runtime_context, manager),
    )
    fixture_status = str(params.get("fixture_status") or "").strip()
    if fixture_status:
        job, scene_job, tile_job = _fixture_job_result(manager, service, job, product=product, fixture_status=fixture_status)
    else:
        job, scene_job, tile_job = _start_real_adapter(service, job, product=product, request=request, area=area)
    result = download_job_to_tool_result(job, scene_job=scene_job, tile_job=tile_job)
    result["tool_name"] = "submit_commercial_download_job"
    result["step_id"] = step_id or str(request.get("step_id") or f"download_{product.get('product_id')}")
    result["outputs"]["product_id"] = product.get("product_id")
    result["outputs"]["area_asset_id"] = request.get("area_asset_id")
    result["outputs"]["download_adapter"] = product.get("download_adapter")
    result["outputs"]["job"] = job
    result["diagnostics"]["management_view"] = download_job_to_management_view(job, tool_result=result)
    return result


def execute_download_requests(
    manager: Any,
    plan: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    runtime_context: ToolRuntimeContext | None = None,
) -> dict[str, Any]:
    requests = _as_list(plan.get("download_requests")) or _as_list(plan.get("requested_downloads"))
    results: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            continue
        results.append(
            execute_single_download_request(
                manager,
                request,
                context=context,
                runtime_context=runtime_context,
                step_id=str(request.get("step_id") or f"download_{index + 1}"),
            )
        )
    status = "succeeded"
    if any(item.get("status") == "awaiting_confirmation" for item in results):
        status = "awaiting_confirmation"
    elif any(item.get("status") == "failed" for item in results):
        status = "failed"
    elif any(item.get("status") == "blocked" for item in results):
        status = "blocked"
    elif any(item.get("status") == "running" for item in results):
        status = "running"
    return {
        "executed": bool(results),
        "ok": bool(results) and all(item.get("status") == "succeeded" for item in results),
        "success": bool(results) and all(item.get("status") == "succeeded" for item in results),
        "status": status,
        "tool_results": results,
        "normalized_results": results,
        "execution_trace": build_execution_trace(plan, {"tool_results": results}).model_dump(mode="json"),
        "executed_tools": ["submit_commercial_download_job"] if results else [],
    }
