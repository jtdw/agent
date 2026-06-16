from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode
from zipfile import ZipFile

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from infrastructure.storage.workspace_paths import workspace_root_for_user
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, EmailStr, Field

from core.config import Settings, load_settings
from core.service import GISWorkspaceService
from core.commercial.service import CommercialService, PLAN_PRESETS
from core.api_security import optional_authenticated_session, require_admin_token, require_authenticated_user, require_resource_owner
from core.api_helpers import (
    SESSION_COOKIE_ID,
    SESSION_COOKIE_TOKEN,
    build_workspace_mentions as _build_workspace_mentions,
    build_result_panel as _api_build_result_panel,
    cors_origins as _cors_origins,
    download_requires_login_result as _api_download_requires_login_result,
    relative_shared_download_url,
    request_admin_token as _request_admin_token,
    request_session as _request_session,
    safe_key as _safe_key,
)
from core.artifacts import artifact_download_url, assert_artifact_path_allowed, public_artifact_payload, safe_download_filename, shapefile_zip_path
from core.archive_utils import safe_extract_zip
from core.chat_tasks import cancel_chat_task, finish_chat_task, start_chat_task
from core.chat_response import attach_chat_state, build_chat_response
from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown
from core.api_utils import api_guard, resolve_child_path
from core.local_library import LocalFileLibrary
from core.map_layers import MapLayerService, dataset_map_kind
from core.station_data import find_station_archives, parse_ismn_station_zip
from core.domestic_sources.intent_router import GSCloudIntentRoute, route_gscloud_download_intent
from core.domestic_sources.gscloud_download_verifier import verify_gscloud_scene_download
from core.domestic_sources.gscloud_products import GSCLOUD_PRODUCTS, LANDSAT8_OLI_TIRS, MOD021KM_1KM_SURFACE_REFLECTANCE, MODEV1F_CHINA_250M_EVI_5DAY, MODL1D_CHINA_1KM_LST_DAILY, MODND1D_CHINA_500M_NDVI_DAILY, SENTINEL2_MSI, match_gscloud_product
from core.domestic_sources.gscloud_reliability import inspect_storage_state, resolve_download_region
from services.data_sources.gscloud_accounts import GSCloudAccountService
from api.routes.data_sources import create_data_sources_router
from api.routes.downloads import create_downloads_router
from services.downloads.resume import DownloadResumeService
from core.ops_config import require_valid_production_config, validate_production_config
from core.llm_config import check_llm_provider_health, validate_llm_config

try:
    from core.commercial.tile_jobs import list_gscloud_tile_jobs, start_gscloud_tile_process
except Exception:  # pragma: no cover
    list_gscloud_tile_jobs = None
    start_gscloud_tile_process = None

try:
    from core.commercial.scene_jobs import list_gscloud_scene_jobs, start_gscloud_landsat8_process, start_gscloud_mod021km_process, start_gscloud_modev1f_process, start_gscloud_modl1d_process, start_gscloud_modnd1d_process, start_gscloud_sentinel2_process
except Exception:  # pragma: no cover
    list_gscloud_scene_jobs = None
    start_gscloud_landsat8_process = None
    start_gscloud_mod021km_process = None
    start_gscloud_modev1f_process = None
    start_gscloud_modl1d_process = None
    start_gscloud_modnd1d_process = None
    start_gscloud_sentinel2_process = None

base_settings = load_settings()
commercial_service = CommercialService(base_settings.workdir)
local_library_root = Path(os.getenv("GIS_AGENT_LOCAL_LIBRARY_DIR", str(base_settings.workdir / "local_library"))).expanduser()
local_library = LocalFileLibrary(local_library_root)
_workspace_services: dict[str, GISWorkspaceService] = {}
_LOCAL_LIBRARY_BOUNDARY_LAYER_CACHE: dict | None = None
MAX_UPLOAD_FILES = int(os.getenv("GIS_AGENT_MAX_UPLOAD_FILES", "30") or 30)
MAX_UPLOAD_BYTES = int(os.getenv("GIS_AGENT_MAX_UPLOAD_MB", "300") or 300) * 1024 * 1024
SESSION_COOKIE_ID = "gis_agent_session_id"
SESSION_COOKIE_TOKEN = "gis_agent_session_token"
SESSION_COOKIE_MAX_AGE = int(os.getenv("GIS_AGENT_SESSION_COOKIE_MAX_AGE", str(7 * 24 * 60 * 60)) or (7 * 24 * 60 * 60))


def _bootstrap_platform_account_from_env() -> None:
    username = os.getenv("GSCLOUD_PLATFORM_USERNAME", "").strip()
    password = os.getenv("GSCLOUD_PLATFORM_PASSWORD", "").strip()
    state_path = os.getenv("GSCLOUD_PLATFORM_STORAGE_STATE", "").strip()
    if not username and not state_path:
        return
    commercial_service.upsert_platform_account(
        source_key="gscloud",
        username=username,
        password=password,
        label=os.getenv("GSCLOUD_PLATFORM_LABEL", "后台地理空间数据云账号").strip() or "后台地理空间数据云账号",
        daily_limit=int(os.getenv("GSCLOUD_PLATFORM_DAILY_LIMIT", "50") or 50),
        monthly_limit=int(os.getenv("GSCLOUD_PLATFORM_MONTHLY_LIMIT", "1000") or 1000),
        storage_state_path=state_path,
    )


try:
    _bootstrap_platform_account_from_env()
except Exception:
    pass


def _startup_operational_checks() -> None:
    require_valid_production_config()
    commercial_service.recover_interrupted_jobs()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _startup_operational_checks()
    yield


app = FastAPI(title="GIS Agent Web API", version="1.4.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _user_workdir(user_id: str | None) -> Path:
    return workspace_root_for_user(base_settings.workdir, user_id)


def workspace_for(user_id: str | None = None) -> GISWorkspaceService:
    key = _safe_key(user_id)
    if key not in _workspace_services:
        settings = Settings(
            api_key=base_settings.api_key,
            model=base_settings.model,
            supported_models=base_settings.supported_models,
            base_url=base_settings.base_url,
            workdir=_user_workdir(user_id),
            temperature=base_settings.temperature,
            desktop_theme=base_settings.desktop_theme,
        )
        settings.ensure_dirs()
        _workspace_services[key] = GISWorkspaceService(settings=settings)
    return _workspace_services[key]


def _set_session_cookies(response: Response, session: dict) -> None:
    secure = os.getenv("GIS_AGENT_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
    response.set_cookie(
        SESSION_COOKIE_ID,
        str(session.get("session_id") or ""),
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        SESSION_COOKIE_TOKEN,
        str(session.get("session_token") or ""),
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_ID, path="/")
    response.delete_cookie(SESSION_COOKIE_TOKEN, path="/")


def _require_request_user(request: Request, user_id: str) -> str:
    session_id, session_token = _request_session(request)
    return require_authenticated_user(
        commercial_service,
        requested_user_id=user_id,
        session_id=session_id,
        session_token=session_token,
    )


def _require_request_user_if_present(request: Request, user_id: str) -> str:
    if not str(user_id or "").strip():
        return ""
    return _require_request_user(request, user_id)


def _authenticated_request_user(request: Request) -> str:
    session_id, session_token = _request_session(request)
    payload = commercial_service.validate_session(session_id, session_token)
    user = payload.get("user") if isinstance(payload, dict) else None
    user_id = str((user or {}).get("user_id") or "").strip()
    if not user_id:
        raise PermissionError("请先登录账号。")
    return user_id


def _require_admin_or_mock_payment_user(request: Request, user_id: str) -> str:
    admin_token = _request_admin_token(request)
    if admin_token:
        require_admin_token(os.getenv("GIS_AGENT_ADMIN_TOKEN", ""), admin_token)
        return str(user_id or "").strip()
    if os.getenv("GIS_AGENT_ENABLE_MOCK_PAYMENT", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return _require_request_user(request, user_id)
    raise PermissionError("模拟支付接口默认关闭。请设置 GIS_AGENT_ENABLE_MOCK_PAYMENT=1 并登录，或配置 GIS_AGENT_ADMIN_TOKEN 后用管理员令牌调用。")


def _audit(
    request: Request,
    *,
    user_id: str = "",
    action: str,
    status: str = "ok",
    resource_type: str = "",
    resource_id: str = "",
    detail: dict | None = None,
) -> None:
    try:
        commercial_service.write_audit_event(
            user_id=user_id,
            action=action,
            status=status,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=request.client.host if request.client else "",
            user_agent=str(request.headers.get("user-agent") or ""),
            detail=detail or {},
        )
    except Exception:
        pass


class AuthIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class ValidateIn(BaseModel):
    session_id: str
    session_token: str


class AskIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    user_id: str = ""
    session_id: str = ""
    session_token: str = ""
    task_id: str = ""
    frontend_context: dict[str, Any] = Field(default_factory=dict)


class ChatCancelIn(BaseModel):
    user_id: str = ""
    task_id: str = Field(min_length=1, max_length=120)
    reason: str = ""


class ChatSessionIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    title: str = ""


class ChatRetryIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    message_id: int
    content: str = Field(min_length=1, max_length=12000)


class ChatModelIn(BaseModel):
    user_id: str = ""
    session_id: str
    model: str = Field(min_length=1, max_length=120)


class PaymentIn(BaseModel):
    user_id: str
    plan: Literal["pro", "team"] = "pro"


class DownloadIn(BaseModel):
    user_id: str
    source_key: str = "gscloud"
    resource_type: str = "dem"
    region: str = ""
    start_date: str = ""
    end_date: str = ""
    account_mode: Literal["own", "platform", "auto"] = "auto"
    request_text: str = ""
    output_name: str = ""


class DownloadDeleteIn(BaseModel):
    user_id: str = ""
    job_id: str


class DownloadActionIn(BaseModel):
    user_id: str = ""
    job_id: str
    reason: str = ""


class DownloadPreflightIn(BaseModel):
    user_id: str
    source_key: str = "gscloud"
    resource_type: str = "landsat8_oli_tirs"
    product_key: str = ""
    region: str = ""
    start_date: str = ""
    end_date: str = ""
    account_mode: Literal["own", "platform", "auto"] = "auto"
    request_text: str = ""
    max_pages: int = 1
    cloud_max: float = 30.0
    processing_level: str = ""


class ExportIn(BaseModel):
    user_id: str = ""
    mode: Literal["latest", "all"] = "all"


class WorkflowIn(BaseModel):
    user_id: str = ""
    run_now: bool = True


class MapLayerRefreshIn(BaseModel):
    user_id: str = ""
    artifact_id: str = ""
    dataset_name: str = ""


class LocalLibraryImportIn(BaseModel):
    user_id: str = ""
    item_ids: list[str] = Field(default_factory=list)


class LocalLibraryRescanIn(BaseModel):
    pass


class ArtifactBatchDeleteIn(BaseModel):
    user_id: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    delete_file: bool = True


def guard(fn):
    return api_guard(fn)




def _station_search_roots(user_id: str | None = None) -> list[Path]:
    project_root = Path(__file__).resolve().parent
    roots = [
        _user_workdir(user_id) / "uploads",
        _user_workdir(user_id) / "derived",
        local_library.data_dir,
        project_root / "local_library" / "data",
        base_settings.workdir / "local_library" / "data",
    ]
    return roots


def _load_station_collection(user_id: str = "") -> dict:
    archives = find_station_archives(*_station_search_roots(user_id))
    if not archives:
        return {
            "count": 0,
            "stations": [],
            "center": [116.18, 41.78],
            "bounds": [115.5, 41.5, 116.5, 42.5],
            "source": "",
            "source_name": "",
            "message": "未找到闪电河 2019 土壤水分站点压缩包。请将 shandianhe2019_station_0_5cm.zip 放入 local_library/data/stations，或上传到当前工作区。",
        }
    # Use the first matching archive. The finder prioritizes Shandian/station archives.
    return parse_ismn_station_zip(archives[0], preferred_depth="0.050000", year="2019")


def _safe_layer_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "layer").strip("_")[:80] or "layer"


def _relative_artifact_url(service: GISWorkspaceService, file_path: str, user_id: str = "") -> str:
    try:
        target = assert_artifact_path_allowed(service.manager.workdir, file_path)
    except (PermissionError, ValueError):
        return ""
    if not target.exists() or not target.is_file():
        return ""
    existing = None
    for item in service.manager.list_artifacts():
        try:
            if Path(str(item.get("path") or "")).resolve() == target:
                existing = item
                break
        except OSError:
            continue
    if existing is None:
        existing = service.manager.register_artifact(
            path=str(target),
            type="artifact",
            title=target.name,
            meta={"tool_name": "workspace_result"},
        )
    elif not service.manager.get_artifact(str(existing.get("artifact_id") or "")):
        existing = service.manager.register_artifact(
            artifact_id=str(existing.get("artifact_id") or ""),
            path=str(target),
            type=str(existing.get("type") or existing.get("category") or "artifact"),
            title=str(existing.get("title") or existing.get("name") or target.name),
            meta=existing.get("meta") if isinstance(existing.get("meta"), dict) else {"tool_name": "workspace_result"},
        )
    return artifact_download_url(str(existing.get("artifact_id") or ""), user_id=user_id)


def _download_job_artifacts(user_id: str, job: dict) -> list[dict]:
    if str(job.get("status") or "") not in {"completed", "success"}:
        return []
    service = workspace_for(user_id)
    job_id = str(job.get("job_id") or "download")
    target_dir = service.manager.derived_dir / "downloads" / safe_download_filename(job_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[str] = []
    for value in (job.get("output_path"), job.get("zip_path")):
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    for key in ("downloaded_path", "path", "zip_path", "package_path", "metadata_path", "preview_path", "log_path"):
        value = result.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in candidates:
            candidates.append(value.strip())

    copied: list[Path] = []
    for value in candidates:
        try:
            source = assert_artifact_path_allowed(commercial_service.workdir, value)
        except (PermissionError, ValueError):
            continue
        if not source.exists() or not source.is_file():
            continue
        destination = target_dir / safe_download_filename(source.name)
        if not destination.exists() or destination.stat().st_size != source.stat().st_size:
            shutil.copy2(source, destination)
        copied.append(destination)

    metadata_path = target_dir / "metadata.json"
    metadata_path.write_text(json.dumps({
        "job_id": job_id,
        "provider": job.get("source_key"),
        "resource_type": job.get("resource_type"),
        "region": job.get("region"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    copied.append(metadata_path)

    public: list[dict] = []
    for path in copied:
        existing = next((item for item in service.manager.list_registered_artifacts(limit=300) if Path(str(item.get("path") or "")).resolve() == path.resolve()), None)
        artifact = existing or service.manager.register_artifact(
            path=str(path),
            type="dem" if path.suffix.lower() in {".tif", ".tiff"} else path.suffix.lower().lstrip(".") or "artifact",
            title=path.name,
            quality_status="validated",
            preview_available=path.suffix.lower() == ".png",
            task_id=job_id,
            meta={"tool_name": "gscloud_download", "job_id": job_id, "provider": "gscloud"},
        )
        public.append(public_artifact_payload(artifact, workdir=service.manager.workdir, user_id=user_id))
    return public


def _public_download_job(job: dict) -> dict:
    public = dict(job)
    for key in ("output_path", "zip_path", "direct_url", "local_file_path", "result_json", "failure_diagnostic_json", "artifact_quality_json"):
        public.pop(key, None)
    public.pop("result", None)
    return public


def _artifact_error(status_code: int, error_code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error_code": error_code, "message": message})


def _public_artifact_or_error(service: GISWorkspaceService, artifact_id: str, user_id: str = "") -> dict:
    artifact = service.manager.get_artifact(artifact_id)
    if not artifact:
        raise _artifact_error(404, "ARTIFACT_NOT_FOUND", "Artifact does not exist or is no longer registered.")
    try:
        target = assert_artifact_path_allowed(service.manager.workdir, str(artifact.get("path") or ""))
    except PermissionError as exc:
        raise _artifact_error(403, "ARTIFACT_FORBIDDEN", str(exc)) from exc
    if not target.exists() or not target.is_file():
        raise _artifact_error(404, "ARTIFACT_FILE_MISSING", "Artifact file is missing or expired.")
    try:
        return public_artifact_payload(artifact, workdir=service.manager.workdir, user_id=user_id)
    except PermissionError as exc:
        raise _artifact_error(403, "ARTIFACT_FORBIDDEN", str(exc)) from exc


def _decorate_message_artifacts(service: GISWorkspaceService, messages: list[dict], user_id: str = "") -> list[dict]:
    decorated: list[dict] = []
    for message in messages or []:
        item = dict(message)
        meta = dict(item.get("meta") or {})
        artifacts = meta.get("artifacts") if isinstance(meta.get("artifacts"), list) else []
        public_artifacts: list[dict] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            artifact_id = str(artifact.get("artifact_id") or "")
            source = service.manager.get_artifact(artifact_id) if artifact_id else artifact
            if not source:
                continue
            source = dict(source)
            source.setdefault("message_id", item.get("message_id"))
            try:
                public = public_artifact_payload(source, workdir=service.manager.workdir, user_id=user_id)
            except Exception:
                continue
            public_artifacts.append(public)
        if public_artifacts:
            meta["artifacts"] = public_artifacts
        item["meta"] = meta
        decorated.append(item)
    return decorated


def _decorate_chat_response_messages(service: GISWorkspaceService, user_id: str, response: dict) -> dict:
    artifacts = response.get("artifacts") if isinstance(response.get("artifacts"), list) else []
    public_artifacts: list[dict] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or "")
        source = service.manager.get_artifact(artifact_id) if artifact_id else None
        try:
            public_artifacts.append(public_artifact_payload(source or artifact, workdir=service.manager.workdir, user_id=user_id))
        except (PermissionError, FileNotFoundError, OSError):
            continue
    if artifacts:
        response = {**response, "artifacts": public_artifacts}
    if isinstance(response.get("messages"), list):
        response = {**response, "messages": _decorate_message_artifacts(service, response["messages"], user_id=user_id)}
    return response


def _decorate_dashboard(service: GISWorkspaceService, user_id: str = "") -> dict:
    data = service.dashboard()
    for item in data.get("artifacts", []):
        if isinstance(item, dict) and item.get("path"):
            item["download_url"] = _relative_artifact_url(service, item["path"], user_id=user_id)
    for result in data.get("model_results", []):
        if not isinstance(result, dict):
            continue
        for artifact in result.get("artifacts", []):
            if isinstance(artifact, dict) and artifact.get("path"):
                artifact["download_url"] = _relative_artifact_url(service, artifact["path"], user_id=user_id)
    latest = data.get("latest_pipeline") if isinstance(data.get("latest_pipeline"), dict) else {}
    summary = latest.get("summary") if isinstance(latest, dict) and isinstance(latest.get("summary"), dict) else {}
    reports = summary.get("reports") if isinstance(summary.get("reports"), dict) else {}
    metrics_dataset = str(reports.get("metrics_dataset") or "")
    gcp_metrics_dataset = str(reports.get("gcp_metrics_dataset") or "")
    analysis: dict = {
        "metrics_dataset": metrics_dataset,
        "gcp_metrics_dataset": gcp_metrics_dataset,
        "metric_rows": [],
        "gcp_metric_rows": [],
    }
    if metrics_dataset:
        try:
            analysis["metric_rows"] = service.manager.preview_table_rows(metrics_dataset, rows=12)
        except Exception:
            analysis["metric_rows"] = []
    if gcp_metrics_dataset:
        try:
            analysis["gcp_metric_rows"] = service.manager.preview_table_rows(gcp_metrics_dataset, rows=12)
        except Exception:
            analysis["gcp_metric_rows"] = []
    if not analysis["metric_rows"]:
        model_rows = []
        for result in data.get("model_results", []):
            if not isinstance(result, dict):
                continue
            metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
            if metrics:
                model_rows.append({"model": result.get("model") or result.get("output_prefix") or "model", **metrics})
        analysis["metric_rows"] = model_rows[:12]
        if model_rows and not analysis["metrics_dataset"]:
            analysis["metrics_dataset"] = str(data.get("model_results", [{}])[0].get("metrics_dataset") or "")
    data["analysis"] = analysis
    return data


def _build_upload_summaries(service: GISWorkspaceService, payload: list[tuple[str, bytes]], messages: list[str]) -> list[dict[str, Any]]:
    catalog = service.manager.database.list_catalog()
    by_filename = {Path(str(item.get("path") or "")).name: item for item in catalog if isinstance(item, dict)}
    summaries: list[dict[str, Any]] = []
    for index, (filename, data) in enumerate(payload):
        safe_name = Path(str(filename or "uploaded.bin")).name
        item = by_filename.get(safe_name, {})
        summaries.append(
            {
                "filename": safe_name,
                "type": str(item.get("data_type") or Path(safe_name).suffix.lower().lstrip(".") or "file"),
                "size_bytes": len(data or b""),
                "row_count": item.get("row_count"),
                "dataset_name": item.get("dataset_name") or "",
                "status": "loaded",
                "message": messages[index] if index < len(messages) else "",
            }
        )
    return summaries


def _build_result_panel(response: dict, dashboard: dict) -> dict:
    return _api_build_result_panel(response, dashboard)
    outcome = response.get("task_outcome") if isinstance(response.get("task_outcome"), dict) else {}
    files: list[dict] = []
    seen: set[str] = set()
    sources: list[dict] = []
    for result in dashboard.get("model_results", []) if isinstance(dashboard.get("model_results"), list) else []:
        if isinstance(result, dict):
            sources.extend([item for item in result.get("artifacts", []) if isinstance(item, dict)])
    sources.extend([item for item in dashboard.get("artifacts", []) if isinstance(item, dict)] if isinstance(dashboard.get("artifacts"), list) else [])
    for item in sources:
        path = str(item.get("path") or item.get("display_path") or "")
        url = str(item.get("download_url") or "")
        key = url or path
        if not key or key in seen:
            continue
        seen.add(key)
        files.append(
            {
                "label": str(item.get("label") or item.get("name") or Path(path).name or "result file"),
                "path": path,
                "download_url": url,
                "kind": str(item.get("type") or item.get("category") or "artifact"),
            }
        )
    return {
        "has_results": bool(outcome.get("has_results") or files),
        "title": str(outcome.get("summary") or "Processing results"),
        "files": files[:12],
        "result_paths": outcome.get("result_paths") if isinstance(outcome.get("result_paths"), list) else [],
        "recommendations": outcome.get("recommendations") if isinstance(outcome.get("recommendations"), list) else [],
    }


def _attach_result_panel(service: GISWorkspaceService, user_id: str, response: dict) -> dict:
    response = _decorate_chat_response_messages(service, user_id, response)
    dashboard = _decorate_dashboard(service, user_id=user_id)
    return {**response, "result_panel": _build_result_panel(response, dashboard)}


def _relative_shared_download_url(file_path: str, user_id: str = "", job_id: str = "") -> str:
    return relative_shared_download_url(base_settings.workdir, file_path, user_id=user_id, job_id=job_id)


def _gscloud_product_key_from_resource(value: str) -> str:
    text = str(value or "").strip().lower()
    for product in GSCLOUD_PRODUCTS.values():
        if text in {product.key.lower(), product.resource_type.lower()}:
            return product.key
    return text


def _gscloud_account_mode_from_prompt(prompt: str) -> str:
    text = str(prompt or "")
    if "平台账号" in text or "账号池" in text:
        return "platform"
    if "自己的账号" in text or "个人账号" in text or "自有账号" in text:
        return "own"
    return "auto"


def _resolve_preflight_storage_state(body: DownloadPreflightIn) -> str:
    source_key = str(body.source_key or "gscloud").lower()
    user = commercial_service.get_user(body.user_id)
    mode = commercial_service.resolve_account_mode(user, body.account_mode, source_key)
    if mode == "own":
        return commercial_service.get_user_storage_state_path(body.user_id, source_key)
    check = commercial_service._select_platform_account(source_key)
    if not check.ok or not check.account_id:
        raise PermissionError(check.reason or "没有可用平台账号。")
    account = commercial_service.get_platform_account_private(check.account_id)
    return str(account.get("storage_state_path") or "")


def _dataset_map_kind(name: str, data_type: str) -> str:
    return dataset_map_kind(name, data_type)


def _raster_preview_path(service: GISWorkspaceService, dataset_name: str) -> Path:
    return MapLayerService(service).raster_preview_path(dataset_name)


def _ensure_raster_preview(service: GISWorkspaceService, dataset_name: str, user_id: str = "") -> dict:
    return MapLayerService(service).ensure_raster_preview(dataset_name, user_id=user_id)


def _read_vector_for_map(path: Path):
    return MapLayerService(workspace_for("anonymous")).read_vector_for_map(path)


def _vector_map_layer(name: str, gdf, *, layer_id: str = "", kind: str = "", meta: dict | None = None) -> dict | None:
    return MapLayerService(workspace_for("anonymous")).vector_map_layer(name, gdf, layer_id=layer_id, kind=kind, meta=meta)


def _local_library_boundary_layer() -> dict | None:
    global _LOCAL_LIBRARY_BOUNDARY_LAYER_CACHE
    if _LOCAL_LIBRARY_BOUNDARY_LAYER_CACHE is not None:
        return json.loads(json.dumps(_LOCAL_LIBRARY_BOUNDARY_LAYER_CACHE))
    try:
        item = local_library.get_item("lib_shandianhe_basin_boundary_full")
        path = Path(str(item.get("absolute_path") or ""))
        gdf = _read_vector_for_map(path)
        layer = _vector_map_layer(
            "闪电河流域边界",
            gdf,
            layer_id="local_library_shandianhe_basin_boundary",
            kind="boundary",
            meta={"source": "local_library", "item_id": item.get("item_id")},
        )
        if layer:
            _LOCAL_LIBRARY_BOUNDARY_LAYER_CACHE = json.loads(json.dumps(layer))
        return layer
    except Exception:
        return None


def _dedupe_boundary_layers(layers: list[dict]) -> list[dict]:
    seen: set[tuple[float, float, float, float]] = set()
    result: list[dict] = []
    for layer in layers:
        if layer.get("kind") != "boundary":
            result.append(layer)
            continue
        bounds = layer.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 4:
            result.append(layer)
            continue
        key = tuple(round(float(value), 6) for value in bounds)
        if key in seen:
            continue
        seen.add(key)
        result.append(layer)
    return result


def _workspace_map_layers(service: GISWorkspaceService, user_id: str = "") -> dict:
    payload = MapLayerService(service).workspace_layers(user_id=user_id)
    layers: list[dict] = list(payload.get("layers") or [])
    has_boundary = any(layer.get("kind") == "boundary" for layer in layers)
    if not has_boundary:
        fallback = _local_library_boundary_layer()
        if fallback:
            layers.insert(0, fallback)
    layers = _dedupe_boundary_layers(layers)
    payload["layers"] = layers
    return payload


app.include_router(
    create_data_sources_router(
        account_service=lambda: GSCloudAccountService(commercial_service),
        authenticated_user=_authenticated_request_user,
        audit=_audit,
        guard=guard,
    )
)
app.include_router(
    create_downloads_router(
        resume_service=lambda: DownloadResumeService(
            commercial_service,
            GSCloudAccountService(commercial_service),
            _maybe_start_gscloud_auto_download,
        ),
        authenticated_user=_authenticated_request_user,
        audit=_audit,
        guard=guard,
    )
)


@app.get("/api/status")
def status():
    llm_validation = validate_llm_config()
    return {
        "ok": True,
        "service": "GIS Agent Web API",
        "version": "1.4.0",
        "profile": "Web-only / LangChain 交互式 GIS 智能体 / 土壤水分融合建模 / 本地文件库 / 天地图底图与数据服务 / 国内资源下载 / 商业化账号体系",
        "desktop_removed": True,
        "local_library": {"enabled": True, "root": str(local_library.root)},
        "tianditu": {"enabled": bool(os.getenv("TIANDITU_TOKEN", "").strip())},
        "llm_status": {
            "status": llm_validation.get("status"),
            "provider": llm_validation.get("provider"),
            "model": llm_validation.get("model"),
            "api_key_present": llm_validation.get("api_key_present"),
            "intent_classifier": llm_validation.get("enable_llm_intent_classifier"),
            "fallback_to_rule_classifier": llm_validation.get("fallback_to_rule_classifier"),
        },
    }


@app.get("/api/llm/health")
def llm_health(network: bool = Query(default=False)):
    return check_llm_provider_health(skip_network=not network)


@app.get("/api/ops/config")
def ops_config():
    return validate_production_config()


def _tianditu_layer_url(layer: str, matrix_set: str = "w") -> str:
    token = os.getenv("TIANDITU_TOKEN", "").strip()
    return (
        f"https://t{{s}}.tianditu.gov.cn/{layer}_{matrix_set}/wmts?"
        f"SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER={layer}"
        f"&STYLE=default&TILEMATRIXSET={matrix_set}&FORMAT=tiles"
        f"&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}&tk={token}"
    )


@app.get("/api/tianditu/config")
def tianditu_config():
    token = os.getenv("TIANDITU_TOKEN", "").strip()
    default_basemap = os.getenv("TIANDITU_DEFAULT_BASEMAP", "vec").strip().lower() or "vec"
    enabled = bool(token)
    return {
        "enabled": enabled,
        "token_masked": (token[:4] + "***" + token[-4:]) if len(token) >= 8 else "",
        "default_basemap": default_basemap,
        "subdomains": ["0", "1", "2", "3", "4", "5", "6", "7"],
        "matrix_set": "w",
        "tile_url_templates": {
            "vector": _tianditu_layer_url("vec"),
            "vector_annotation": _tianditu_layer_url("cva"),
            "image": _tianditu_layer_url("img"),
            "image_annotation": _tianditu_layer_url("cia"),
            "terrain": _tianditu_layer_url("ter"),
            "terrain_annotation": _tianditu_layer_url("cta"),
        } if enabled else {},
        "capabilities": [
            "WMTS 矢量底图",
            "WMTS 影像底图",
            "WMTS 地形晕渲",
            "中文注记叠加",
            "地名搜索与逆地理编码可通过后端服务继续封装",
            "政区/道路/水系/居民地等数据 API 可作为辅助要素源",
        ],
        "setup_hint": "请在 .env 中配置 TIANDITU_TOKEN，并在天地图控制台限制浏览器端 Key 的域名/Referer。" if not enabled else "天地图 Token 已配置。",
    }




@app.get("/api/map/stations")
def map_stations(request: Request, user_id: str = Query(default="")):
    return guard(lambda: _load_station_collection(_require_request_user_if_present(request, user_id)))


@app.get("/api/map/layers")
def map_layers(request: Request, user_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        return _workspace_map_layers(workspace_for(authorized_user_id), user_id=authorized_user_id)

    return guard(run)


@app.post("/api/map/layers/refresh")
def refresh_map_layer(body: MapLayerRefreshIn, request: Request):
    def run():
        authorized_user_id = _require_request_user_if_present(request, body.user_id)
        service = workspace_for(authorized_user_id)
        if body.artifact_id:
            return MapLayerService(service).refresh_artifact(body.artifact_id, user_id=authorized_user_id)
        if body.dataset_name:
            layer = MapLayerService(service).dataset_layer({"name": body.dataset_name, "type": service.manager.get(body.dataset_name).data_type, "meta": service.manager.get(body.dataset_name).meta}, user_id=authorized_user_id)
            if not layer:
                raise FileNotFoundError(f"map layer not found: {body.dataset_name}")
            return {"dataset_name": body.dataset_name, "map_layer_id": layer["id"], "map_ready": True, "layer": layer}
        raise ValueError("artifact_id or dataset_name is required")

    return guard(run)


@app.get("/api/map/raster-preview")
def map_raster_preview(request: Request, user_id: str = Query(default=""), dataset_name: str = Query(...)):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = workspace_for(authorized_user_id)
        target = _raster_preview_path(service, dataset_name)
        if not target.exists():
            _ensure_raster_preview(service, dataset_name, user_id=authorized_user_id)
        if not target.exists():
            raise FileNotFoundError(f"raster preview not found: {dataset_name}")
        return FileResponse(str(target), media_type="image/png", filename=target.name)

    return guard(run)

@app.post("/api/auth/login")
def login(body: AuthIn, response: Response, request: Request):
    def run():
        session = commercial_service.authenticate_user(str(body.email), body.password)
        _set_session_cookies(response, session)
        _audit(request, user_id=str(session["user"].get("user_id") or ""), action="auth.login", resource_type="user", resource_id=str(session["user"].get("user_id") or ""))
        return {"user": session["user"], "expires_at": session.get("expires_at")}

    return guard(run)


@app.post("/api/auth/register")
def register(body: AuthIn, response: Response, request: Request):
    def run():
        commercial_service.register_user(str(body.email), body.password, plan="basic")
        session = commercial_service.authenticate_user(str(body.email), body.password)
        _set_session_cookies(response, session)
        _audit(request, user_id=str(session["user"].get("user_id") or ""), action="auth.register", resource_type="user", resource_id=str(session["user"].get("user_id") or ""))
        return {"user": session["user"], "expires_at": session.get("expires_at")}

    return guard(run)


@app.post("/api/auth/validate")
def validate(body: ValidateIn):
    return guard(lambda: commercial_service.validate_session(body.session_id, body.session_token))


@app.get("/api/auth/me")
def me(request: Request):
    def run():
        session_id, session_token = _request_session(request)
        return optional_authenticated_session(commercial_service, session_id=session_id, session_token=session_token)

    return guard(run)


@app.post("/api/auth/logout")
def logout(response: Response, request: Request):
    _clear_session_cookies(response)
    _audit(request, action="auth.logout")
    return {"ok": True}


@app.get("/api/chat/messages")
def messages(request: Request, user_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = workspace_for(authorized_user_id)
        return {"messages": _decorate_message_artifacts(service, service.current_messages(), user_id=authorized_user_id)}

    return guard(run)


@app.get("/api/chat/sessions")
def chat_sessions(request: Request, user_id: str = Query(default="")):
    def run():
        service = workspace_for(_require_request_user_if_present(request, user_id))
        return {
            "sessions": service.list_sessions(),
            "current_session_id": service.current_session_id,
            "messages": _decorate_message_artifacts(service, service.current_messages(), user_id=user_id),
        }

    return guard(run)


@app.post("/api/chat/sessions")
def create_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = workspace_for(_require_request_user_if_present(request, body.user_id))
        session_id = service.create_new_session(body.title or None)
        return {
            "session_id": session_id,
            "sessions": service.list_sessions(),
            "current_session_id": service.current_session_id,
            "messages": _decorate_message_artifacts(service, service.current_messages(), user_id=body.user_id),
        }

    return guard(run)


@app.post("/api/chat/sessions/switch")
def switch_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = workspace_for(_require_request_user_if_present(request, body.user_id))
        service.switch_session(body.session_id)
        return {
            "sessions": service.list_sessions(),
            "current_session_id": service.current_session_id,
            "messages": _decorate_message_artifacts(service, service.current_messages(), user_id=body.user_id),
        }

    return guard(run)


@app.get("/api/chat/models")
def chat_models(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
    def run():
        service = workspace_for(_require_request_user_if_present(request, user_id))
        if session_id:
            service.use_session_or_current(session_id)
        return service.chat_model_state(session_id or service.current_session_id)

    return guard(run)


@app.post("/api/chat/models/select")
def select_chat_model(body: ChatModelIn, request: Request):
    def run():
        service = workspace_for(_require_request_user_if_present(request, body.user_id))
        service.switch_session(body.session_id)
        return service.select_chat_model(body.model, body.session_id)

    return guard(run)


@app.post("/api/chat/sessions/rename")
def rename_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = workspace_for(_require_request_user_if_present(request, body.user_id))
        service.rename_session(body.session_id, body.title)
        return {"sessions": service.list_sessions(), "current_session_id": service.current_session_id}

    return guard(run)


@app.post("/api/chat/sessions/delete")
def delete_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = workspace_for(_require_request_user_if_present(request, body.user_id))
        current = service.delete_session(body.session_id)
        return {
            "current_session_id": current,
            "sessions": service.list_sessions(),
            "messages": _decorate_message_artifacts(service, service.current_messages(), user_id=body.user_id),
        }

    return guard(run)


@app.post("/api/chat/sessions/clear")
def clear_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = workspace_for(_require_request_user_if_present(request, body.user_id))
        if body.session_id:
            service.use_session_or_current(body.session_id)
        service.clear_current_chat()
        return {
            "current_session_id": service.current_session_id,
            "sessions": service.list_sessions(),
            "messages": _decorate_message_artifacts(service, service.current_messages(), user_id=body.user_id),
        }

    return guard(run)


@app.post("/api/chat/retry")
def retry_chat_message(body: ChatRetryIn, request: Request):
    def run():
        service = workspace_for(_require_request_user_if_present(request, body.user_id))
        if body.session_id:
            service.use_session_or_current(body.session_id)
        result = service.edit_user_message_and_retry(body.message_id, body.content)
        return _decorate_chat_response_messages(service, body.user_id, {**result, "messages": service.current_messages(), "sessions": service.list_sessions(), "current_session_id": service.current_session_id})

    return guard(run)


def _maybe_import_library_items_for_prompt(service: GISWorkspaceService, prompt: str) -> list[str]:
    text = (prompt or "").lower()
    trigger_words = ["本地文件库", "内置数据", "基础数据", "调用", "加载", "导入", "使用"]
    if not any(word in prompt for word in trigger_words):
        return []

    library_data = local_library.list_items()
    imported: list[str] = []
    for item in library_data.get("items", []):
        haystack = " ".join([
            str(item.get("name", "")),
            str(item.get("category", "")),
            str(item.get("description", "")),
            str(item.get("region", "")),
            " ".join(item.get("tags") or []),
        ]).lower()
        name_hit = str(item.get("name", "")).lower() and str(item.get("name", "")).lower() in text
        tag_hit = any(str(tag).lower() in text for tag in (item.get("tags") or []) if len(str(tag)) >= 2)
        domain_hit = ("行政" in prompt and "行政" in haystack) or ("降雨" in prompt and ("降雨" in haystack or "降水" in haystack or "precip" in haystack)) or ("降水" in prompt and ("降雨" in haystack or "降水" in haystack or "precip" in haystack)) or ("dem" in text and "dem" in haystack) or ("高程" in prompt and "高程" in haystack)
        if name_hit or tag_hit or domain_hit:
            try:
                imported.append(service.import_local_library_item(local_library.get_item(item["item_id"])))
            except Exception as exc:
                imported.append(f"导入 {item.get('name')} 失败：{exc}")
        if len(imported) >= 5:
            break
    return imported


def _extract_region_from_prompt(prompt: str) -> str:
    text = prompt or ""
    candidates = [
        "成都市", "成都", "四川省", "四川", "闪电河流域", "闪电河",
        "河北省", "中国", "全国"
    ]
    for item in candidates:
        if item in text:
            return "成都市" if item == "成都" else ("四川省" if item == "四川" else item)
    m = re.search(r"(?:下载|裁剪|覆盖|范围|区域为|研究区为)([^，。；;\s]{2,18})", text)
    if m:
        value = m.group(1).strip()
        value = re.sub(r"(范围|区域|DEM|数据|的)$", "", value)
        return value or "当前研究区"
    return "当前研究区"


def _extract_output_name_from_prompt(prompt: str, region: str, resource_type: str) -> str:
    text = prompt or ""
    for pat in [r"输出(?:为|名为)\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", r"保存为\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)", r"命名为\s*([A-Za-z0-9_\-\u4e00-\u9fff]+)"]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    if "成都" in region:
        return f"chengdu_{resource_type}"
    if "四川" in region:
        return f"sichuan_{resource_type}"
    if "闪电河" in region:
        return f"shandianhe_{resource_type}"
    safe_region = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", region or "region").strip("_")
    return f"{safe_region}_{resource_type}"


def _extract_year_from_prompt(prompt: str) -> str:
    m = re.search(r"(20\d{2}|19\d{2})\s*年?", prompt or "")
    return m.group(1) if m else ""


def _extract_cloud_max_from_prompt(prompt: str, default: float = 30.0) -> float:
    text = prompt or ""
    m = re.search(r"云量(?:小于|低于|不超过|<=|≤|<)?\s*(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1))
    return default


def _extract_max_scenes_from_prompt(prompt: str, default: int = 1) -> int:
    m = re.search(r"(?:下载|选择|获取)\s*(\d+)\s*(?:景|幅|个)", prompt or "")
    if m:
        return max(1, min(10, int(m.group(1))))
    return default


def _is_gscloud_dem_download_prompt(prompt: str) -> bool:
    text = (prompt or "").lower()
    if "dem" not in text and "高程" not in prompt:
        return False
    if "下载" not in prompt and "获取" not in prompt and "准备" not in prompt:
        return False
    return "地理空间数据云" in prompt or "平台账号" in prompt or "自己的账号" in prompt or "账号" in prompt


def _is_gscloud_landsat_download_prompt(prompt: str) -> bool:
    text = prompt or ""
    product = match_gscloud_product(text)
    if product is None or product.key != LANDSAT8_OLI_TIRS.key:
        return False
    if not any(word in text for word in ("下载", "获取", "准备", "检索")):
        return False
    return "地理空间数据云" in text or "平台账号" in text or "自己的账号" in text or "账号" in text or "Landsat" in text or "landsat" in text


def _is_gscloud_modnd1d_download_prompt(prompt: str) -> bool:
    text = prompt or ""
    product = match_gscloud_product(text)
    if product is None or product.key != MODND1D_CHINA_500M_NDVI_DAILY.key:
        return False
    if not any(word in text for word in ("下载", "获取", "准备", "检索")):
        return False
    return "地理空间数据云" in text or "平台账号" in text or "自己的账号" in text or "账号" in text or "MODND1D" in text.upper() or "NDVI" in text.upper()


def _is_gscloud_modl1d_download_prompt(prompt: str) -> bool:
    text = prompt or ""
    product = match_gscloud_product(text)
    if product is None or product.key != MODL1D_CHINA_1KM_LST_DAILY.key:
        return False
    if not any(word in text for word in ("下载", "获取", "准备", "检索")):
        return False
    upper = text.upper()
    return "地理空间数据云" in text or "平台账号" in text or "自己的账号" in text or "账号" in text or "MODL1D" in upper or "LST" in upper or "地表温度" in text


def _is_gscloud_modev1f_download_prompt(prompt: str) -> bool:
    text = prompt or ""
    product = match_gscloud_product(text)
    if product is None or product.key != MODEV1F_CHINA_250M_EVI_5DAY.key:
        return False
    if not any(word in text for word in ("下载", "获取", "准备", "检索")):
        return False
    upper = text.upper()
    return (
        "地理空间数据云" in text
        or "平台账号" in text
        or "自己的账号" in text
        or "账号" in text
        or "MODEV1F" in upper
        or "EVI" in upper
        or "五天合成" in text
    )


def _submit_direct_gscloud_modev1f_from_chat(user_id: str, prompt: str) -> dict:
    if not str(user_id or "").strip():
        return {
            "reply": "你还没有登录账号。请先登录或注册 BASIC 账号，再提交 MODEV1F EVI 下载任务。",
            "model": "direct-router",
            "reason": "download_requires_login",
        }
    if start_gscloud_modev1f_process is None:
        return {
            "reply": "MODEV1F 后台下载模块未正确加载，请检查 scene_jobs.py 与 gscloud_scene_worker.py。",
            "model": "direct-router",
            "reason": "modev1f_worker_unavailable",
        }

    region = _extract_region_from_prompt(prompt)
    account_mode = _gscloud_account_mode_from_prompt(prompt)
    output_name = _extract_output_name_from_prompt(prompt, region, "modev1f_evi")
    year = _extract_year_from_prompt(prompt)
    max_scenes = _extract_max_scenes_from_prompt(prompt, default=1)
    job = commercial_service.submit_job(
        user_id=user_id,
        source_key="gscloud",
        resource_type=MODEV1F_CHINA_250M_EVI_5DAY.resource_type,
        region=region,
        account_mode=account_mode,
        request_text=prompt,
        output_name=output_name,
    )
    account_mode = str(job.get("account_mode") or account_mode)

    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job["job_id"])
    except Exception:
        state_path = ""

    scene_job = None
    if state_path and Path(state_path).exists():
        commercial_service._update_job(job["job_id"], status="running", progress=5, stage="starting_modev1f_scene_worker")
        scene_job = start_gscloud_modev1f_process(
            workdir=base_settings.workdir,
            job_id=job["job_id"],
            region=region,
            year=year,
            max_scenes=max_scenes,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MODEV1F 中国 250M EVI 五天合成产品下载任务，并启动地理空间数据云自动检索下载。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MODEV1F_CHINA_250M_EVI_5DAY.name}\n"
            f"区域：{region}\n"
            f"年份：{year or '未指定'}\n"
            f"数据筛选：强制只下载“数据=有”的记录\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"后台场景任务：{(scene_job or {}).get('scene_job_id', '')}\n\n"
            f"你可以继续输入：查看商业下载任务 {job['job_id']} 的状态。"
        )
    else:
        commercial_service._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MODEV1F EVI 下载任务，但尚未启动下载，因为没有找到可用的地理空间数据云登录态。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MODEV1F_CHINA_250M_EVI_5DAY.name}\n"
            f"区域：{region}\n"
            f"数据筛选：后续启动时会强制只下载“数据=有”的记录\n"
            f"当前状态：waiting_login\n\n"
            f"登录态配置完成后，请重新提交 MODEV1F EVI 下载任务。"
        )
    return {"reply": reply, "model": "direct-router", "reason": "deterministic_gscloud_modev1f_download", "job": job, "scene_job": scene_job}


def _is_gscloud_mod021km_download_prompt(prompt: str) -> bool:
    text = prompt or ""
    product = match_gscloud_product(text)
    if product is None or product.key != MOD021KM_1KM_SURFACE_REFLECTANCE.key:
        return False
    if not any(word in text for word in ("下载", "获取", "准备", "检索")):
        return False
    upper = text.upper()
    return (
        "地理空间数据云" in text
        or "平台账号" in text
        or "自己的账号" in text
        or "账号" in text
        or "MOD021KM" in upper
        or "MODISL1B" in upper
        or "反射率" in text
    )


def _submit_direct_gscloud_mod021km_from_chat(user_id: str, prompt: str) -> dict:
    if not str(user_id or "").strip():
        return {
            "reply": "你还没有登录账号。请先登录或注册 BASIC 账号，再提交 MOD021KM 地表反射率下载任务。",
            "model": "direct-router",
            "reason": "download_requires_login",
        }
    if start_gscloud_mod021km_process is None:
        return {
            "reply": "MOD021KM 后台下载模块未正确加载，请检查 scene_jobs.py 与 gscloud_scene_worker.py。",
            "model": "direct-router",
            "reason": "mod021km_worker_unavailable",
        }

    region = _extract_region_from_prompt(prompt)
    account_mode = _gscloud_account_mode_from_prompt(prompt)
    output_name = _extract_output_name_from_prompt(prompt, region, "mod021km_reflectance")
    year = _extract_year_from_prompt(prompt)
    max_scenes = _extract_max_scenes_from_prompt(prompt, default=1)
    job = commercial_service.submit_job(
        user_id=user_id,
        source_key="gscloud",
        resource_type=MOD021KM_1KM_SURFACE_REFLECTANCE.resource_type,
        region=region,
        account_mode=account_mode,
        request_text=prompt,
        output_name=output_name,
    )
    account_mode = str(job.get("account_mode") or account_mode)

    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job["job_id"])
    except Exception:
        state_path = ""

    scene_job = None
    if state_path and Path(state_path).exists():
        commercial_service._update_job(job["job_id"], status="running", progress=5, stage="starting_mod021km_scene_worker")
        scene_job = start_gscloud_mod021km_process(
            workdir=base_settings.workdir,
            job_id=job["job_id"],
            region=region,
            year=year,
            max_scenes=max_scenes,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MOD021KM 1KM 地表反射率下载任务，并启动地理空间数据云自动检索下载。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MOD021KM_1KM_SURFACE_REFLECTANCE.name}\n"
            f"区域：{region}\n"
            f"年份：{year or '未指定'}\n"
            f"数据筛选：强制只下载“数据=有”的记录\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"后台场景任务：{(scene_job or {}).get('scene_job_id', '')}\n\n"
            f"你可以继续输入：查看商业下载任务 {job['job_id']} 的状态。"
        )
    else:
        commercial_service._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MOD021KM 地表反射率下载任务，但尚未启动下载，因为没有找到可用的地理空间数据云登录态。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MOD021KM_1KM_SURFACE_REFLECTANCE.name}\n"
            f"区域：{region}\n"
            f"数据筛选：后续启动时会强制只下载“数据=有”的记录\n"
            f"当前状态：waiting_login\n\n"
            f"登录态配置完成后，请重新提交 MOD021KM 地表反射率下载任务。"
        )
    return {"reply": reply, "model": "direct-router", "reason": "deterministic_gscloud_mod021km_download", "job": job, "scene_job": scene_job}


def _sentinel2_processing_level_from_prompt(prompt: str) -> str:
    upper = str(prompt or "").upper().replace(" ", "")
    if "L2A" in upper or "MSIL2A" in upper:
        return "MSIL2A"
    if "L1C" in upper or "MSIL1C" in upper:
        return "MSIL1C"
    return ""


def _is_gscloud_sentinel2_download_prompt(prompt: str) -> bool:
    text = prompt or ""
    product = match_gscloud_product(text)
    if product is None or product.key != SENTINEL2_MSI.key:
        return False
    if not any(word in text for word in ("下载", "获取", "准备", "检索")):
        return False
    upper = text.upper()
    return (
        "地理空间数据云" in text
        or "平台账号" in text
        or "自己的账号" in text
        or "账号" in text
        or "SENTINEL" in upper
        or "S2" in upper
        or "哨兵" in text
    )


def _submit_direct_gscloud_sentinel2_from_chat(user_id: str, prompt: str) -> dict:
    if not str(user_id or "").strip():
        return {
            "reply": "你还没有登录账号。请先登录或注册 BASIC 账号，再提交 Sentinel-2 下载任务。",
            "model": "direct-router",
            "reason": "download_requires_login",
        }
    if start_gscloud_sentinel2_process is None:
        return {
            "reply": "Sentinel-2 后台下载模块未正确加载，请检查 scene_jobs.py 与 gscloud_scene_worker.py。",
            "model": "direct-router",
            "reason": "sentinel2_worker_unavailable",
        }

    region = _extract_region_from_prompt(prompt)
    account_mode = _gscloud_account_mode_from_prompt(prompt)
    output_name = _extract_output_name_from_prompt(prompt, region, "sentinel2_msi")
    year = _extract_year_from_prompt(prompt)
    max_scenes = _extract_max_scenes_from_prompt(prompt, default=1)
    processing_level = _sentinel2_processing_level_from_prompt(prompt)
    job = commercial_service.submit_job(
        user_id=user_id,
        source_key="gscloud",
        resource_type=SENTINEL2_MSI.resource_type,
        region=region,
        account_mode=account_mode,
        request_text=prompt,
        output_name=output_name,
    )
    account_mode = str(job.get("account_mode") or account_mode)

    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job["job_id"])
    except Exception:
        state_path = ""

    scene_job = None
    if state_path and Path(state_path).exists():
        commercial_service._update_job(job["job_id"], status="running", progress=5, stage="starting_sentinel2_scene_worker")
        scene_job = start_gscloud_sentinel2_process(
            workdir=base_settings.workdir,
            job_id=job["job_id"],
            region=region,
            year=year,
            processing_level=processing_level,
            max_scenes=max_scenes,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 Sentinel-2 下载任务，并启动地理空间数据云自动检索下载。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{SENTINEL2_MSI.name}\n"
            f"区域：{region}\n"
            f"年份：{year or '未指定'}\n"
            f"处理级别：{processing_level or '未限定'}\n"
            f"数据筛选：强制只下载“数据=有”的记录\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"后台场景任务：{(scene_job or {}).get('scene_job_id', '')}\n\n"
            f"你可以继续输入：查看商业下载任务 {job['job_id']} 的状态。"
        )
    else:
        commercial_service._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 Sentinel-2 下载任务，但尚未启动下载，因为没有找到可用的地理空间数据云登录态。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{SENTINEL2_MSI.name}\n"
            f"区域：{region}\n"
            f"数据筛选：后续启动时会强制只下载“数据=有”的记录\n"
            f"当前状态：waiting_login\n\n"
            f"登录态配置完成后，请重新提交 Sentinel-2 下载任务。"
        )
    return {"reply": reply, "model": "direct-router", "reason": "deterministic_gscloud_sentinel2_download", "job": job, "scene_job": scene_job}


def _submit_direct_gscloud_modl1d_from_chat(user_id: str, prompt: str) -> dict:
    if not str(user_id or "").strip():
        return {
            "reply": "你还没有登录账号。请先登录或注册 BASIC 账号，再提交 MODL1D 地表温度下载任务。",
            "model": "direct-router",
            "reason": "download_requires_login",
        }
    if start_gscloud_modl1d_process is None:
        return {
            "reply": "MODL1D 后台下载模块未正确加载，请检查 scene_jobs.py 与 gscloud_scene_worker.py。",
            "model": "direct-router",
            "reason": "modl1d_worker_unavailable",
        }

    region = _extract_region_from_prompt(prompt)
    account_mode = _gscloud_account_mode_from_prompt(prompt)
    output_name = _extract_output_name_from_prompt(prompt, region, "modl1d_lst")
    year = _extract_year_from_prompt(prompt)
    max_scenes = _extract_max_scenes_from_prompt(prompt, default=1)
    include_quality = "qc" in prompt.lower() or "质量" in prompt or "qcd" in prompt.lower() or "qcn" in prompt.lower()
    job = commercial_service.submit_job(
        user_id=user_id,
        source_key="gscloud",
        resource_type=MODL1D_CHINA_1KM_LST_DAILY.resource_type,
        region=region,
        account_mode=account_mode,
        request_text=prompt,
        output_name=output_name,
    )
    account_mode = str(job.get("account_mode") or account_mode)

    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job["job_id"])
    except Exception:
        state_path = ""

    scene_job = None
    if state_path and Path(state_path).exists():
        commercial_service._update_job(job["job_id"], status="running", progress=5, stage="starting_modl1d_scene_worker")
        scene_job = start_gscloud_modl1d_process(
            workdir=base_settings.workdir,
            job_id=job["job_id"],
            region=region,
            year=year,
            include_quality=include_quality,
            max_scenes=max_scenes,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MODL1D 中国 1KM 地表温度每天产品下载任务，并启动地理空间数据云自动检索下载。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MODL1D_CHINA_1KM_LST_DAILY.name}\n"
            f"区域：{region}\n"
            f"年份：{year or '未指定'}\n"
            f"数据筛选：强制只下载“数据=有”的记录\n"
            f"产品筛选：{'LTD/LTN + QCD/QCN' if include_quality else 'LTD/LTN 主产品，默认跳过质量控制'}\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"后台场景任务：{(scene_job or {}).get('scene_job_id', '')}\n\n"
            f"你可以继续输入：查看商业下载任务 {job['job_id']} 的状态。"
        )
    else:
        commercial_service._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MODL1D 地表温度下载任务，但尚未启动下载，因为没有找到可用的地理空间数据云登录态。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MODL1D_CHINA_1KM_LST_DAILY.name}\n"
            f"区域：{region}\n"
            f"数据筛选：后续启动时会强制只下载“数据=有”的记录\n"
            f"当前状态：waiting_login\n\n"
            f"登录态配置完成后，请重新提交 MODL1D 地表温度下载任务。"
        )
    return {"reply": reply, "model": "direct-router", "reason": "deterministic_gscloud_modl1d_download", "job": job, "scene_job": scene_job}


def _submit_direct_gscloud_modnd1d_from_chat(user_id: str, prompt: str) -> dict:
    if not str(user_id or "").strip():
        return {
            "reply": "你还没有登录账号。请先登录或注册 BASIC 账号，再提交 MODND1D NDVI 下载任务。",
            "model": "direct-router",
            "reason": "download_requires_login",
        }
    if start_gscloud_modnd1d_process is None:
        return {
            "reply": "MODND1D 后台下载模块未正确加载，请检查 scene_jobs.py 与 gscloud_scene_worker.py。",
            "model": "direct-router",
            "reason": "modnd1d_worker_unavailable",
        }

    region = _extract_region_from_prompt(prompt)
    account_mode = _gscloud_account_mode_from_prompt(prompt)
    output_name = _extract_output_name_from_prompt(prompt, region, "modnd1d_ndvi")
    year = _extract_year_from_prompt(prompt)
    max_scenes = _extract_max_scenes_from_prompt(prompt, default=1)
    include_qc = "qc" in prompt.lower() or "质量" in prompt
    job = commercial_service.submit_job(
        user_id=user_id,
        source_key="gscloud",
        resource_type=MODND1D_CHINA_500M_NDVI_DAILY.resource_type,
        region=region,
        account_mode=account_mode,
        request_text=prompt,
        output_name=output_name,
    )
    account_mode = str(job.get("account_mode") or account_mode)

    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job["job_id"])
    except Exception:
        state_path = ""

    scene_job = None
    if state_path and Path(state_path).exists():
        commercial_service._update_job(job["job_id"], status="running", progress=5, stage="starting_modnd1d_scene_worker")
        scene_job = start_gscloud_modnd1d_process(
            workdir=base_settings.workdir,
            job_id=job["job_id"],
            region=region,
            year=year,
            include_qc=include_qc,
            max_scenes=max_scenes,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MODND1D 中国 500M NDVI 每天产品下载任务，并启动地理空间数据云自动检索下载。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MODND1D_CHINA_500M_NDVI_DAILY.name}\n"
            f"区域：{region}\n"
            f"年份：{year or '未指定'}\n"
            f"数据筛选：强制只下载“数据=有”的记录\n"
            f"产品筛选：{'NDVI + QC' if include_qc else '仅 NDVI 主产品，默认跳过 QC'}\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"后台场景任务：{(scene_job or {}).get('scene_job_id', '')}\n\n"
            f"你可以继续输入：查看商业下载任务 {job['job_id']} 的状态。"
        )
    else:
        commercial_service._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 MODND1D NDVI 下载任务，但尚未启动下载，因为没有找到可用的地理空间数据云登录态。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{MODND1D_CHINA_500M_NDVI_DAILY.name}\n"
            f"区域：{region}\n"
            f"数据筛选：后续启动时会强制只下载“数据=有”的记录\n"
            f"当前状态：waiting_login\n\n"
            f"登录态配置完成后，请重新提交 MODND1D NDVI 下载任务。"
        )
    return {"reply": reply, "model": "direct-router", "reason": "deterministic_gscloud_modnd1d_download", "job": job, "scene_job": scene_job}


def _submit_direct_gscloud_landsat8_from_chat(user_id: str, prompt: str) -> dict:
    if not str(user_id or "").strip():
        return {
            "reply": "你还没有登录账号。请先登录或注册 BASIC 账号，再提交 Landsat 8 下载任务。",
            "model": "direct-router",
            "reason": "download_requires_login",
        }
    if start_gscloud_landsat8_process is None:
        return {
            "reply": "Landsat 8 后台下载模块未正确加载，请检查 core/commercial/scene_jobs.py 与 worker 配置。",
            "model": "direct-router",
            "reason": "landsat_worker_unavailable",
        }

    region = _extract_region_from_prompt(prompt)
    account_mode = _gscloud_account_mode_from_prompt(prompt)
    output_name = _extract_output_name_from_prompt(prompt, region, "landsat8")
    year = _extract_year_from_prompt(prompt)
    cloud_max = _extract_cloud_max_from_prompt(prompt, default=30.0)
    max_scenes = _extract_max_scenes_from_prompt(prompt, default=1)
    job = commercial_service.submit_job(
        user_id=user_id,
        source_key="gscloud",
        resource_type=LANDSAT8_OLI_TIRS.resource_type,
        region=region,
        account_mode=account_mode,
        request_text=prompt,
        output_name=output_name,
    )
    account_mode = str(job.get("account_mode") or account_mode)

    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job["job_id"])
    except Exception:
        state_path = ""

    scene_job = None
    if state_path and Path(state_path).exists():
        commercial_service._update_job(job["job_id"], status="running", progress=5, stage="starting_landsat8_scene_worker")
        scene_job = start_gscloud_landsat8_process(
            workdir=base_settings.workdir,
            job_id=job["job_id"],
            region=region,
            year=year,
            cloud_max=cloud_max,
            max_scenes=max_scenes,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 Landsat 8 OLI_TIRS 下载任务，并启动地理空间数据云自动检索下载。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{LANDSAT8_OLI_TIRS.name}\n"
            f"区域：{region}\n"
            f"年份：{year or '未指定'}\n"
            f"云量阈值：≤ {cloud_max}%\n"
            f"数据筛选：强制只下载“数据=有”的记录\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"后台场景任务：{(scene_job or {}).get('scene_job_id', '')}\n\n"
            f"你可以继续输入：查看商业下载任务 {job['job_id']} 的状态。"
        )
    else:
        commercial_service._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        job = commercial_service.get_job(job["job_id"])
        reply = (
            f"已创建 Landsat 8 OLI_TIRS 下载任务，但尚未启动下载，因为没有找到可用的地理空间数据云登录态。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"产品：{LANDSAT8_OLI_TIRS.name}\n"
            f"区域：{region}\n"
            f"云量阈值：≤ {cloud_max}%\n"
            f"数据筛选：后续启动时会强制只下载“数据=有”的记录\n"
            f"当前状态：waiting_login\n\n"
            f"登录态配置完成后，请重新提交 Landsat 8 下载任务，或后续扩展为按任务编号启动。"
        )
    return {"reply": reply, "model": "direct-router", "reason": "deterministic_gscloud_landsat8_download", "job": job, "scene_job": scene_job}


def _submit_direct_gscloud_dem_from_chat(user_id: str, prompt: str) -> dict:
    if not str(user_id or "").strip():
        return {
            "reply": "你还没有登录账号。请先登录或注册 BASIC 账号，再提交地理空间数据云 DEM 下载任务。",
            "model": "direct-router",
            "reason": "download_requires_login",
        }
    region = _extract_region_from_prompt(prompt)
    account_mode = _gscloud_account_mode_from_prompt(prompt)
    output_name = _extract_output_name_from_prompt(prompt, region, "dem")
    job = commercial_service.submit_job(
        user_id=user_id,
        source_key="gscloud",
        resource_type="dem",
        region=region,
        account_mode=account_mode,
        request_text=prompt,
        output_name=output_name,
    )
    account_mode = str(job.get("account_mode") or account_mode)

    # Do not let the LLM invent a job id. The real job_id below is the only valid one.
    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job["job_id"])
    except Exception:
        state_path = ""

    auto_started = False
    auto_tile_job = None
    if state_path and Path(state_path).exists() and start_gscloud_tile_process is not None:
        commercial_service._update_job(job["job_id"], status="running", progress=5, stage="starting_auto_tile_worker")
        auto_tile_job = start_gscloud_tile_process(
            workdir=base_settings.workdir,
            job_id=job["job_id"],
            region=region,
            region_dataset="",
            dataset_id="310",
            max_tiles=0,
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        job = commercial_service.get_job(job["job_id"])
        auto_started = True
    else:
        commercial_service._update_job(job["job_id"], status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        job = commercial_service.get_job(job["job_id"])

    if auto_started:
        reply = (
            f"已创建真实 DEM 下载任务，并启动地理空间数据云自动分幅下载。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"区域：{region}\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"后台分幅任务：{(auto_tile_job or {}).get('tile_job_id', '')}\n\n"
            f"你可以继续输入：查看商业下载任务 {job['job_id']} 的状态。"
        )
    else:
        if account_mode == "own":
            next_step = "请点击聊天中的“去登录”，或打开“设置 → 我的数据源账号”完成官方网页登录。"
        else:
            next_step = "请先在服务器后台 .env 中配置平台账号 storage_state，或运行平台账号登录态保存脚本。"
        reply = (
            f"已创建真实 DEM 下载任务，但尚未启动下载，因为没有找到可用的地理空间数据云登录态。\n\n"
            f"任务编号：{job['job_id']}\n"
            f"区域：{region}\n"
            f"账号模式：{account_mode}\n"
            f"输出名：{output_name}\n"
            f"当前状态：waiting_login\n\n"
            f"下一步：{next_step}\n"
            "登录成功后点击“继续下载”，系统会恢复当前任务。"
        )
    result = {"reply": reply, "model": "direct-router", "reason": "deterministic_gscloud_dem_download", "job": job}
    if job.get("status") == "waiting_login":
        result["reply"] = (
            "这个数据源需要登录地理空间数据云账号后才能下载。"
            "任务尚未开始下载，登录成功后可直接继续当前任务。"
        )
        result["action_required"] = {
            "type": "login_required",
            "provider": "gscloud",
            "job_id": job["job_id"],
            "user_message": "需要登录地理空间数据云账号。",
            "actions": ["login", "cancel"],
        }
    return result


def _submit_gscloud_intent_route_from_chat(user_id: str, prompt: str, route: GSCloudIntentRoute) -> dict:
    product_key = route.product_key
    if product_key == MODL1D_CHINA_1KM_LST_DAILY.key:
        return _submit_direct_gscloud_modl1d_from_chat(user_id, prompt)
    if product_key == MODND1D_CHINA_500M_NDVI_DAILY.key:
        return _submit_direct_gscloud_modnd1d_from_chat(user_id, prompt)
    if product_key == MODEV1F_CHINA_250M_EVI_5DAY.key:
        return _submit_direct_gscloud_modev1f_from_chat(user_id, prompt)
    if product_key == MOD021KM_1KM_SURFACE_REFLECTANCE.key:
        return _submit_direct_gscloud_mod021km_from_chat(user_id, prompt)
    if product_key == SENTINEL2_MSI.key:
        return _submit_direct_gscloud_sentinel2_from_chat(user_id, prompt)
    if product_key == LANDSAT8_OLI_TIRS.key:
        return _submit_direct_gscloud_landsat8_from_chat(user_id, prompt)
    if product_key == "gscloud_dem":
        return _submit_direct_gscloud_dem_from_chat(user_id, prompt)
    return {
        "reply": "我识别到你可能要下载地理空间数据云数据，但还不能确定具体产品。请补充产品名，例如 Sentinel-2、Landsat 8、NDVI、EVI、LST、MOD021KM 或 DEM。",
        "model": "direct-router",
        "reason": "gscloud_intent_unknown_product",
    }


def _maybe_start_gscloud_auto_download(job: dict, region: str = "") -> dict:
    """Start the background GSCloud worker when a valid login state exists."""
    source_key = str(job.get("source_key") or "").lower()
    resource_type = str(job.get("resource_type") or "").lower()
    if source_key != "gscloud":
        return {"auto_supported": False, "auto_started": False, "reason": "not_gscloud"}

    job_id = str(job.get("job_id") or "")
    state_path = ""
    try:
        state_path = commercial_service.resolve_job_storage_state_path(job_id)
    except Exception:
        state_path = ""
    if not state_path or not Path(state_path).exists():
        if hasattr(commercial_service, "_release_platform_reservation"):
            commercial_service._release_platform_reservation(job_id, "release_waiting_login_platform_download")
        commercial_service._update_job(job_id, status="waiting_login", progress=5, stage="needs_gscloud_login_state")
        return {"auto_supported": True, "auto_started": False, "reason": "waiting_login"}

    actual_region = region or str(job.get("region") or "") or "当前研究区"
    request_text = str(job.get("request_text") or "")
    year = _extract_year_from_prompt(request_text) or str(job.get("start_date") or "")[:4]

    if resource_type == MODL1D_CHINA_1KM_LST_DAILY.resource_type:
        if start_gscloud_modl1d_process is None:
            return {"auto_supported": True, "auto_started": False, "reason": "modl1d_worker_unavailable"}
        commercial_service._update_job(job_id, status="running", progress=5, stage="starting_modl1d_scene_worker")
        scene_job = start_gscloud_modl1d_process(
            workdir=base_settings.workdir,
            job_id=job_id,
            region=actual_region,
            year=year,
            start_date=str(job.get("start_date") or ""),
            end_date=str(job.get("end_date") or ""),
            include_quality=("qc" in request_text.lower() or "质量" in request_text),
            max_scenes=_extract_max_scenes_from_prompt(request_text, default=1),
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "scene_job": scene_job}

    if resource_type == MODND1D_CHINA_500M_NDVI_DAILY.resource_type:
        if start_gscloud_modnd1d_process is None:
            return {"auto_supported": True, "auto_started": False, "reason": "modnd1d_worker_unavailable"}
        commercial_service._update_job(job_id, status="running", progress=5, stage="starting_modnd1d_scene_worker")
        scene_job = start_gscloud_modnd1d_process(
            workdir=base_settings.workdir,
            job_id=job_id,
            region=actual_region,
            year=year,
            start_date=str(job.get("start_date") or ""),
            end_date=str(job.get("end_date") or ""),
            include_qc=("qc" in request_text.lower() or "质量" in request_text),
            max_scenes=_extract_max_scenes_from_prompt(request_text, default=1),
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "scene_job": scene_job}

    if resource_type == MODEV1F_CHINA_250M_EVI_5DAY.resource_type:
        if start_gscloud_modev1f_process is None:
            return {"auto_supported": True, "auto_started": False, "reason": "modev1f_worker_unavailable"}
        commercial_service._update_job(job_id, status="running", progress=5, stage="starting_modev1f_scene_worker")
        scene_job = start_gscloud_modev1f_process(
            workdir=base_settings.workdir,
            job_id=job_id,
            region=actual_region,
            year=year,
            start_date=str(job.get("start_date") or ""),
            end_date=str(job.get("end_date") or ""),
            max_scenes=_extract_max_scenes_from_prompt(request_text, default=1),
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "scene_job": scene_job}

    if resource_type == MOD021KM_1KM_SURFACE_REFLECTANCE.resource_type:
        if start_gscloud_mod021km_process is None:
            return {"auto_supported": True, "auto_started": False, "reason": "mod021km_worker_unavailable"}
        commercial_service._update_job(job_id, status="running", progress=5, stage="starting_mod021km_scene_worker")
        scene_job = start_gscloud_mod021km_process(
            workdir=base_settings.workdir,
            job_id=job_id,
            region=actual_region,
            year=year,
            start_date=str(job.get("start_date") or ""),
            end_date=str(job.get("end_date") or ""),
            max_scenes=_extract_max_scenes_from_prompt(request_text, default=1),
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "scene_job": scene_job}

    if resource_type == SENTINEL2_MSI.resource_type:
        if start_gscloud_sentinel2_process is None:
            return {"auto_supported": True, "auto_started": False, "reason": "sentinel2_worker_unavailable"}
        commercial_service._update_job(job_id, status="running", progress=5, stage="starting_sentinel2_scene_worker")
        scene_job = start_gscloud_sentinel2_process(
            workdir=base_settings.workdir,
            job_id=job_id,
            region=actual_region,
            year=year,
            start_date=str(job.get("start_date") or ""),
            end_date=str(job.get("end_date") or ""),
            processing_level=_sentinel2_processing_level_from_prompt(request_text),
            max_scenes=_extract_max_scenes_from_prompt(request_text, default=1),
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "scene_job": scene_job}

    if resource_type == LANDSAT8_OLI_TIRS.resource_type:
        if start_gscloud_landsat8_process is None:
            return {"auto_supported": True, "auto_started": False, "reason": "landsat_worker_unavailable"}
        commercial_service._update_job(job_id, status="running", progress=5, stage="starting_landsat8_scene_worker")
        scene_job = start_gscloud_landsat8_process(
            workdir=base_settings.workdir,
            job_id=job_id,
            region=actual_region,
            year=year,
            start_date=str(job.get("start_date") or ""),
            end_date=str(job.get("end_date") or ""),
            cloud_max=_extract_cloud_max_from_prompt(request_text, default=30.0),
            max_scenes=_extract_max_scenes_from_prompt(request_text, default=1),
            timeout_seconds=1800,
            headless=True,
            auto_load=True,
        )
        return {"auto_supported": True, "auto_started": True, "reason": "started", "scene_job": scene_job}

    if resource_type != "dem":
        return {"auto_supported": False, "auto_started": False, "reason": "unsupported_gscloud_resource_type"}
    if start_gscloud_tile_process is None:
        return {"auto_supported": True, "auto_started": False, "reason": "tile_worker_unavailable"}

    commercial_service._update_job(job_id, status="running", progress=5, stage="starting_auto_tile_worker")
    tile_job = start_gscloud_tile_process(
        workdir=base_settings.workdir,
        job_id=job_id,
        region=actual_region,
        region_dataset="",
        dataset_id="310",
        max_tiles=0,
        timeout_seconds=1800,
        headless=True,
        auto_load=True,
    )
    return {"auto_supported": True, "auto_started": True, "reason": "started", "auto_tile_job": tile_job}


def _is_commercial_download_status_prompt(prompt: str) -> bool:
    text = str(prompt or "")
    return bool(re.search(r"\bjob_[A-Za-z0-9_\-]+\b", text)) and any(word in text for word in ("查看", "查询", "状态", "进度"))


def _format_commercial_download_status(prompt: str, user_id: str) -> dict:
    match = re.search(r"\b(job_[A-Za-z0-9_\-]+)\b", str(prompt or ""))
    if not match:
        raise ValueError("请提供商业下载任务编号，例如 job_xxxxxxxxxxxx。")
    job_id = match.group(1)
    job = require_resource_owner(commercial_service.get_job(job_id), user_id=user_id, resource_name="download job")
    status = str(job.get("status") or "")
    stage = str(job.get("stage") or "")
    progress = job.get("progress", 0)
    tile_jobs: list[dict] = []
    if list_gscloud_tile_jobs is not None:
        tile_jobs = [item for item in list_gscloud_tile_jobs(commercial_service.workdir, limit=50) if item.get("job_id") == job_id]
    latest_tile = tile_jobs[0] if tile_jobs else None
    scene_jobs: list[dict] = []
    if list_gscloud_scene_jobs is not None:
        scene_jobs = [item for item in list_gscloud_scene_jobs(commercial_service.workdir, limit=50) if item.get("job_id") == job_id]
    latest_scene = scene_jobs[0] if scene_jobs else None

    lines = [
        f"商业下载任务状态：{job_id}",
        "",
        f"- 状态：{status or 'unknown'}",
        f"- 阶段：{stage or 'unknown'}",
        f"- 进度：{progress}%",
        f"- 数据源：{job.get('source_key') or '--'}",
        f"- 数据类型：{job.get('resource_type') or '--'}",
        f"- 区域：{job.get('region') or '--'}",
        f"- 账号模式：{job.get('account_mode') or '--'}",
        f"- 输出名：{job.get('output_name') or '--'}",
        f"- 更新时间：{job.get('updated_at') or '--'}",
    ]
    if job.get("error_message"):
        lines.append(f"- 错误信息：{job.get('error_message')}")
    if job.get("output_path"):
        lines.append(f"- 输出路径：{job.get('output_path')}")
    if job.get("zip_path"):
        lines.append(f"- 结果压缩包：{job.get('zip_path')}")
    if latest_tile:
        lines.extend([
            "",
            f"关联自动分幅任务：{latest_tile.get('tile_job_id')}",
            f"- 分幅状态：{latest_tile.get('state') or '--'}",
            f"- 分幅进度说明：{latest_tile.get('message') or '--'}",
            f"- 状态文件：{latest_tile.get('status_path') or '--'}",
        ])
        if latest_tile.get("error"):
            lines.append(f"- 分幅错误：{latest_tile.get('error')}")
    elif latest_scene:
        scene_filter = "数据=有"
        if latest_scene.get("cloud_max") not in (None, ""):
            scene_filter += f"，云量≤{latest_scene.get('cloud_max')}%"
        if latest_scene.get("include_qc") is not None:
            scene_filter += "，包含 QC" if latest_scene.get("include_qc") else "，仅 NDVI 主产品"
        lines.extend([
            "",
            f"关联场景下载任务：{latest_scene.get('scene_job_id')}",
            f"- 产品：{latest_scene.get('product_key') or '--'}",
            f"- 场景状态：{latest_scene.get('state') or '--'}",
            f"- 场景进度说明：{latest_scene.get('message') or '--'}",
            f"- 数据筛选：{scene_filter}",
            f"- 状态文件：{latest_scene.get('status_path') or '--'}",
        ])
        if latest_scene.get("error"):
            lines.append(f"- 场景错误：{latest_scene.get('error')}")
    else:
        lines.extend(["", "未找到该商业任务关联的后台下载任务。"])

    if status in {"queued", "waiting_login", "waiting_manual"}:
        lines.append("")
        lines.append("下一步：如果任务一直停在等待状态，请先确认地理空间数据云登录态或平台账号 Cookie 是否可用。")
    elif status == "running":
        lines.append("")
        lines.append("任务仍在后台运行，可以稍后再次查询状态。")
    elif status == "completed":
        lines.append("")
        lines.append("任务已完成，可以在结果路径或压缩包位置查看输出。")
    elif status == "failed":
        lines.append("")
        lines.append("任务失败，请根据错误信息修复后重新提交或重新启动下载。")

    return {
        "reply": "\n".join(lines),
        "model": "direct-router",
        "reason": "commercial_download_status",
        "job": job,
        "tile_job": latest_tile,
        "scene_job": latest_scene,
    }


def _format_download_job_log_text(job: dict, scene_jobs: list[dict], tile_jobs: list[dict], audit_events: list[dict]) -> str:
    lines = [
        f"Download job log: {job.get('job_id')}",
        f"status: {job.get('status')}",
        f"stage: {job.get('stage')}",
        f"progress: {job.get('progress')}%",
        f"source_key: {job.get('source_key')}",
        f"resource_type: {job.get('resource_type')}",
        f"region: {job.get('region')}",
        f"output_path: {job.get('output_path') or ''}",
        f"zip_path: {job.get('zip_path') or ''}",
        f"error_message: {job.get('error_message') or ''}",
        "",
        "Scene jobs:",
    ]
    if scene_jobs:
        for item in scene_jobs:
            lines.append(f"- {item.get('scene_job_id') or ''} state={item.get('state') or ''} message={item.get('message') or ''}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Tile jobs:")
    if tile_jobs:
        for item in tile_jobs:
            lines.append(f"- {item.get('tile_job_id') or ''} state={item.get('state') or ''} message={item.get('message') or ''}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Recent audit events:")
    if audit_events:
        for item in audit_events:
            lines.append(f"- {item.get('created_at') or ''} {item.get('action') or ''} {item.get('status') or ''} {item.get('resource_id') or ''}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _download_requires_login_result(prompt: str) -> dict:
    return _api_download_requires_login_result(prompt)


@app.post("/api/chat/ask")
def ask(body: AskIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        service = workspace_for(user_id)
        def finalize(response: dict) -> dict:
            try:
                return _attach_result_panel(service, user_id, response)
            finally:
                finish_chat_task(body.task_id)
        if body.session_id:
            service.use_session_or_current(body.session_id)
        service.apply_frontend_context(body.frontend_context)
        if body.task_id:
            start_chat_task(body.task_id, user_id=user_id, session_id=service.current_session_id)
        if _is_commercial_download_status_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _format_commercial_download_status(body.prompt, user_id)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "tile_job")))
        intent_route = route_gscloud_download_intent(body.prompt)
        if intent_route.kind == "clarify":
            result = {
                "reply": intent_route.clarification,
                "model": "direct-router",
                "reason": "gscloud_intent_clarification",
                "intent_route": intent_route.__dict__,
                "action_required": {
                    "type": "clarification_required",
                    "missing_parameters": ["region"],
                    "recommended_defaults": {"resolution": "30m", "format": "GeoTIFF", "clip_to_region": True},
                    "options": [
                        {"value": "active_region", "label": "当前研究区"},
                        {"value": "upload_boundary", "label": "上传边界文件"},
                        {"value": "admin_region", "label": "输入行政区名称"},
                        {"value": "bbox", "label": "手动输入 bbox"},
                    ],
                },
            }
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "intent_route")))
        if intent_route.kind == "matched":
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_gscloud_intent_route_from_chat(user_id, body.prompt, intent_route)
            result["intent_route"] = intent_route.__dict__
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "scene_job", "tile_job", "intent_route")))
        if _is_gscloud_modl1d_download_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_direct_gscloud_modl1d_from_chat(user_id, body.prompt)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "scene_job")))
        if _is_gscloud_modnd1d_download_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_direct_gscloud_modnd1d_from_chat(user_id, body.prompt)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "scene_job")))
        if _is_gscloud_modev1f_download_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_direct_gscloud_modev1f_from_chat(user_id, body.prompt)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "scene_job")))
        if _is_gscloud_mod021km_download_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_direct_gscloud_mod021km_from_chat(user_id, body.prompt)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "scene_job")))
        if _is_gscloud_sentinel2_download_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_direct_gscloud_sentinel2_from_chat(user_id, body.prompt)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "scene_job")))
        if _is_gscloud_landsat_download_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_direct_gscloud_landsat8_from_chat(user_id, body.prompt)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job", "scene_job")))
        if _is_gscloud_dem_download_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _submit_direct_gscloud_dem_from_chat(user_id, body.prompt)
            return finalize(build_chat_response(service, user_prompt=body.prompt, result=result, meta_keys=("model", "reason", "job")))
        imported = _maybe_import_library_items_for_prompt(service, body.prompt)
        library_hint = local_library.summary_text(max_items=16)
        prompt = body.prompt
        if imported:
            prompt += "\n\n系统已根据你的指令从本地文件库预加载以下数据：\n" + "\n".join(f"- {m}" for m in imported)
        prompt += "\n\n【本地文件库上下文】\n" + library_hint + "\n如用户需要内置基础数据，请优先建议或调用本地文件库中已有条目；不要虚构不存在的数据。"
        return finalize(attach_chat_state(service, service.ask(prompt, visible_prompt=body.prompt, frontend_context=body.frontend_context, task_id=body.task_id)))

    return guard(run)


@app.post("/api/chat/cancel")
def cancel_chat(body: ChatCancelIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        result = cancel_chat_task(body.task_id, user_id=user_id, reason=body.reason)
        if result.get("status") == "forbidden":
            raise HTTPException(status_code=403, detail={"error_code": "CHAT_TASK_FORBIDDEN", "message": result.get("message")})
        return result

    return guard(run)


@app.post("/api/files/upload")
async def upload_files(request: Request, user_id: str = Form(default=""), files: list[UploadFile] = File(...)):
    async def read_all() -> list[tuple[str, bytes]]:
        if len(files) > MAX_UPLOAD_FILES:
            raise ValueError(f"单次最多上传 {MAX_UPLOAD_FILES} 个文件。")
        payload: list[tuple[str, bytes]] = []
        total_size = 0
        for file in files:
            data = await file.read()
            if not data:
                continue
            total_size += len(data)
            if total_size > MAX_UPLOAD_BYTES:
                raise ValueError(f"单次上传总大小不能超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB。")
            payload.append((file.filename or "uploaded.bin", data))
        return payload

    authorized_user_id = _require_request_user_if_present(request, user_id)
    payload = await read_all()
    if not payload:
        raise HTTPException(status_code=400, detail="没有读取到有效上传文件。")
    def run():
        service = workspace_for(authorized_user_id)
        messages = service.upload_bytes_batch(payload)
        result = {"ok": True, "count": len(payload), "messages": messages}
        dashboard_data = _decorate_dashboard(service, user_id=authorized_user_id)
        outcome = build_task_outcome("upload", result, dashboard=dashboard_data)
        return {
            **result,
            "dashboard": dashboard_data,
            "upload_summaries": _build_upload_summaries(service, payload, messages),
            "task_outcome": outcome,
            "outcome_markdown": format_task_outcome_markdown(outcome),
        }

    return guard(run)


@app.get("/api/local-library")
def list_local_library(
    query: str = Query(default=""),
    category: str = Query(default=""),
    data_type: str = Query(default=""),
    include_disabled: bool = Query(default=False),
    include_source_docs: bool = Query(default=False),
):
    return guard(lambda: local_library.list_items(query=query, category=category, data_type=data_type, include_disabled=include_disabled, include_source_docs=include_source_docs))


@app.post("/api/local-library/rescan")
def rescan_local_library(request: Request):
    def run():
        require_admin_token(os.getenv("GIS_AGENT_ADMIN_TOKEN", ""), _request_admin_token(request))
        return local_library.rescan()

    return guard(run)


@app.post("/api/local-library/import")
def import_local_library(body: LocalLibraryImportIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        if not body.item_ids:
            raise ValueError("请选择至少一个本地文件库条目。")
        service = workspace_for(user_id)
        messages: list[str] = []
        for item in local_library.resolve_paths(body.item_ids):
            messages.append(service.import_local_library_item(item))
        result = {"ok": True, "count": len(messages), "messages": messages}
        dashboard_data = _decorate_dashboard(service, user_id=user_id)
        outcome = build_task_outcome("upload", result, dashboard=dashboard_data)
        return {**result, "dashboard": dashboard_data, "task_outcome": outcome, "outcome_markdown": format_task_outcome_markdown(outcome)}

    return guard(run)


@app.get("/api/workspace/dashboard")
def dashboard(request: Request, user_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        data = _decorate_dashboard(workspace_for(authorized_user_id), user_id=authorized_user_id)
        data["local_library"] = local_library.list_items()
        return data

    return guard(run)


@app.get("/api/workspace/mentions")
def workspace_mentions(request: Request, user_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = workspace_for(authorized_user_id)
        return _build_workspace_mentions(service.manager.list_datasets())

    return guard(run)


@app.post("/api/workspace/export")
def export_workspace(body: ExportIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        service = workspace_for(user_id)
        result = service.export_results(mode=body.mode)
        result["download_url"] = _relative_artifact_url(service, result["zip_path"], user_id=user_id)
        _audit(request, user_id=user_id, action="workspace.export", resource_type="artifact", resource_id=str(result.get("zip_path") or ""), detail={"mode": body.mode, "file_count": result.get("file_count")})
        return result

    return guard(run)


@app.get("/api/artifacts/{artifact_id}")
def artifact_metadata(artifact_id: str, request: Request, user_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = workspace_for(authorized_user_id)
        payload = _public_artifact_or_error(service, artifact_id, user_id=authorized_user_id)
        _audit(request, user_id=authorized_user_id, action="artifact.metadata", resource_type="artifact", resource_id=artifact_id)
        return payload

    return guard(run)


@app.get("/api/artifacts/{artifact_id}/download")
def artifact_download(artifact_id: str, request: Request, user_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = workspace_for(authorized_user_id)
        artifact = service.manager.get_artifact(artifact_id)
        if not artifact:
            raise _artifact_error(404, "ARTIFACT_NOT_FOUND", "Artifact does not exist or is no longer registered.")
        public = _public_artifact_or_error(service, artifact_id, user_id=authorized_user_id)
        source = assert_artifact_path_allowed(service.manager.workdir, str(artifact.get("path") or ""))
        download_path = shapefile_zip_path(service.manager.workdir, source, artifact_id) if source.suffix.lower() == ".shp" else source
        if not download_path.exists() or not download_path.is_file():
            raise _artifact_error(404, "ARTIFACT_FILE_MISSING", "Artifact file is missing or expired.")
        _audit(request, user_id=authorized_user_id, action="artifact.download", resource_type="artifact", resource_id=artifact_id)
        return FileResponse(str(download_path), media_type=str(public.get("mime_type") or "application/octet-stream"), filename=str(public.get("filename") or download_path.name))

    return guard(run)


@app.delete("/api/artifacts/{artifact_id}")
def artifact_delete(artifact_id: str, request: Request, user_id: str = Query(default=""), delete_file: bool = Query(default=True)):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = workspace_for(authorized_user_id)
        artifact = service.manager.resolve_artifact(artifact_id)
        if not artifact:
            raise _artifact_error(404, "ARTIFACT_NOT_FOUND", "Artifact does not exist or is no longer registered.")
        try:
            assert_artifact_path_allowed(service.manager.workdir, str(artifact.get("path") or ""))
        except PermissionError as exc:
            raise _artifact_error(403, "ARTIFACT_FORBIDDEN", str(exc)) from exc
        result = service.manager.delete_artifact(artifact_id, delete_file=delete_file)
        _audit(request, user_id=authorized_user_id, action="artifact.delete", resource_type="artifact", resource_id=artifact_id, detail={"delete_file": delete_file, "file_deleted": result.get("file_deleted")})
        return result

    return guard(run)


@app.post("/api/artifacts/delete-batch")
def artifact_delete_batch(body: ArtifactBatchDeleteIn, request: Request):
    def run():
        authorized_user_id = _require_request_user_if_present(request, body.user_id)
        service = workspace_for(authorized_user_id)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_id in body.artifact_ids:
            artifact_id = str(raw_id or "").strip()
            if not artifact_id or artifact_id in seen:
                continue
            seen.add(artifact_id)
            artifact = service.manager.resolve_artifact(artifact_id)
            if not artifact:
                results.append({"ok": False, "artifact_id": artifact_id, "status": "not_found", "file_deleted": False})
                continue
            try:
                assert_artifact_path_allowed(service.manager.workdir, str(artifact.get("path") or ""))
                result = service.manager.delete_artifact(artifact_id, delete_file=body.delete_file)
            except PermissionError as exc:
                result = {"ok": False, "artifact_id": artifact_id, "status": "forbidden", "file_deleted": False, "error": str(exc)}
            results.append(result)
            _audit(
                request,
                user_id=authorized_user_id,
                action="artifact.delete",
                resource_type="artifact",
                resource_id=artifact_id,
                detail={"delete_file": body.delete_file, "batch": True, "ok": result.get("ok"), "file_deleted": result.get("file_deleted")},
            )
        return {
            "ok": all(bool(item.get("ok")) for item in results) if results else False,
            "deleted_count": sum(1 for item in results if item.get("ok")),
            "failed_count": sum(1 for item in results if not item.get("ok")),
            "results": results,
        }

    return guard(run)


@app.get("/api/files/artifact")
def artifact(request: Request, user_id: str = Query(default=""), path: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        _audit(request, user_id=authorized_user_id, action="artifact.legacy_download_blocked", status="blocked", resource_type="workspace_file")
        raise _artifact_error(
            410,
            "LEGACY_ARTIFACT_DOWNLOAD_DISABLED",
            "Legacy path downloads are disabled. Use an artifact_id download URL.",
        )

    return guard(run)


@app.post("/api/payments/simulate")
def simulate_payment(body: PaymentIn, request: Request):
    def run():
        user_id = _require_admin_or_mock_payment_user(request, body.user_id)
        preset = PLAN_PRESETS.get(body.plan, PLAN_PRESETS["pro"])
        amount = int(preset.get("price_cents", 2000)) if "price_cents" in preset else {"basic": 900, "pro": 2000, "team": 5900}.get(body.plan, 2000)
        result = commercial_service.simulate_payment(
            user_id=user_id,
            plan=body.plan,
            amount_cents=amount,
            platform_quota=int(preset.get("platform_monthly_quota", 30)),
            days=int(preset.get("days", 30)),
            note="Web 前端模拟支付",
        )
        _audit(request, user_id=user_id, action="payment.simulate", resource_type="payment", resource_id=str((result.get("payment") or {}).get("payment_id") or ""), detail={"plan": body.plan})
        return result

    return guard(run)


def _gscloud_public_status(user_id: str) -> dict:
    return GSCloudAccountService(commercial_service).status(user_id)


@app.post("/api/downloads/submit")
def submit_download(body: DownloadIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        payload = body.model_dump()
        payload["user_id"] = user_id
        job = commercial_service.submit_job(**payload)
        auto = _maybe_start_gscloud_auto_download(job, region=body.region)
        _audit(request, user_id=user_id, action="download.submit", resource_type="download_job", resource_id=job["job_id"], detail={"source_key": job.get("source_key"), "resource_type": job.get("resource_type"), "auto_started": auto.get("auto_started")})
        return {"job": commercial_service.get_job(job["job_id"]), **auto}

    return guard(run)


@app.post("/api/downloads/preflight")
def preflight_download(body: DownloadPreflightIn, request: Request):
    def run():
        _require_request_user(request, body.user_id)
        if str(body.source_key or "").lower() != "gscloud":
            raise ValueError("当前预检接口仅支持 GSCloud 场景表产品。")
        product_key = _gscloud_product_key_from_resource(body.product_key or body.resource_type)
        if product_key not in GSCLOUD_PRODUCTS:
            raise ValueError(f"不支持预检的 GSCloud 产品: {body.product_key or body.resource_type}")
        region = resolve_download_region(body.request_text, body.region)
        if not region.get("ok"):
            return {
                "state": "NEEDS_REGION",
                "ok": False,
                "product_key": product_key,
                "region_resolution": region,
                "message": region["message"],
            }
        state_path = _resolve_preflight_storage_state(body)
        login_health = inspect_storage_state(state_path)
        if not login_health.get("ok"):
            return {
                "state": "NEEDS_LOGIN",
                "ok": False,
                "product_key": product_key,
                "login_health": login_health,
                "message": "当前 GSCloud 登录态不可用，请先重新登录或更新平台账号 Cookie。",
            }
        result = verify_gscloud_scene_download(
            product_key=product_key,
            storage_state_path=state_path,
            download_dir=base_settings.workdir / "gscloud_download_verification",
            execute_download=False,
            max_pages=max(1, int(body.max_pages or 1)),
            timeout_seconds=600,
            headless=True,
            options={
                "region": region["region"],
                "start_date": body.start_date,
                "end_date": body.end_date,
                "cloud_max": body.cloud_max,
                "processing_level": body.processing_level,
            },
        )
        return {"ok": True, **result, "region_resolution": region}

    return guard(run)


@app.get("/api/downloads/login-health")
def download_login_health(request: Request, user_id: str = Query(...), source_key: str = Query(default="gscloud"), account_mode: str = Query(default="platform")):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        source = str(source_key or "gscloud").lower()
        mode = str(account_mode or "platform").lower()
        if mode == "own":
            state_path = commercial_service.get_user_storage_state_path(authorized_user_id, source)
        else:
            check = commercial_service._select_platform_account(source)
            if not check.ok or not check.account_id:
                raise PermissionError(check.reason or "没有可用平台账号。")
            account = commercial_service.get_platform_account_private(check.account_id)
            state_path = str(account.get("storage_state_path") or "")
        health = inspect_storage_state(state_path)
        _audit(request, user_id=authorized_user_id, action="download.login_health", resource_type="storage_state", detail={"source_key": source, "account_mode": mode, "ok": health.get("ok")})
        return {"source_key": source, "account_mode": mode, "login_health": health}

    return guard(run)


@app.get("/api/downloads/jobs")
def list_jobs(request: Request, user_id: str = ""):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        jobs = commercial_service.list_jobs(user_id=authorized_user_id)
        scene_by_job: dict[str, dict] = {}
        if list_gscloud_scene_jobs is not None:
            for item in list_gscloud_scene_jobs(commercial_service.workdir, limit=100):
                jid = str(item.get("job_id") or "")
                if jid and jid not in scene_by_job:
                    scene_by_job[jid] = item
        for job in jobs:
            if isinstance(job, dict):
                scene = scene_by_job.get(str(job.get("job_id") or ""))
                if scene:
                    job["scene_status"] = scene
                    for key in (
                        "pages_scanned",
                        "candidate_count",
                        "selected_count",
                        "downloaded_count",
                        "current_scene",
                        "scan_stop_reason",
                        "failure_diagnostic",
                        "login_health",
                        "region_resolution",
                        "artifact_quality",
                    ):
                        if scene.get(key) is not None:
                            job[key] = scene.get(key)
                for target in (job.get("zip_path"), job.get("output_path")):
                    url = _relative_shared_download_url(str(target or ""), user_id=authorized_user_id, job_id=str(job.get("job_id") or ""))
                    if url:
                        job["download_url"] = url
                        break
                if job.get("status") in {"completed", "success"}:
                    job["artifacts"] = _download_job_artifacts(authorized_user_id, job)
        return {"jobs": [_public_download_job(job) for job in jobs]}
    return guard(run)


@app.get("/api/downloads/jobs/log")
def download_job_log(request: Request, user_id: str = Query(...), job_id: str = Query(...)):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        job = require_resource_owner(commercial_service.get_job(job_id), user_id=authorized_user_id, resource_name="download job")
        tile_jobs = []
        scene_jobs = []
        if list_gscloud_tile_jobs is not None:
            tile_jobs = [item for item in list_gscloud_tile_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id]
        if list_gscloud_scene_jobs is not None:
            scene_jobs = [item for item in list_gscloud_scene_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id]
        return {
            "job": job,
            "scene_jobs": scene_jobs,
            "tile_jobs": tile_jobs,
            "audit_events": commercial_service.list_audit_events(user_id=authorized_user_id, limit=20),
        }

    return guard(run)


@app.get("/api/downloads/jobs/log-download")
def download_job_log_file(request: Request, user_id: str = Query(...), job_id: str = Query(...)):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        job = require_resource_owner(commercial_service.get_job(job_id), user_id=authorized_user_id, resource_name="download job")
        tile_jobs = []
        scene_jobs = []
        if list_gscloud_tile_jobs is not None:
            tile_jobs = [item for item in list_gscloud_tile_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id]
        if list_gscloud_scene_jobs is not None:
            scene_jobs = [item for item in list_gscloud_scene_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id]
        audit_events = commercial_service.list_audit_events(user_id=authorized_user_id, limit=20)
        text = _format_download_job_log_text(job, scene_jobs, tile_jobs, audit_events)
        _audit(request, user_id=authorized_user_id, action="download.log_download", resource_type="download_job", resource_id=job_id)
        return PlainTextResponse(
            text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{job_id}_log.txt"'},
        )

    return guard(run)


@app.post("/api/downloads/jobs/delete")
def delete_download_job(body: DownloadDeleteIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        result = commercial_service.delete_job(body.job_id, user_id=user_id)
        jobs = commercial_service.list_jobs(user_id=user_id)
        _audit(request, user_id=user_id, action="download.delete", resource_type="download_job", resource_id=body.job_id)
        return {**result, "jobs": jobs}

    return guard(run)


@app.post("/api/downloads/jobs/cancel")
def cancel_download_job(body: DownloadActionIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        result = commercial_service.cancel_job(body.job_id, user_id=user_id, reason=body.reason)
        jobs = commercial_service.list_jobs(user_id=user_id)
        _audit(request, user_id=user_id, action="download.cancel", resource_type="download_job", resource_id=body.job_id)
        return {**result, "jobs": jobs}

    return guard(run)


@app.post("/api/downloads/jobs/retry")
def retry_download_job(body: DownloadActionIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        retry = commercial_service.retry_job(body.job_id, user_id=user_id)
        auto = _maybe_start_gscloud_auto_download(retry, region=str(retry.get("region") or ""))
        jobs = commercial_service.list_jobs(user_id=user_id)
        _audit(request, user_id=user_id, action="download.retry", resource_type="download_job", resource_id=retry["job_id"], detail={"retried_from": body.job_id, "auto_started": auto.get("auto_started")})
        return {"job": commercial_service.get_job(retry["job_id"]), **auto, "jobs": jobs}

    return guard(run)


@app.get("/api/downloads/artifact")
def download_job_artifact(request: Request, user_id: str = Query(...), job_id: str = Query(...), path: str = Query(...)):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        job = require_resource_owner(commercial_service.get_job(job_id), user_id=authorized_user_id, resource_name="download job")
        target = resolve_child_path(base_settings.workdir, path)
        assert_artifact_path_allowed(base_settings.workdir, target)
        allowed = {str(job.get("zip_path") or ""), str(job.get("output_path") or "")}
        if str(target.resolve()) not in {str(Path(item).resolve()) for item in allowed if item}:
            _audit(request, user_id=authorized_user_id, action="download.artifact", status="denied", resource_type="download_job", resource_id=job_id, detail={"path": path})
            raise PermissionError("下载路径不属于该任务。")
        _audit(request, user_id=authorized_user_id, action="download.artifact", resource_type="download_job", resource_id=job_id, detail={"path": path})
        return FileResponse(str(target), filename=target.name)
    return guard(run)


SHANDIAN_WORKFLOW_PROMPT = """
请基于当前已上传数据，执行“闪电河流域表层土壤水分融合及模型适应性分析”的自动检查与建模准备流程。
要求：
1. 先检查当前工作区有哪些站点数据、遥感/再分析产品表、栅格、边界文件和论文文档。
2. 如果数据不足，明确列出缺少哪些文件，不要编造结果。
3. 若存在可用样本表，完成缺失值统计、时间字段识别、坐标字段识别、2019 建模期与 2020 独立验证期检查。
4. 优先按土壤水分论文流程组织：多源 1 km 产品、站点 0-5 cm 参考值、气象因子、NDVI/LAI、DEM/坡度/坡向。
5. 能运行时，优先执行 BTCH、RF、XGBoost、LSTM 对比，并输出 R、RMSE、ubRMSE、Bias、NSE。
6. 对模型输出继续执行 GCP 不确定性分析，输出 PICP、MPIW、NMPIW、QCP、IS。
7. 最后生成适合毕业论文使用的阶段性结论、风险点和下一步建议。
""".strip()


@app.post("/api/workflows/shandian-soil-moisture")
def shandian_soil_moisture_workflow(body: WorkflowIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        if body.run_now:
            return workspace_for(user_id).ask(SHANDIAN_WORKFLOW_PROMPT)
        return {"prompt": SHANDIAN_WORKFLOW_PROMPT}

    return guard(run)
