from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from core.area_resolver import area_by_asset_id
from core.commercial.scene_jobs import (
    start_gscloud_landsat8_process,
    start_gscloud_mod021km_process,
    start_gscloud_modev1f_process,
    start_gscloud_modnd1d_process,
    start_gscloud_modl1d_process,
    start_gscloud_sentinel2_process,
)
from core.commercial.service import CommercialService
from core.commercial.tile_jobs import start_gscloud_tile_process
from core.durable_jobs import DurableJobStore
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


def _idempotency_key(user_id: str, session_id: str, request: dict[str, Any], product: dict[str, Any]) -> str:
    params = {
        "user_id": user_id,
        "session_id": session_id,
        "product_id": product.get("product_id"),
        "area_asset_id": request.get("area_asset_id"),
        "resolved_resolution": request.get("resolved_resolution"),
        "time_range": request.get("time_range"),
        "download_parameters": request.get("download_parameters"),
    }
    raw = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    return "download:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _durable_status_from_download(job: dict[str, Any]) -> str:
    status = str((job or {}).get("status") or "").strip().lower()
    return {
        "queued": "queued",
        "running": "running",
        "waiting_login": "waiting_login",
        "waiting_manual": "awaiting_confirmation",
        "completed": "succeeded",
        "failed": "failed",
        "canceled": "cancelled",
    }.get(status, "failed")


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


def _unique_result_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(str(filename or "download_result.bin")).name or "download_result.bin"
    target = directory / safe_name
    if not target.exists():
        return target
    stem = target.stem or "download_result"
    suffix = target.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}_{hashlib.sha256(safe_name.encode('utf-8')).hexdigest()[:8]}{suffix}"


def _deterministic_result_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(str(filename or "download_result.bin")).name or "download_result.bin"
    return directory / safe_name


def _cleanup_duplicate_result_copies(directory: Path, canonical: Path) -> list[str]:
    deleted: list[str] = []
    if not directory.exists() or not canonical.name:
        return deleted
    stem = canonical.stem
    suffix = canonical.suffix.lower()
    for path in directory.glob(f"{stem}_*{canonical.suffix}"):
        if path == canonical or path.suffix.lower() != suffix:
            continue
        marker = path.stem[len(stem) :]
        if not marker.startswith("_") or not marker[1:].replace("_", "").isdigit():
            continue
        try:
            path.unlink()
            deleted.append(path.name)
        except Exception:
            continue
    return deleted


def _link_or_copy_file(source: Path, target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
        return "hardlink"
    except Exception:
        shutil.copy2(source, target)
        return "copy"


def _existing_path_candidates(manager: Any, raw_path: str) -> list[Path]:
    raw = str(raw_path or "").strip()
    if not raw:
        return []
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [Path.cwd() / path, Path(getattr(manager, "workdir", ".")) / path, path]
    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve(strict=False))
        except Exception:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_file():
            resolved.append(candidate)
    return resolved


def _path_is_inside(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        resolved = path
    for root in roots:
        try:
            root_resolved = root.resolve(strict=False)
            if resolved == root_resolved or resolved.is_relative_to(root_resolved):
                return True
        except Exception:
            continue
    return False


def _path_is_in_current_result_scope(manager: Any, path: Path) -> bool:
    session_id = str(getattr(manager, "current_session_id", "") or "").strip()
    if not session_id:
        return _path_is_inside(path, [Path(getattr(manager, "workdir", "."))])
    roots = [
        Path(getattr(manager, "upload_dir", "")),
        Path(getattr(manager, "derived_dir", "")),
        Path(getattr(manager, "plot_dir", "")),
        Path(getattr(manager, "temp_dir", "")),
    ]
    roots = [root for root in roots if str(root)]
    return _path_is_inside(path, roots)


def _artifact_type_for_path(path: Path, key: str, product: dict[str, Any]) -> str:
    suffix = path.suffix.lower()
    if key == "zip_path" or suffix == ".zip":
        return "download_package"
    if suffix in {".tif", ".tiff"}:
        return "raster"
    return str(product.get("resource_type") or "download")


def _registered_download_artifacts(
    manager: Any,
    job: dict[str, Any],
    *,
    product: dict[str, Any],
) -> list[dict[str, Any]]:
    job_id = str(job.get("job_id") or "").strip()
    product_id = str(product.get("product_id") or job.get("resource_type") or "download").strip() or "download"
    result = _as_dict(job.get("result"))
    raw_paths = [
        ("zip_path", job.get("zip_path") or result.get("zip_path")),
        ("output_path", job.get("output_path") or result.get("output_path") or result.get("final_output_path") or result.get("path")),
        ("package_path", result.get("package_path")),
        ("downloaded_path", result.get("downloaded_path")),
    ]
    artifacts: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    result_dir = Path(getattr(manager, "derived_dir", Path(getattr(manager, "workdir", ".")) / "derived")) / "downloads" / (job_id or product_id)
    for key, raw in raw_paths:
        source = next(iter(_existing_path_candidates(manager, str(raw or ""))), None)
        if source is None:
            continue
        source_key = str(source.resolve(strict=False))
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        target = source
        if not _path_is_in_current_result_scope(manager, source):
            target = _deterministic_result_path(result_dir, source.name)
            source_stat = source.stat()
            needs_copy = True
            if target.exists():
                try:
                    needs_copy = target.stat().st_size != source_stat.st_size or int(target.stat().st_mtime) < int(source_stat.st_mtime)
                except Exception:
                    needs_copy = True
            storage_mode = "reference"
            if needs_copy and source.resolve(strict=False) != target.resolve(strict=False):
                storage_mode = _link_or_copy_file(source, target)
            _cleanup_duplicate_result_copies(result_dir, target)
        else:
            storage_mode = "reference"
        artifact_id = f"artifact_{job_id}_{product_id}_{key}" if job_id else ""
        registered = manager.register_artifact(
            path=str(target),
            artifact_id=artifact_id,
            type=_artifact_type_for_path(target, key, product),
            title=target.name,
            source_tool="submit_commercial_download_job",
            meta={
                "job_id": job_id,
                "product_id": product_id,
                "download_key": key,
                "source_path_copied": source_key != str(target.resolve(strict=False)),
                "storage_mode": storage_mode,
            },
        )
        artifacts.append(
            {
                "artifact_id": str(registered.get("artifact_id") or artifact_id),
                "type": str(registered.get("type") or _artifact_type_for_path(target, key, product)),
                "title": str(registered.get("title") or target.name),
                "description": str(registered.get("description") or ""),
                "quality_status": str(registered.get("quality_status") or "ok"),
                "preview_available": bool(registered.get("preview_available", False)),
                "path": str(registered.get("path") or target),
            }
        )
    return artifacts


def _attach_registered_download_artifacts(manager: Any, result: dict[str, Any], job: dict[str, Any], product: dict[str, Any]) -> dict[str, Any]:
    if str(result.get("status") or "") != "succeeded":
        return result
    artifacts = _registered_download_artifacts(manager, job, product=product)
    if not artifacts:
        return result
    result["artifacts"] = artifacts
    result.setdefault("outputs", {})["artifacts"] = artifacts
    diagnostics = result.setdefault("diagnostics", {})
    diagnostics["registered_artifact_ids"] = [item["artifact_id"] for item in artifacts if item.get("artifact_id")]
    diagnostics["artifact_registration_source"] = "download_job_outputs"
    return result


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
        service._update_job(job_id, status="running", progress=5, stage="starting_auto_tile_worker")
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
        return service.get_job(job_id), None, tile_job
    scene_starters: dict[str, Callable[..., dict[str, Any]]] = {
        "gscloud_ndvi_500m_10day": start_gscloud_modnd1d_process,
        "gscloud_lst_1km_10day": start_gscloud_modl1d_process,
        "gscloud_evi_250m_10day": start_gscloud_modev1f_process,
        "gscloud_surface_reflectance_1km": start_gscloud_mod021km_process,
        "gscloud_sentinel2_msi": start_gscloud_sentinel2_process,
        "gscloud_landsat8_oli_tirs": start_gscloud_landsat8_process,
    }
    starter = scene_starters.get(str(product.get("product_id") or ""))
    if starter is None:
        return service.fail_job(job_id, f"产品 {product.get('product_id')} 暂无可执行下载适配器。"), None, None
    service._update_job(job_id, status="running", progress=5, stage="starting_scene_worker")
    starter_kwargs = {
        "workdir": service.workdir,
        "job_id": job_id,
        "region": region,
        "start_date": start_date,
        "end_date": end_date,
        "max_scenes": int(params.get("max_scenes") or 1),
        "timeout_seconds": int(params.get("timeout_seconds") or 1800),
        "headless": bool(params.get("headless", True)),
        "auto_load": bool(params.get("auto_load", True)),
    }
    if str(product.get("product_id") or "") == "gscloud_landsat8_oli_tirs":
        starter_kwargs["cloud_max"] = float(params.get("cloud_max") or 30.0)
    scene_job = starter(**starter_kwargs)
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
    session_id = _session_id(runtime_context, manager)
    _ensure_commercial_user(service, user_id)
    area = _context_area(context, str(request.get("area_asset_id") or ""))
    params = _as_dict(request.get("download_parameters"))
    start_date, end_date = _time_range(request)
    durable_store = DurableJobStore(Path(manager.workdir) / "durable_jobs.db")
    durable = durable_store.submit_job(
        plan_id=str(context.get("plan_id") or request.get("plan_id") or ""),
        user_id=user_id,
        session_id=session_id,
        job_type="submit_commercial_download_job",
        idempotency_key=str(params.get("idempotency_key") or _idempotency_key(user_id, session_id, request, product)),
        payload={
            "area_asset_id": request.get("area_asset_id"),
            "product_id": product.get("product_id"),
            "resolved_resolution": request.get("resolved_resolution"),
            "time_range": request.get("time_range"),
            "download_parameters": params,
        },
    )
    existing_commercial_job_id = str(_as_dict(durable.get("result")).get("commercial_job_id") or "")
    if existing_commercial_job_id:
        existing_job = service.get_job(existing_commercial_job_id)
        existing_result = download_job_to_tool_result(existing_job)
        existing_result = _attach_registered_download_artifacts(manager, existing_result, existing_job, product)
        existing_result["tool_name"] = "submit_commercial_download_job"
        existing_result["step_id"] = step_id or str(request.get("step_id") or f"download_{product.get('product_id')}")
        existing_result["outputs"]["product_id"] = product.get("product_id")
        existing_result["outputs"]["area_asset_id"] = request.get("area_asset_id")
        existing_result["outputs"]["download_adapter"] = product.get("download_adapter")
        existing_result["outputs"]["job"] = existing_job
        existing_result["outputs"]["durable_job_id"] = durable.get("job_id")
        existing_result["diagnostics"]["management_view"] = download_job_to_management_view(existing_job, tool_result=existing_result)
        existing_result["diagnostics"]["idempotency_reused"] = True
        return existing_result
    durable_store.update_status(str(durable["job_id"]), "running", progress=1)
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
        session_id=session_id,
    )
    fixture_status = str(params.get("fixture_status") or "").strip()
    if fixture_status:
        job, scene_job, tile_job = _fixture_job_result(manager, service, job, product=product, fixture_status=fixture_status)
    else:
        job, scene_job, tile_job = _start_real_adapter(service, job, product=product, request=request, area=area)
    result = download_job_to_tool_result(job, scene_job=scene_job, tile_job=tile_job)
    result = _attach_registered_download_artifacts(manager, result, job, product)
    result["tool_name"] = "submit_commercial_download_job"
    result["step_id"] = step_id or str(request.get("step_id") or f"download_{product.get('product_id')}")
    result["outputs"]["product_id"] = product.get("product_id")
    result["outputs"]["area_asset_id"] = request.get("area_asset_id")
    result["outputs"]["download_adapter"] = product.get("download_adapter")
    result["outputs"]["job"] = job
    result["outputs"]["durable_job_id"] = durable.get("job_id")
    result["diagnostics"]["management_view"] = download_job_to_management_view(job, tool_result=result)
    durable_store.update_status(
        str(durable["job_id"]),
        _durable_status_from_download(job),
        progress=int(job.get("progress") or 0),
        error_code=str((result.get("errors") or [{}])[0].get("code") if result.get("errors") else result.get("error_code") or ""),
        error_message=str(result.get("user_message") or job.get("error_message") or ""),
        result={"commercial_job_id": job.get("job_id"), "tool_result": result},
    )
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
