from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import time
from queue import Empty
from threading import Event, Thread
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode
from uuid import uuid4
from zipfile import ZipFile

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field

from api.routes.data_sources import create_data_sources_router
from api.routes.downloads import create_downloads_router
from core.config import Settings, load_settings
from core.service import GISWorkspaceService
from core.commercial.service import CommercialService, PLAN_PRESETS
from core.api_security import optional_authenticated_session, require_admin_token, require_authenticated_user, require_resource_owner
from core.api_helpers import (
    SESSION_COOKIE_ID,
    SESSION_COOKIE_TOKEN,
    build_result_panel as _api_build_result_panel,
    cors_origins as _cors_origins,
    download_requires_login_result as _api_download_requires_login_result,
    relative_shared_download_url,
    request_admin_token as _request_admin_token,
    request_session as _request_session,
    safe_key as _safe_key,
)
from core.archive_utils import safe_extract_zip
from core.artifacts import artifact_download_url, assert_artifact_path_allowed, content_disposition_attachment, public_artifact_payload, safe_download_filename, shapefile_zip_path
from core.chat_response import attach_chat_state, build_chat_response
from core.chat_tasks import cancel_chat_task, finish_chat_task, start_chat_task
from core.download_request_executor import _attach_registered_download_artifacts
from core.durable_jobs import DurableJobStore
from core.realtime_events import GLOBAL_REALTIME_EVENT_HUB, TaskEventStore
from core.response_quality import validate_response_before_send
from core.presentation_result import build_presentation_bundle
from core.management_views import download_job_to_management_view
from core.diagnostic_views import diagnostic_event_views
from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown
from core.tool_contracts import download_job_to_tool_result
from core.response_language import detect_response_language
from core.api_utils import api_guard, resolve_child_path
from core.local_library import LocalFileLibrary
from core.capability_config import CapabilityConfigStore, CAPABILITY_CONFIG_VERSION
from core.dataset_availability import DATASET_AVAILABILITY_SCHEMA_VERSION, DatasetAvailabilityStore
from core.dataset_availability_scanner import scan_dataset_availability
from core.system_reset import reset_system_workspace
from core.storage_cleanup import cleanup_storage_candidates, scan_storage_cleanup_candidates
from core.compat_usage import CompatibilityUsageStore
from core.trial_monitoring import TrialMonitoringStore
from core.map_layers import MapLayerService
from core.semantic_parser import parse_user_semantics
from core.station_data import find_station_archives, parse_ismn_station_zip
from core.domestic_sources.gscloud_download_verifier import verify_gscloud_scene_download
from core.domestic_sources.gscloud_products import GSCLOUD_PRODUCTS, LANDSAT8_OLI_TIRS, MOD021KM_1KM_SURFACE_REFLECTANCE, MODEV1F_CHINA_250M_EVI_5DAY, MODL1D_CHINA_1KM_LST_DAILY, MODND1D_CHINA_500M_NDVI_DAILY, SENTINEL2_MSI, match_gscloud_product
from core.domestic_sources.gscloud_reliability import inspect_storage_state, resolve_download_region
from core.domestic_sources.gscloud_adapter import gscloud_platform_state_path
from core.commercial.login_jobs import start_gscloud_login_process
from core.ops_config import require_valid_production_config, validate_production_config
from core.llm_config import check_llm_provider_health, validate_llm_config
from services.data_sources.gscloud_accounts import GSCloudAccountService
from services.downloads.resume import DownloadResumeService

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
    key = _safe_key(user_id)
    if key == "anonymous":
        return base_settings.workdir / "anonymous"
    return base_settings.workdir / "users" / key


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


def _require_current_request_user(request: Request) -> str:
    session_id, session_token = _request_session(request)
    payload = optional_authenticated_session(commercial_service, session_id=session_id, session_token=session_token)
    if not payload.get("authenticated"):
        raise PermissionError("请先登录账号。")
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise PermissionError("登录会话缺少用户标识，请重新登录。")
    return user_id


def _allow_anonymous_core_access() -> bool:
    return os.getenv("GIS_AGENT_ALLOW_ANONYMOUS", "0").strip().lower() in {"1", "true", "yes", "on"}


def _require_request_user_if_present(request: Request, user_id: str) -> str:
    if not str(user_id or "").strip():
        if _allow_anonymous_core_access():
            return ""
        return _require_current_request_user(request)
    return _require_request_user(request, user_id)


def _scoped_workspace_service(user_id: str, session_id: str = "") -> GISWorkspaceService:
    service = workspace_for(user_id)
    service.set_request_context(user_id, session_id)
    return service


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


class ChatConfirmIn(BaseModel):
    confirmation_id: str = Field(min_length=1, max_length=200)
    confirmation_prompt: str = Field(default="", max_length=4000)
    user_id: str = ""
    session_id: str = ""
    session_token: str = ""
    task_id: str = ""
    frontend_context: dict[str, Any] = Field(default_factory=dict)


class ChatSessionIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    title: str = ""
    interaction_mode: Literal["chat_only", "tool_enabled"] | None = None


class ChatRetryIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    message_id: int
    content: str = Field(min_length=1, max_length=12000)


class ChatModelIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    model: str = Field(min_length=1, max_length=120)


class ChatCancelIn(BaseModel):
    user_id: str = ""
    task_id: str = Field(min_length=1, max_length=120)
    reason: str = ""


class PaymentIn(BaseModel):
    user_id: str
    plan: Literal["pro", "team"] = "pro"


class DownloadIn(BaseModel):
    user_id: str
    session_id: str = ""
    source_key: str = "gscloud"
    resource_type: str = "dem"
    region: str = ""
    start_date: str = ""
    end_date: str = ""
    account_mode: Literal["own", "platform", "auto"] = "auto"
    request_text: str = ""
    output_name: str = ""
    include_raw: bool = False


class DownloadDeleteIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    job_id: str


class DownloadActionIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
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
    session_id: str = ""
    mode: Literal["latest", "all"] = "all"


class ArtifactDeleteIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    artifact_id: str = ""
    path: str = ""


class MapLayerRefreshIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    artifact_id: str = ""
    dataset_name: str = ""


class WorkflowIn(BaseModel):
    user_id: str = ""
    session_id: str = ""
    run_now: bool = True


class LocalLibraryImportIn(BaseModel):
    user_id: str = ""
    item_ids: list[str] = Field(default_factory=list)


class LocalLibraryRescanIn(BaseModel):
    pass


def guard(fn):
    return api_guard(fn)


def _capability_store() -> CapabilityConfigStore:
    return CapabilityConfigStore()


def _dataset_availability_store() -> DatasetAvailabilityStore:
    return DatasetAvailabilityStore()


def _compat_usage_store() -> CompatibilityUsageStore:
    return CompatibilityUsageStore(base_settings.workdir / "compat_usage.db")


def _trial_monitoring_store() -> TrialMonitoringStore:
    return TrialMonitoringStore(base_settings.workdir / "trial_monitoring.db")


def _compat_actor_type(request: Request) -> str:
    explicit = str(request.headers.get("x-actor-type") or "").strip().lower()
    if explicit:
        return explicit
    user_agent = str(request.headers.get("user-agent") or "").lower()
    if "testclient" in user_agent or "playwright" in user_agent:
        return "automated_test"
    return "trial_user"


def _require_capability_admin(request: Request) -> None:
    require_admin_token(os.getenv("GIS_AGENT_ADMIN_TOKEN", ""), _request_admin_token(request))


async def _extract_capability_document_text(upload: UploadFile) -> tuple[str, str]:
    filename = upload.filename or "knowledge.txt"
    suffix = Path(filename).suffix.lower()
    data = await upload.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Knowledge document is too large.")
    if suffix in {".md", ".txt"}:
        try:
            return data.decode("utf-8-sig"), filename
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Knowledge document must be UTF-8 encoded.") from exc
    if suffix in {".pdf", ".docx"}:
        try:
            from markitdown import MarkItDown  # type: ignore
        except Exception as exc:
            raise HTTPException(status_code=400, detail="PDF/DOCX extraction requires markitdown to be installed.") from exc
        with tempfile.TemporaryDirectory(prefix="capability_doc_") as tmp:
            path = Path(tmp) / (re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._") or f"knowledge{suffix}")
            path.write_bytes(data)
            result = MarkItDown().convert(str(path))
            text = str(getattr(result, "text_content", "") or "")
            if not text.strip():
                raise HTTPException(status_code=400, detail="No text could be extracted from the knowledge document.")
            return text, filename
    raise HTTPException(status_code=400, detail="Unsupported knowledge document type. Use md, txt, pdf, or docx.")


def _gscloud_account_service() -> GSCloudAccountService:
    return GSCloudAccountService(commercial_service)


def _download_resume_service() -> DownloadResumeService:
    return DownloadResumeService(
        commercial_service,
        _gscloud_account_service(),
        _maybe_start_gscloud_auto_download,
    )


app.include_router(
    create_data_sources_router(
        account_service=_gscloud_account_service,
        authenticated_user=_require_current_request_user,
        audit=_audit,
        guard=guard,
    )
)
app.include_router(
    create_downloads_router(
        resume_service=_download_resume_service,
        authenticated_user=_require_current_request_user,
        audit=_audit,
        guard=guard,
    )
)




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


def _ensure_downloadable_artifact(service: GISWorkspaceService, item: dict, *, user_id: str, session_id: str) -> dict:
    artifact_id = str(item.get("artifact_id") or "").strip()
    if artifact_id and service.manager.database.get_artifact(artifact_id):
        return item
    path = str(item.get("path") or "").strip()
    if not path:
        return item
    registered = service.manager.register_artifact(
        artifact_id=artifact_id,
        path=path,
        type=str(item.get("type") or item.get("category") or item.get("kind") or "artifact"),
        title=str(item.get("title") or item.get("name") or Path(path).name),
        description=str(item.get("description") or ""),
        preview_available=bool(item.get("preview_available")),
        source_tool=str(item.get("source_tool") or "workspace_scan"),
        meta=item.get("meta") if isinstance(item.get("meta"), dict) else {},
    )
    item.update(registered)
    return item


def _decorate_dashboard(service: GISWorkspaceService, user_id: str = "") -> dict:
    data = service.dashboard()
    session_id = str(getattr(service, "current_session_id", "") or "")
    for item in data.get("artifacts", []):
        if not isinstance(item, dict) or not item.get("path"):
            continue
        item = _ensure_downloadable_artifact(service, item, user_id=user_id, session_id=session_id)
        artifact_id = str(item.get("artifact_id") or "")
        if artifact_id:
            item["download_url"] = artifact_download_url(artifact_id, user_id=user_id, session_id=session_id)
    for result in data.get("model_results", []):
        if not isinstance(result, dict):
            continue
        for artifact in result.get("artifacts", []):
            if not isinstance(artifact, dict) or not artifact.get("path"):
                continue
            artifact = _ensure_downloadable_artifact(service, artifact, user_id=user_id, session_id=session_id)
            artifact_id = str(artifact.get("artifact_id") or "")
            if artifact_id:
                artifact["download_url"] = artifact_download_url(artifact_id, user_id=user_id, session_id=session_id)
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


def _build_workspace_mentions(datasets: list[dict[str, Any]]) -> dict:
    items: list[dict[str, Any]] = []
    for item in datasets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("dataset_name") or item.get("label") or "").strip()
        if not name:
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        columns = meta.get("columns") if isinstance(meta.get("columns"), list) else []
        path = str(item.get("path") or item.get("display_path") or "")
        filename = str(item.get("filename") or Path(path).name or name)
        row_count = item.get("row_count", meta.get("rows", meta.get("row_count")))
        column_count = item.get("column_count", len(columns) if columns else meta.get("column_count"))
        items.append(
            {
                "id": str(item.get("id") or name),
                "name": name,
                "label": name,
                "mention": f"@{{{name}}}",
                "type": str(item.get("type") or item.get("data_type") or "file"),
                "filename": filename,
                "path": path,
                "row_count": row_count if isinstance(row_count, int) else None,
                "column_count": column_count if isinstance(column_count, int) else None,
                "crs": str(item.get("crs") or meta.get("crs") or ""),
                "description": str(item.get("description") or ""),
                "meta": meta,
            }
        )
    return {"items": items, "count": len(items)}


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


def _decorate_response_artifacts(service: GISWorkspaceService, user_id: str, response: dict) -> dict:
    session_id = str(getattr(service, "current_session_id", "") or "")

    def decorate_item(item: dict) -> dict:
        artifact = dict(item)
        artifact_id = str(artifact.get("artifact_id") or "")
        raw_path = str(artifact.get("path") or artifact.get("absolute_path") or artifact.get("relative_path") or "")
        filename = str(artifact.get("filename") or artifact.get("name") or artifact.get("title") or "")
        if raw_path:
            filename = filename or Path(raw_path).name
            if artifact_id and not service.manager.database.get_artifact(artifact_id):
                source_info = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
                registered = service.manager.register_artifact(
                    artifact_id=artifact_id,
                    path=raw_path,
                    type=str(artifact.get("type") or artifact.get("kind") or "artifact"),
                    title=str(artifact.get("title") or artifact.get("name") or artifact.get("filename") or filename),
                    description=str(artifact.get("description") or ""),
                    preview_available=bool(artifact.get("preview_available")),
                    source_tool=str(artifact.get("source_tool") or source_info.get("tool_name") or ""),
                    meta=artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {},
                )
                artifact.update(registered)
                artifact_id = str(artifact.get("artifact_id") or artifact_id)
        if filename:
            artifact["filename"] = safe_download_filename(filename)
            artifact["name"] = artifact.get("name") or artifact["filename"]
        if artifact_id and not artifact.get("download_url"):
            artifact["download_url"] = artifact_download_url(artifact_id, user_id=user_id, session_id=session_id)
        for private_key in ("path", "absolute_path", "relative_path", "display_path", "owner_user_id", "session_id"):
            artifact.pop(private_key, None)
        if isinstance(artifact.get("meta"), dict):
            meta = dict(artifact["meta"])
            meta.pop("owner_user_id", None)
            meta.pop("session_id", None)
            artifact["meta"] = meta
        return artifact

    def decorate_user_facing_result(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        patched = dict(value)
        for key in ("primary_artifacts", "secondary_artifacts", "preview_artifacts"):
            if isinstance(patched.get(key), list):
                patched[key] = [decorate_item(item) if isinstance(item, dict) else item for item in patched[key]]
        groups = []
        for group in patched.get("grouped_artifacts", []) if isinstance(patched.get("grouped_artifacts"), list) else []:
            if not isinstance(group, dict):
                groups.append(group)
                continue
            group_patch = dict(group)
            if isinstance(group_patch.get("artifacts"), list):
                group_patch["artifacts"] = [decorate_item(item) if isinstance(item, dict) else item for item in group_patch["artifacts"]]
            groups.append(group_patch)
        if groups:
            patched["grouped_artifacts"] = groups
        bundle = patched.get("download_bundle")
        if isinstance(bundle, dict):
            bundle_patch = {}
            for key, item in bundle.items():
                bundle_patch[key] = decorate_item(item) if isinstance(item, dict) else item
            patched["download_bundle"] = bundle_patch
        return patched

    updated = dict(response)
    for key in ("artifacts", "files"):
        if isinstance(updated.get(key), list):
            updated[key] = [decorate_item(item) if isinstance(item, dict) else item for item in updated[key]]
    if isinstance(updated.get("user_facing_result"), dict):
        updated["user_facing_result"] = decorate_user_facing_result(updated["user_facing_result"])
    messages = []
    for message in updated.get("messages", []) if isinstance(updated.get("messages"), list) else []:
        if not isinstance(message, dict):
            messages.append(message)
            continue
        patched = dict(message)
        meta = dict(patched.get("meta") or {}) if isinstance(patched.get("meta"), dict) else {}
        for key in ("artifacts", "files"):
            if isinstance(meta.get(key), list):
                meta[key] = [decorate_item(item) if isinstance(item, dict) else item for item in meta[key]]
        if isinstance(meta.get("user_facing_result"), dict):
            meta["user_facing_result"] = decorate_user_facing_result(meta["user_facing_result"])
        if meta:
            patched["meta"] = meta
        messages.append(patched)
    if messages:
        updated["messages"] = messages
    return validate_response_before_send(updated, user_id=user_id, session_id=session_id)


def _attach_result_panel(service: GISWorkspaceService, user_id: str, response: dict) -> dict:
    dashboard = _decorate_dashboard(service, user_id=user_id)
    response = _decorate_response_artifacts(service, user_id, response)
    return {**response, "result_panel": _build_result_panel(response, dashboard)}


def _relative_shared_download_url(file_path: str, user_id: str = "", job_id: str = "", session_id: str = "") -> str:
    return relative_shared_download_url(base_settings.workdir, file_path, user_id=user_id, job_id=job_id, session_id=session_id)


def _assert_download_job_session(job: dict, session_id: str = "") -> None:
    requested = str(session_id or "").strip()
    if not requested:
        return
    actual = str(job.get("session_id") or "").strip()
    if not actual:
        # Legacy jobs created before chat/download requests carried session_id.
        # Ownership is still enforced before this check, so keep them diagnosable.
        return
    if actual != requested:
        raise PermissionError("download job belongs to another session")


def _manager_for_download_job(user_id: str, job: dict) -> Any | None:
    session_id = str((job or {}).get("session_id") or "").strip()
    if not user_id or not session_id:
        return None
    try:
        return _scoped_workspace_service(user_id, session_id).manager
    except Exception:
        return None


def _download_tool_result_for_job(job: dict, *, user_id: str = "") -> dict:
    job_id = str((job or {}).get("job_id") or "")
    scene_job = None
    tile_job = None
    if job_id and list_gscloud_scene_jobs is not None:
        scene_job = next((item for item in list_gscloud_scene_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id), None)
    if job_id and list_gscloud_tile_jobs is not None:
        tile_job = next((item for item in list_gscloud_tile_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id), None)
    tool_result = download_job_to_tool_result(job, scene_job=scene_job, tile_job=tile_job)
    manager = _manager_for_download_job(user_id, job)
    if manager is not None:
        product = {
            "product_id": str(job.get("output_name") or job.get("resource_type") or "download"),
            "resource_type": str(job.get("resource_type") or "download"),
        }
        tool_result = _attach_registered_download_artifacts(manager, tool_result, job, product)
    return tool_result


def _attach_download_tool_result(payload: dict, job_key: str = "job") -> dict:
    patched = dict(payload or {})
    job = patched.get(job_key)
    if isinstance(job, dict):
        tool_result = _download_tool_result_for_job(job, user_id=str(job.get("user_id") or ""))
        step_result = {**tool_result, "step_id": "download_job"}
        bundle = build_presentation_bundle(
            task_goal="download_status",
            task_plan_summary={
                "primary_goal": "download_status",
                "intent": "download",
                "operation": "status",
                "response_language": detect_response_language(job.get("request_text") or job.get("region") or ""),
            },
            coordinator_status=str(tool_result.get("status") or ""),
            normalized_results=[step_result],
            response_language=detect_response_language(job.get("request_text") or job.get("region") or ""),
        )
        patched["tool_result"] = tool_result
        patched["download_tool_result"] = tool_result
        patched["normalized_results"] = bundle["normalized_results"]
        patched["presentation_result"] = bundle["presentation_result"]
        patched["execution_summary"] = bundle["execution_summary"]
        patched["presentation_reply"] = bundle["reply"]
        patched["result_rendering_path"] = "presentation_result"
        patched["presentation_source"] = bundle.get("presentation_source")
        patched["management_view"] = download_job_to_management_view(job, tool_result=tool_result)
        patched["deprecated_raw_job_api"] = True
    jobs = patched.get("jobs")
    if isinstance(jobs, list):
        patched["management_views"] = [
            download_job_to_management_view(item, tool_result=_download_tool_result_for_job(item, user_id=str(item.get("user_id") or "")))
            for item in jobs
            if isinstance(item, dict)
        ]
    if any(isinstance(patched.get(key), list) for key in ("scene_jobs", "tile_jobs", "audit_events")):
        patched["diagnostic_event_views"] = {
            "scene_jobs": diagnostic_event_views(patched.get("scene_jobs") if isinstance(patched.get("scene_jobs"), list) else [], default_phase="scene"),
            "tile_jobs": diagnostic_event_views(patched.get("tile_jobs") if isinstance(patched.get("tile_jobs"), list) else [], default_phase="tile"),
            "audit_events": diagnostic_event_views(patched.get("audit_events") if isinstance(patched.get("audit_events"), list) else [], default_phase="audit"),
        }
    return patched


def _gscloud_product_key_from_resource(value: str) -> str:
    text = str(value or "").strip().lower()
    for product in GSCLOUD_PRODUCTS.values():
        if text in {product.key.lower(), product.resource_type.lower()}:
            return product.key
    return text


def _resolve_preflight_storage_state(body: DownloadPreflightIn) -> str:
    source_key = str(body.source_key or "gscloud").lower()
    mode = commercial_service.resolve_account_mode(body.user_id, body.account_mode, source_key)
    if mode in {"own", "user", "user_account", "manual_cookie"}:
        return commercial_service.get_user_storage_state_path(body.user_id, source_key)
    check = commercial_service._select_platform_account(source_key)
    if not check.ok or not check.account_id:
        raise PermissionError(check.reason or "没有可用平台账号。")
    account = commercial_service.get_platform_account_private(check.account_id)
    return str(account.get("storage_state_path") or "")


def _resolve_gscloud_prompt_account_mode(user_id: str, prompt: str) -> str:
    text = str(prompt or "")
    own_markers = (
        "\u81ea\u5df1\u7684\u8d26\u53f7",
        "\u81ea\u6709\u8d26\u53f7",
        "\u4e2a\u4eba\u8d26\u53f7",
    )
    platform_markers = (
        "\u5e73\u53f0\u8d26\u53f7",
        "\u8d26\u53f7\u6c60",
    )
    if any(marker in text for marker in own_markers):
        return "own"
    if any(marker in text for marker in platform_markers):
        return "platform"
    return commercial_service.default_account_mode(user_id, "gscloud")


def _dataset_map_kind(name: str, data_type: str) -> str:
    text = f"{name} {data_type}".lower()
    if any(token in text for token in ["soil", "moisture", "sm", "ndvi", "prediction", "result"]):
        return "soil"
    if any(token in text for token in ["dem", "elevation", "srtm", "aster", "terrain"]):
        return "dem"
    if any(token in text for token in ["boundary", "region", "aoi", "basin", "admin"]):
        return "boundary"
    return "boundary" if data_type == "vector" else "dem"


def _raster_preview_path(service: GISWorkspaceService, dataset_name: str) -> Path:
    safe_name = _safe_layer_id(dataset_name)
    return service.manager.temp_dir / "map_previews" / f"{safe_name}.png"


def _ensure_raster_preview(service: GISWorkspaceService, dataset_name: str, user_id: str = "") -> dict:
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.warp import transform_bounds

    raster_path = service.manager.get_raster_path(dataset_name)
    preview_path = _raster_preview_path(service, dataset_name)
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    if not preview_path.exists() or preview_path.stat().st_mtime < raster_path.stat().st_mtime:
        with rasterio.open(raster_path) as src:
            max_size = 1200
            scale = max(src.width / max_size, src.height / max_size, 1)
            out_width = max(1, int(src.width / scale))
            out_height = max(1, int(src.height / scale))
            data = src.read(1, out_shape=(out_height, out_width), masked=True)
            arr = np.asarray(data.filled(np.nan), dtype="float32")
            valid = np.isfinite(arr)
            rgba = np.zeros((out_height, out_width, 4), dtype=np.uint8)
            if valid.any():
                lo, hi = np.nanpercentile(arr[valid], [2, 98])
                if hi <= lo:
                    hi = lo + 1
                norm = np.clip((arr - lo) / (hi - lo), 0, 1)
                rgba[..., 0] = (32 + 210 * norm).astype(np.uint8)
                rgba[..., 1] = (96 + 120 * norm).astype(np.uint8)
                rgba[..., 2] = (180 - 140 * norm).astype(np.uint8)
                rgba[..., 3] = np.where(valid, 190, 0).astype(np.uint8)
            Image.fromarray(rgba, mode="RGBA").save(preview_path)

    with rasterio.open(raster_path) as src:
        bounds = tuple(src.bounds)
        if src.crs:
            bounds = transform_bounds(src.crs, "EPSG:4326", *bounds, densify_pts=21)
    params = {"dataset_name": dataset_name}
    if str(user_id or "").strip():
        params["user_id"] = _safe_key(user_id)
    return {
        "preview_path": str(preview_path),
        "preview_url": f"/api/map/raster-preview?{urlencode(params)}",
        "bounds": [float(v) for v in bounds],
    }


def _read_vector_for_map(path: Path):
    import geopandas as gpd

    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            shp_names = [name for name in archive.namelist() if name.lower().endswith(".shp")]
            if not shp_names:
                raise FileNotFoundError(f"zip archive has no shapefile: {path}")
            shp_name = sorted(shp_names, key=lambda item: ("/" in item, item))[0]
            with tempfile.TemporaryDirectory(prefix="gis-agent-map-vector-") as temp_dir:
                safe_extract_zip(archive, Path(temp_dir))
                return gpd.read_file(Path(temp_dir) / shp_name)
    return gpd.read_file(path)


def _vector_map_layer(name: str, gdf, *, layer_id: str = "", kind: str = "", meta: dict | None = None) -> dict | None:
    if gdf.empty:
        return None
    if gdf.crs:
        gdf = gdf.to_crs("EPSG:4326")
    if len(gdf) > 2000:
        gdf = gdf.head(2000)
    return {
        "id": layer_id or _safe_layer_id(name),
        "name": name,
        "type": "vector",
        "kind": kind or _dataset_map_kind(name, "vector"),
        "bounds": [float(v) for v in gdf.total_bounds.tolist()],
        "feature_count": int(len(gdf)),
        "geojson": json.loads(gdf.to_json()),
        "meta": meta or {},
    }


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
    layers: list[dict] = []
    has_boundary = False
    for item in service.manager.list_datasets():
        name = str(item.get("name") or "")
        data_type = str(item.get("type") or "")
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        if data_type == "vector":
            gdf = service.manager.get_vector(name)
            layer = _vector_map_layer(name, gdf, kind=_dataset_map_kind(name, data_type), meta=meta)
            if not layer:
                continue
            layers.append(layer)
            has_boundary = has_boundary or layer.get("kind") == "boundary"
        elif data_type == "raster":
            preview = _ensure_raster_preview(service, name, user_id=user_id)
            layers.append({
                "id": _safe_layer_id(name),
                "name": name,
                "type": "raster",
                "kind": _dataset_map_kind(name, data_type),
                "bounds": preview["bounds"],
                "preview_url": preview["preview_url"],
                "meta": meta,
            })
    if not has_boundary:
        fallback = _local_library_boundary_layer()
        if fallback:
            layers.insert(0, fallback)
    layers = _dedupe_boundary_layers(layers)
    return {"layers": layers}


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
            "role_models": llm_validation.get("role_models", {}),
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
def map_layers(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
    def run():
        if not str(user_id or "").strip() and not str(session_id or "").strip():
            return {"layers": []}
        authorized_user_id = _require_request_user_if_present(request, user_id)
        return MapLayerService(_scoped_workspace_service(authorized_user_id, session_id)).workspace_layers(
            user_id=authorized_user_id,
            session_id=session_id,
        )

    return guard(run)


@app.post("/api/map/layers/refresh")
def refresh_map_layer(body: MapLayerRefreshIn, request: Request):
    def run():
        authorized_user_id = _require_request_user_if_present(request, body.user_id)
        service = _scoped_workspace_service(authorized_user_id, body.session_id)
        layer_service = MapLayerService(service)
        if body.artifact_id:
            service.manager.assert_artifact_access(authorized_user_id, body.session_id or service.current_session_id, body.artifact_id)
            return layer_service.refresh_artifact(body.artifact_id, user_id=authorized_user_id, session_id=body.session_id)
        if body.dataset_name:
            dataset = next((item for item in service.manager.list_datasets() if item.get("name") == body.dataset_name), None)
            if not dataset:
                raise FileNotFoundError(f"dataset not found: {body.dataset_name}")
            layer = layer_service.dataset_layer(dataset, user_id=authorized_user_id, session_id=body.session_id)
            if not layer:
                raise ValueError(f"dataset produced no map layer: {body.dataset_name}")
            return {"dataset_name": body.dataset_name, "map_layer_id": layer["id"], "map_ready": True, "layer": layer}
        raise ValueError("artifact_id or dataset_name is required")

    return guard(run)


@app.get("/api/map/raster-preview")
def map_raster_preview(request: Request, user_id: str = Query(default=""), session_id: str = Query(default=""), dataset_name: str = Query(...)):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = _scoped_workspace_service(authorized_user_id, session_id)
        layer_service = MapLayerService(service)
        target = layer_service.raster_preview_path(dataset_name)
        if not target.exists():
            layer_service.ensure_raster_preview(dataset_name, user_id=authorized_user_id)
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
        service = _scoped_workspace_service(authorized_user_id)
        return _decorate_response_artifacts(service, authorized_user_id, {"messages": service.current_messages()})

    return guard(run)


def _task_event_store_for_service(service: GISWorkspaceService) -> TaskEventStore:
    return TaskEventStore(Path(service.manager.workdir) / "durable_jobs.db")


def _event_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bridge_commercial_download_events(service: GISWorkspaceService, *, user_id: str, session_id: str) -> None:
    event_store = _task_event_store_for_service(service)
    try:
        jobs = commercial_service.list_jobs(user_id=user_id, session_id=session_id, limit=100)
    except Exception:
        return
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("job_id") or "").strip()
        if not job_id:
            continue
        try:
            tool_result = download_job_to_tool_result(job)
            view = download_job_to_management_view(job, tool_result=tool_result)
        except Exception:
            continue
        raw_status = str(view.get("status") or "running")
        status = "cancelled" if raw_status == "canceled" else raw_status
        if status not in {"queued", "running", "awaiting_confirmation", "waiting_login", "paused", "succeeded", "failed", "cancelled"}:
            status = "running"
        kind = "task_progress" if status == "running" else "task_status"
        if status == "succeeded":
            kind = "task_result"
        elif status == "failed":
            kind = "error"
        elif status == "cancelled":
            kind = "warning"
        artifact_refs = view.get("artifact_refs") if isinstance(view.get("artifact_refs"), list) else []
        layer_refs = view.get("map_layer_refs") if isinstance(view.get("map_layer_refs"), list) else []
        message = str(view.get("user_message") or view.get("display_title") or "下载任务状态已更新。")
        presentation = {
            "schema_version": "presentation-result/v1",
            "status": status,
            "concise_summary": message,
            "artifact_refs": artifact_refs,
            "map_layer_refs": layer_refs,
            "warnings": view.get("warnings") if isinstance(view.get("warnings"), list) else [],
            "error_summary": str(view.get("error_title") or "") if status in {"failed", "cancelled"} else "",
            "next_action_suggestions": view.get("available_actions") if isinstance(view.get("available_actions"), list) else [],
        }
        task_update = {
            "interaction_type": "tool_task",
            "management_view": view,
            "task_card": {
                "task_id": job_id,
                "status": status,
                "progress": view.get("progress"),
                "current_step": _event_dict(view.get("action_state")).get("stage") or "",
                "summary": message,
            },
        }
        fingerprint = json.dumps(
            {
                "status": status,
                "progress": view.get("progress"),
                "updated_at": view.get("updated_at"),
                "artifacts": artifact_refs,
                "error_code": view.get("error_code"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        event_store.append_if_changed(
            checkpoint_key=f"commercial-download:{job_id}",
            fingerprint=fingerprint,
            user_id=user_id,
            session_id=session_id,
            task_id=job_id,
            job_id=job_id,
            kind=kind,
            status=status,
            progress=int(float(view.get("progress") or 0)),
            current_step=str(_event_dict(view.get("action_state")).get("stage") or ""),
            message=message,
            management_view=view,
            presentation_result=presentation,
            task_update=task_update,
        )


def _public_task_events(service: GISWorkspaceService, *, user_id: str, session_id: str, after_version: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    _bridge_commercial_download_events(service, user_id=user_id, session_id=session_id)
    return _task_event_store_for_service(service).public_events(
        user_id=user_id,
        session_id=session_id,
        after_version=after_version,
        limit=limit,
    )


def _sse_event(event: dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {int(event.get('version') or 0)}\nevent: {str(event.get('kind') or 'message')}\ndata: {payload}\n\n"


def _stream_task_update(response: dict[str, Any]) -> dict[str, Any]:
    messages = response.get("messages") if isinstance(response.get("messages"), list) else []
    assistant = next((item for item in reversed(messages) if isinstance(item, dict) and item.get("role") == "assistant"), {})
    meta = assistant.get("meta") if isinstance(assistant.get("meta"), dict) else {}
    allowed = {
        "action_required",
        "interaction_type",
        "mode",
        "status",
        "management_view",
        "download_management_view",
        "task_card",
        "execution_summary",
        "presentation_result",
        "confirmed_pending_confirmation_id",
        "reason",
    }
    return {key: meta[key] for key in allowed if key in meta}


@app.get("/api/chat/events/replay")
def replay_chat_events(
    request: Request,
    user_id: str = Query(default=""),
    session_id: str = Query(default=""),
    after_version: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = _scoped_workspace_service(authorized_user_id, session_id)
        return {
            "schema_version": "task-progress-event-replay/v1",
            "events": _public_task_events(
                service,
                user_id=authorized_user_id,
                session_id=session_id or service.current_session_id,
                after_version=after_version,
                limit=limit,
            ),
        }

    return guard(run)


@app.get("/api/chat/events")
def stream_chat_events(
    request: Request,
    user_id: str = Query(default=""),
    session_id: str = Query(default=""),
    after_version: int = Query(default=0, ge=0),
    once: bool = Query(default=False),
):
    authorized_user_id = _require_request_user_if_present(request, user_id)
    service = _scoped_workspace_service(authorized_user_id, session_id)
    scoped_session_id = session_id or service.current_session_id

    def event_stream():
        version = max(0, int(after_version or 0))
        subscription = GLOBAL_REALTIME_EVENT_HUB.subscribe(user_id=authorized_user_id, session_id=scoped_session_id)
        try:
            while True:
                events = _public_task_events(service, user_id=authorized_user_id, session_id=scoped_session_id, after_version=version)
                for event in events:
                    version = max(version, int(event.get("version") or 0))
                    yield _sse_event(event)
                transient_events: list[dict[str, Any]] = []
                try:
                    transient_events.append(subscription.get(timeout=0.8 if not events else 0.01))
                    while True:
                        transient_events.append(subscription.get_nowait())
                except Empty:
                    pass
                for event in transient_events:
                    yield _sse_event(event)
                if once:
                    return
                if not events and not transient_events:
                    yield ": keepalive\n\n"
        finally:
            GLOBAL_REALTIME_EVENT_HUB.unsubscribe(subscription)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/chat/sessions")
def chat_sessions(request: Request, user_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = _scoped_workspace_service(authorized_user_id)
        if not service.current_session_id:
            service.set_request_context(authorized_user_id, create_if_missing=True)
        return _decorate_response_artifacts(service, authorized_user_id, {
            "sessions": service.list_sessions(),
            "current_session_id": service.current_session_id,
            "messages": service.current_messages(),
        })

    return guard(run)


@app.post("/api/chat/sessions")
def create_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, body.user_id))
        session_id = service.create_new_session(body.title or None)
        return {
            "session_id": session_id,
            "sessions": service.list_sessions(),
            "current_session_id": service.current_session_id,
            "messages": service.current_messages(),
        }

    return guard(run)


@app.post("/api/chat/sessions/switch")
def switch_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, body.user_id), body.session_id)
        service.switch_session(body.session_id)
        return {
            "sessions": service.list_sessions(),
            "current_session_id": service.current_session_id,
            "messages": service.current_messages(),
        }

    return guard(run)


@app.post("/api/chat/sessions/rename")
def rename_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, body.user_id), body.session_id)
        service.rename_session(body.session_id, body.title)
        return {"sessions": service.list_sessions(), "current_session_id": service.current_session_id}

    return guard(run)


@app.post("/api/chat/sessions/delete")
def delete_chat_session(body: ChatSessionIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        _compat_usage_store().record_effective_request(source="POST /api/chat/ask", actor_type=_compat_actor_type(request))
        service = _scoped_workspace_service(user_id, body.session_id)
        cancelled_download_jobs = commercial_service.cancel_session_jobs(user_id, body.session_id, reason="Session deleted.")
        current = service.delete_session(body.session_id)
        hard_deleted_downloads = commercial_service.hard_delete_session_jobs(user_id, body.session_id)
        return {
            "current_session_id": current,
            "sessions": service.list_sessions(),
            "messages": service.current_messages(),
            "cancelled_download_jobs": cancelled_download_jobs,
            "hard_deleted_downloads": hard_deleted_downloads,
        }

    return guard(run)


@app.post("/api/chat/sessions/mode")
def set_chat_interaction_mode(body: ChatSessionIn, request: Request):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, body.user_id), body.session_id)
        mode = service.set_interaction_mode(body.interaction_mode or "chat_only", body.session_id or service.current_session_id)
        return {
            "interaction_mode": mode,
            "sessions": service.list_sessions(),
            "current_session_id": service.current_session_id,
            "messages": service.current_messages(),
        }

    return guard(run)


@app.post("/api/chat/sessions/clear")
def clear_chat_session(body: ChatSessionIn, request: Request):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, body.user_id), body.session_id)
        service.clear_current_chat()
        return {
            "current_session_id": service.current_session_id,
            "sessions": service.list_sessions(),
            "messages": service.current_messages(),
        }

    return guard(run)


@app.post("/api/chat/retry")
def retry_chat_message(body: ChatRetryIn, request: Request):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, body.user_id), body.session_id)
        result = service.edit_user_message_and_retry(body.message_id, body.content)
        return {**result, "messages": service.current_messages(), "sessions": service.list_sessions(), "current_session_id": service.current_session_id}

    return guard(run)


@app.get("/api/chat/models")
def chat_models(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, user_id), session_id)
        return service.chat_model_state(session_id or service.current_session_id)

    return guard(run)


@app.post("/api/chat/models/select")
def select_chat_model(body: ChatModelIn, request: Request):
    def run():
        service = _scoped_workspace_service(_require_request_user_if_present(request, body.user_id), body.session_id)
        return service.select_chat_model(body.model, body.session_id or service.current_session_id)

    return guard(run)


@app.post("/api/chat/cancel")
def cancel_chat(body: ChatCancelIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        result = cancel_chat_task(body.task_id, user_id=user_id, reason=body.reason)
        cancelled_durable_jobs: list[str] = []
        for service in list(_workspace_services.values()):
            try:
                store = DurableJobStore(service.manager.workdir / "durable_jobs.db")
                jobs = store.list_jobs(user_id=user_id, statuses=["queued", "running"], job_type="validated_task_plan", limit=100)
                for job in jobs:
                    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
                    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
                    if str(context.get("chat_task_id") or "") == body.task_id:
                        store.cancel_job(str(job.get("job_id") or ""), user_id=user_id, reason=body.reason or "用户取消任务。")
                        cancelled_durable_jobs.append(str(job.get("job_id") or ""))
            except Exception:
                continue
        return {**result, "cancelled_durable_jobs": cancelled_durable_jobs}

    return guard(run)


def _extract_region_from_prompt(prompt: str) -> str:
    semantic = parse_user_semantics(prompt)
    semantic_region = str(semantic.get("region") or semantic.get("region_raw") or "").strip()
    if semantic_region:
        return semantic_region

    text = prompt or ""
    candidates = [
        "成都市", "成都", "四川省", "四川", "闪电河流域", "闪电河",
        "河北省", "中国", "全国"
    ]
    for item in candidates:
        if item in text:
            return "成都市" if item == "成都" else ("四川省" if item == "四川" else item)

    admin_matches: list[str] = []
    for match in re.finditer(
        r"([\u4e00-\u9fff]{2,18}?(?:特别行政区|自治州|自治县|自治旗|地区|盟|省|市|县|区|旗))(?=(?:的|DEM|dem|GDEM|gdem|SRTM|srtm|90|30|数据|高程|[，。；;\s]|$))",
        text,
    ):
        value = match.group(1).strip()
        value = re.sub(r"^(?:帮我|请|给我|为我|下载|获取|准备|预检|裁剪|覆盖|查询|计算|进行|处理|提取|生成|制作)+", "", value)
        if value:
            admin_matches.append(value)
    if admin_matches:
        return admin_matches[-1]

    m = re.search(r"(?:下载|裁剪|覆盖|范围|区域为|研究区为)([^，。；;\s]{2,18})", text)
    if m:
        value = m.group(1).strip()
        value = re.split(r"(?:的)?(?:SRTM|srtm|ASTER|aster|GDEM|gdem|DEM|dem|90m|90M|30m|30M|90米|30米|高程|数据)", value, maxsplit=1)[0]
        value = re.sub(r"(范围|区域|DEM|数据|的)$", "", value)
        return value or "当前研究区"
    return "当前研究区"


def _extract_gscloud_dem_dataset_id_from_prompt(prompt: str) -> str:
    semantic = parse_user_semantics(prompt)
    dataset_id = str(semantic.get("dataset_id") or "").strip()
    if dataset_id:
        return dataset_id

    text = str(prompt or "")
    compact = re.sub(r"\s+", "", text).lower()
    if "srtm" in compact or "90m" in compact or "90米" in compact:
        return "306"
    if "gdemv2" in compact or "gdem2" in compact:
        return "421"
    return "310"




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


















def _sentinel2_processing_level_from_prompt(prompt: str) -> str:
    upper = str(prompt or "").upper().replace(" ", "")
    if "L2A" in upper or "MSIL2A" in upper:
        return "MSIL2A"
    if "L1C" in upper or "MSIL1C" in upper:
        return "MSIL1C"
    return ""
















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
            return {"auto_supported": True, "auto_started": False, "reason": "modev1t_worker_unavailable"}
        commercial_service._update_job(job_id, status="running", progress=5, stage="starting_modev1t_scene_worker")
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
        dataset_id=_extract_gscloud_dem_dataset_id_from_prompt(request_text),
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
        service = _scoped_workspace_service(user_id, body.session_id)
        task_id = str(body.task_id or "").strip()
        if task_id:
            start_chat_task(task_id, user_id=user_id, session_id=body.session_id)
        def finalize(response: dict) -> dict:
            if task_id:
                finish_chat_task(task_id)
            return _attach_result_panel(service, user_id, response)
        service.apply_frontend_context(body.frontend_context)
        if _is_commercial_download_status_prompt(body.prompt):
            if not user_id:
                return finalize(build_chat_response(service, user_prompt=body.prompt, result=_download_requires_login_result(body.prompt)))
            result = _format_commercial_download_status(body.prompt, user_id)
            result = _attach_download_tool_result(result)
            if result.get("presentation_reply"):
                result["reply"] = str(result["presentation_reply"])
            return finalize(
                build_chat_response(
                    service,
                    user_prompt=body.prompt,
                    result=result,
                    meta_keys=(
                        "model",
                        "reason",
                        "normalized_results",
                        "presentation_result",
                        "execution_summary",
                        "result_rendering_path",
                        "presentation_source",
                        "tool_result",
                        "job",
                        "tile_job",
                        "scene_job",
                    ),
                )
            )
        return finalize(
            attach_chat_state(
                service,
                service.ask(
                    body.prompt,
                    visible_prompt=body.prompt,
                    frontend_context=body.frontend_context,
                    extra_assistant_meta={"active_task_id": task_id} if task_id else None,
                ),
            )
        )

    return guard(run)


@app.post("/api/chat/stream")
def stream_chat(body: AskIn, request: Request):
    authorized_user_id = _require_request_user_if_present(request, body.user_id)
    service = _scoped_workspace_service(authorized_user_id, body.session_id)
    session_id = body.session_id or service.current_session_id
    task_id = str(body.task_id or "").strip() or f"chat_{uuid4().hex[:12]}"
    completed = Event()
    outcome: dict[str, Any] = {}
    emitted_deltas: list[str] = []

    def on_delta(delta: str) -> None:
        emitted_deltas.append(delta)
        GLOBAL_REALTIME_EVENT_HUB.publish_model_token(
            user_id=authorized_user_id,
            session_id=session_id,
            task_id=task_id,
            delta=delta,
        )

    def run_chat() -> None:
        start_chat_task(task_id, user_id=authorized_user_id, session_id=session_id)
        event_store = _task_event_store_for_service(service)
        event_store.append(
            user_id=authorized_user_id,
            session_id=session_id,
            task_id=task_id,
            kind="task_status",
            status="planning",
            message="正在理解请求并准备回答或任务计划。",
        )
        try:
            service.apply_frontend_context(body.frontend_context)
            result = attach_chat_state(
                service,
                service.ask(
                    body.prompt,
                    visible_prompt=body.prompt,
                    frontend_context=body.frontend_context,
                    extra_assistant_meta={"active_task_id": task_id},
                    stream_callback=on_delta,
                ),
            )
            result = _attach_result_panel(service, authorized_user_id, result)
            outcome["result"] = result
            presentation = result.get("presentation_result") if isinstance(result.get("presentation_result"), dict) else {}
            task_update = _stream_task_update(result)
            status = str(
                presentation.get("status")
                or task_update.get("status")
                or ("succeeded" if str(result.get("mode") or "") == "answer_only" else "running")
            )
            if status not in {"planning", "awaiting_confirmation", "queued", "running", "waiting_login", "paused", "succeeded", "failed", "cancelled"}:
                status = "running"
            GLOBAL_REALTIME_EVENT_HUB.publish(
                user_id=authorized_user_id,
                session_id=session_id,
                kind="model_complete",
                task_id=task_id,
                status=status,
                message="回答已生成。" if str(result.get("mode") or "") == "answer_only" else str(result.get("reply") or "任务状态已更新。")[:1200],
                delta="" if emitted_deltas else str(result.get("reply") or "")[:2000],
                management_view=task_update.get("management_view") if isinstance(task_update.get("management_view"), dict) else {},
                presentation_result=presentation,
                task_update=task_update,
            )
        except Exception:
            GLOBAL_REALTIME_EVENT_HUB.publish(
                user_id=authorized_user_id,
                session_id=session_id,
                kind="error",
                task_id=task_id,
                status="failed",
                message="请求未能完成，未执行未验证的工具。请稍后重试。",
            )
        finally:
            finish_chat_task(task_id)
            completed.set()

    def event_stream():
        channel = GLOBAL_REALTIME_EVENT_HUB.subscribe(user_id=authorized_user_id, session_id=session_id)
        worker = Thread(target=run_chat, name=f"chat-stream-{task_id}", daemon=True)
        worker.start()
        try:
            while not completed.is_set() or not channel.empty():
                try:
                    event = channel.get(timeout=0.75)
                    if str(event.get("task_id") or "") == task_id:
                        yield _sse_event(event)
                except Empty:
                    yield ": keepalive\n\n"
        finally:
            GLOBAL_REALTIME_EVENT_HUB.unsubscribe(channel)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat/confirm")
def confirm_chat_action(body: ChatConfirmIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        service = _scoped_workspace_service(user_id, body.session_id)
        task_id = str(body.task_id or "").strip()
        if task_id:
            start_chat_task(task_id, user_id=user_id, session_id=body.session_id)

        def finalize(response: dict) -> dict:
            if task_id:
                finish_chat_task(task_id)
            return _attach_result_panel(service, user_id, response)

        service.apply_frontend_context(body.frontend_context)
        token = str(body.confirmation_id or "").strip()
        prompt = f"{str(body.confirmation_prompt or '确认执行').strip()} confirmed_action_id={token}".strip()
        return finalize(
            attach_chat_state(
                service,
                service.ask(
                    prompt,
                    frontend_context=body.frontend_context,
                    record_user_message=False,
                    extra_assistant_meta={
                        "active_task_id": task_id,
                        "confirmed_pending_confirmation_id": token,
                        "confirmation_submission": "structured",
                    }
                    if task_id
                    else {
                        "confirmed_pending_confirmation_id": token,
                        "confirmation_submission": "structured",
                    },
                ),
            )
        )

    return guard(run)


@app.post("/api/files/upload")
async def upload_files(request: Request, user_id: str = Form(default=""), session_id: str = Form(default=""), files: list[UploadFile] = File(...)):
    authorized_user_id = _require_request_user_if_present(request, user_id)
    service = _scoped_workspace_service(authorized_user_id, session_id)

    async def save_streamed_uploads() -> list[tuple[Path, str]]:
        if len(files) > MAX_UPLOAD_FILES:
            raise ValueError(f"单次最多上传 {MAX_UPLOAD_FILES} 个文件。")
        saved: list[tuple[Path, str]] = []
        total_size = 0
        chunk_size = 1024 * 1024
        try:
            for file in files:
                original = file.filename or "uploaded.bin"
                target = service.manager.upload_dir / service.manager._unique_storage_name(original)
                target.parent.mkdir(parents=True, exist_ok=True)
                file_size = 0
                with target.open("wb") as out:
                    while True:
                        chunk = await file.read(chunk_size)
                        if not chunk:
                            break
                        file_size += len(chunk)
                        total_size += len(chunk)
                        if total_size > MAX_UPLOAD_BYTES:
                            raise ValueError(f"单次上传总大小不能超过 {MAX_UPLOAD_BYTES // 1024 // 1024} MB。")
                        out.write(chunk)
                if file_size:
                    saved.append((target, original))
                else:
                    target.unlink(missing_ok=True)
            return saved
        except Exception:
            for path, _ in saved:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                if "target" in locals():
                    target.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    async def run_async():
        payload = await save_streamed_uploads()
        if not payload:
            raise HTTPException(status_code=400, detail="没有读取到有效上传文件。")
        try:
            messages = service.upload_saved_files_batch(payload)
        except Exception:
            for path, _ in payload:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            raise
        result = {"ok": True, "count": len(payload), "messages": messages}
        dashboard_data = _decorate_dashboard(service, user_id=authorized_user_id)
        outcome = build_task_outcome("upload", result, dashboard=dashboard_data)
        return {**result, "dashboard": dashboard_data, "task_outcome": outcome, "outcome_markdown": format_task_outcome_markdown(outcome)}

    try:
        return await run_async()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
def rescan_local_library():
    return guard(lambda: local_library.rescan())


@app.post("/api/local-library/import")
def import_local_library(body: LocalLibraryImportIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        if not body.item_ids:
            raise ValueError("请选择至少一个本地文件库条目。")
        service = _scoped_workspace_service(user_id)
        messages: list[str] = []
        for item in local_library.resolve_paths(body.item_ids):
            messages.append(service.import_local_library_item(item))
        result = {"ok": True, "count": len(messages), "messages": messages}
        dashboard_data = _decorate_dashboard(service, user_id=user_id)
        outcome = build_task_outcome("upload", result, dashboard=dashboard_data)
        return {**result, "dashboard": dashboard_data, "task_outcome": outcome, "outcome_markdown": format_task_outcome_markdown(outcome)}

    return guard(run)


@app.get("/api/admin/capabilities/{resource_type}")
def list_capability_resources(resource_type: Literal["knowledge", "tool_cards", "products", "assets"], request: Request, include_disabled: bool = False):
    def run():
        _require_capability_admin(request)
        return {
            "schema_version": "capability-management-view/v1",
            "registry_version": CAPABILITY_CONFIG_VERSION,
            "resource_type": resource_type,
            "items": _capability_store().list_resources(resource_type, include_disabled=include_disabled),
        }
    return guard(run)


@app.post("/api/admin/capabilities/knowledge")
def upsert_capability_knowledge(body: dict[str, Any], request: Request):
    def run():
        _require_capability_admin(request)
        return {"ok": True, "item": _capability_store().upsert_knowledge(body), "registry_version": CAPABILITY_CONFIG_VERSION}
    return guard(run)


@app.post("/api/admin/capabilities/knowledge/upload")
async def upload_capability_knowledge(
    request: Request,
    file: UploadFile = File(...),
    knowledge_id: str = Form(""),
    title: str = Form(""),
    source: str = Form("admin_upload"),
    language: str = Form("zh-CN"),
    tags: str = Form(""),
    applicable_scope: str = Form(""),
    reliability: str = Form("medium"),
    version: str = Form("v1"),
    status: str = Form("draft"),
):
    try:
        _require_capability_admin(request)
        content, filename = await _extract_capability_document_text(file)
        safe_id = knowledge_id.strip() or re.sub(r"[^A-Za-z0-9_.:-]+", "_", Path(filename).stem).strip("._:-") or "knowledge_doc"
        payload = {
            "knowledge_id": safe_id,
            "title": title.strip() or Path(filename).stem,
            "source": source,
            "language": language,
            "tags": [item.strip() for item in tags.split(",") if item.strip()],
            "applicable_scope": applicable_scope.strip() or "general",
            "reliability": reliability,
            "version": version,
            "status": status,
            "content": content,
            "original_filename": filename,
        }
        return {"ok": True, "item": _capability_store().upsert_knowledge(payload), "registry_version": CAPABILITY_CONFIG_VERSION}
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/admin/capabilities/tool-cards")
def upsert_capability_tool_card(body: dict[str, Any], request: Request):
    def run():
        _require_capability_admin(request)
        return {"ok": True, "item": _capability_store().upsert_tool_card(body), "registry_version": CAPABILITY_CONFIG_VERSION}
    return guard(run)


@app.post("/api/admin/capabilities/products")
def upsert_capability_product(body: dict[str, Any], request: Request):
    def run():
        _require_capability_admin(request)
        return {"ok": True, "item": _capability_store().upsert_product(body), "registry_version": CAPABILITY_CONFIG_VERSION}
    return guard(run)


@app.post("/api/admin/capabilities/assets")
def upsert_capability_asset(body: dict[str, Any], request: Request):
    def run():
        _require_capability_admin(request)
        return {"ok": True, "item": _capability_store().upsert_asset(body), "registry_version": CAPABILITY_CONFIG_VERSION}
    return guard(run)


class CapabilityStatusIn(BaseModel):
    status: str = "pending_review"
    actor: str = ""
    summary: str = ""


@app.post("/api/admin/capabilities/{resource_type}/{item_id}/status")
def update_capability_status(resource_type: Literal["knowledge", "tool_cards", "products", "assets"], item_id: str, body: CapabilityStatusIn, request: Request):
    def run():
        _require_capability_admin(request)
        return {"ok": True, "item": _capability_store().set_status(resource_type, item_id, body.status, actor=body.actor, summary=body.summary), "registry_version": CAPABILITY_CONFIG_VERSION}
    return guard(run)


class CapabilityRollbackIn(BaseModel):
    version: str
    actor: str = ""
    summary: str = ""


@app.post("/api/admin/capabilities/{resource_type}/{item_id}/rollback")
def rollback_capability_resource(resource_type: Literal["knowledge", "tool_cards", "products", "assets"], item_id: str, body: CapabilityRollbackIn, request: Request):
    def run():
        _require_capability_admin(request)
        return {"ok": True, "item": _capability_store().rollback(resource_type, item_id, body.version, actor=body.actor, summary=body.summary), "registry_version": CAPABILITY_CONFIG_VERSION}
    return guard(run)


@app.get("/api/admin/capabilities/audit/events")
def list_capability_audit_events(request: Request, limit: int = 100):
    def run():
        _require_capability_admin(request)
        return {
            "schema_version": "capability-audit-view/v1",
            "events": _capability_store().list_audit_events(limit=limit),
        }
    return guard(run)


@app.get("/api/admin/dataset-availability")
def list_dataset_availability_profiles(request: Request, include_inactive: bool = False):
    def run():
        _require_capability_admin(request)
        return {
            "schema_version": DATASET_AVAILABILITY_SCHEMA_VERSION,
            "items": _dataset_availability_store().list_profiles(include_inactive=include_inactive),
        }
    return guard(run)


@app.post("/api/admin/dataset-availability")
def upsert_dataset_availability_profile(body: dict[str, Any], request: Request):
    def run():
        _require_capability_admin(request)
        return {
            "ok": True,
            "schema_version": DATASET_AVAILABILITY_SCHEMA_VERSION,
            "item": _dataset_availability_store().upsert_profile(body),
        }
    return guard(run)


@app.post("/api/admin/dataset-availability/{product_id}/status")
def update_dataset_availability_status(product_id: str, body: CapabilityStatusIn, request: Request):
    def run():
        _require_capability_admin(request)
        return {
            "ok": True,
            "schema_version": DATASET_AVAILABILITY_SCHEMA_VERSION,
            "item": _dataset_availability_store().set_status(product_id, body.status, actor=body.actor, summary=body.summary),
        }
    return guard(run)


class DatasetAvailabilityScanIn(BaseModel):
    scan_method: str = "catalog_metadata"
    actor: str = ""
    summary: str = ""


@app.post("/api/admin/dataset-availability/{product_id}/scan")
def scan_dataset_availability_profile(product_id: str, body: DatasetAvailabilityScanIn, request: Request):
    def run():
        _require_capability_admin(request)
        draft = scan_dataset_availability(product_id, scan_method=body.scan_method, actor=body.actor, summary=body.summary)
        return {
            "ok": True,
            "schema_version": DATASET_AVAILABILITY_SCHEMA_VERSION,
            "item": _dataset_availability_store().upsert_profile(draft),
        }
    return guard(run)


@app.get("/api/admin/compat-usage/report")
def compatibility_usage_report(request: Request):
    def run():
        _require_capability_admin(request)
        return _compat_usage_store().report(exclude_actor_types={"automated_test"})
    return guard(run)


@app.get("/api/admin/trial-monitoring/report")
def trial_monitoring_report(request: Request):
    def run():
        _require_capability_admin(request)
        return _trial_monitoring_store().report(exclude_actor_types={"automated_test"})
    return guard(run)


class AdminSystemResetIn(BaseModel):
    mode: Literal["keep_accounts", "full_reset"]
    confirm_text: str = ""


@app.post("/api/admin/system-reset")
def admin_system_reset(body: AdminSystemResetIn, request: Request):
    def run():
        global commercial_service
        _require_capability_admin(request)
        _workspace_services.clear()
        result = reset_system_workspace(
            workdir=base_settings.workdir,
            commercial_service=commercial_service,
            mode=body.mode,
            confirm_text=body.confirm_text,
        )
        commercial_service = result.pop("commercial_service")
        base_settings.ensure_dirs()
        return result
    return guard(run)


class AdminStorageCleanupIn(BaseModel):
    candidate_ids: list[str] = []
    confirm_text: str = ""


class AdminPlatformAccountIn(BaseModel):
    source_key: str = "gscloud"
    username: str = ""
    password: str = ""
    label: str = ""
    daily_limit: int = 50
    monthly_limit: int = 1000


class AdminPlatformLoginIn(BaseModel):
    timeout_seconds: int = 300
    headless: bool = False


class AdminPlatformStatusIn(BaseModel):
    status: Literal["active", "disabled"] = "disabled"


def _admin_platform_account_with_health(account: dict[str, Any]) -> dict[str, Any]:
    account_id = str((account or {}).get("account_id") or "")
    private: dict[str, Any] = {}
    try:
        private = commercial_service.get_platform_account_private(account_id)
    except Exception:
        private = {}
    public = commercial_service._platform_public(private) if private else dict(account or {})
    health = inspect_storage_state(str(private.get("storage_state_path") or ""))
    public["login_health"] = health
    public["has_storage_state"] = bool(private.get("storage_state_path"))
    public.pop("storage_state_path", None)
    return public


@app.get("/api/admin/platform-accounts")
def list_admin_platform_accounts(request: Request, source_key: str = Query(default="gscloud"), include_inactive: bool = Query(default=True)):
    def run():
        _require_capability_admin(request)
        accounts = commercial_service.list_platform_accounts(source_key=source_key, include_inactive=include_inactive)
        return {
            "schema_version": "platform-account-management/v1",
            "accounts": [_admin_platform_account_with_health(item) for item in accounts],
        }
    return guard(run)


@app.post("/api/admin/platform-accounts")
def upsert_admin_platform_account(body: AdminPlatformAccountIn, request: Request):
    def run():
        _require_capability_admin(request)
        account = commercial_service.upsert_platform_account(
            source_key=body.source_key,
            username=body.username,
            password=body.password,
            label=body.label,
            daily_limit=body.daily_limit,
            monthly_limit=body.monthly_limit,
        )
        commercial_service.write_audit_event(
            action="admin.platform_account.upsert",
            status="ok",
            resource_type="platform_account",
            resource_id=str(account.get("account_id") or ""),
            detail={"source_key": body.source_key, "label": body.label or body.source_key},
        )
        return {"ok": True, "account": _admin_platform_account_with_health(account)}
    return guard(run)


@app.post("/api/admin/platform-accounts/{account_id}/login")
def start_admin_platform_login(account_id: str, body: AdminPlatformLoginIn, request: Request):
    def run():
        _require_capability_admin(request)
        account = commercial_service.get_platform_account_private(account_id)
        source_key = str(account.get("source_key") or "gscloud").strip().lower()
        if source_key != "gscloud":
            raise ValueError("当前登录窗口只支持 GSCloud 平台账号。")
        state_path = gscloud_platform_state_path(base_settings.workdir, account_id, source_key)
        login_job = start_gscloud_login_process(
            workdir=base_settings.workdir,
            subject_type="platform_account",
            subject_id=account_id,
            state_path=state_path,
            timeout_seconds=body.timeout_seconds,
            headless=body.headless,
        )
        commercial_service.write_audit_event(
            action="admin.platform_account.login_started",
            status="ok",
            resource_type="platform_account",
            resource_id=account_id,
            detail={"source_key": source_key, "login_job_id": login_job.get("login_job_id")},
        )
        safe_job = {
            "login_job_id": login_job.get("login_job_id"),
            "state": login_job.get("state"),
            "message": login_job.get("message"),
            "timeout_seconds": login_job.get("timeout_seconds"),
            "created_at": login_job.get("created_at"),
            "updated_at": login_job.get("updated_at"),
        }
        return {"ok": True, "login_job": safe_job, "account": _admin_platform_account_with_health(commercial_service.get_platform_account_private(account_id))}
    return guard(run)


@app.get("/api/admin/platform-accounts/{account_id}/health")
def check_admin_platform_login_health(account_id: str, request: Request):
    def run():
        _require_capability_admin(request)
        account = commercial_service.get_platform_account_private(account_id)
        health = inspect_storage_state(str(account.get("storage_state_path") or ""))
        commercial_service.write_audit_event(
            action="admin.platform_account.login_health",
            status="ok" if health.get("ok") else "warning",
            resource_type="platform_account",
            resource_id=account_id,
            detail={"source_key": account.get("source_key"), "ok": bool(health.get("ok")), "reason": health.get("reason")},
        )
        return {"ok": True, "account_id": account_id, "login_health": health}
    return guard(run)


@app.post("/api/admin/platform-accounts/{account_id}/status")
def update_admin_platform_account_status(account_id: str, body: AdminPlatformStatusIn, request: Request):
    def run():
        _require_capability_admin(request)
        account = commercial_service.set_platform_account_status(account_id, body.status)
        commercial_service.write_audit_event(
            action="admin.platform_account.status",
            status="ok",
            resource_type="platform_account",
            resource_id=account_id,
            detail={"status": body.status, "source_key": account.get("source_key")},
        )
        return {"ok": True, "account": _admin_platform_account_with_health(account)}
    return guard(run)


@app.get("/api/admin/storage-cleanup/scan")
def admin_storage_cleanup_scan(request: Request):
    def run():
        _require_capability_admin(request)
        return scan_storage_cleanup_candidates(base_settings.workdir)
    return guard(run)


@app.post("/api/admin/storage-cleanup/delete")
def admin_storage_cleanup_delete(body: AdminStorageCleanupIn, request: Request):
    def run():
        _require_capability_admin(request)
        return cleanup_storage_candidates(base_settings.workdir, candidate_ids=body.candidate_ids, confirm_text=body.confirm_text)
    return guard(run)


@app.get("/api/admin/capabilities/knowledge/search/test")
def test_capability_knowledge_search(request: Request, query: str, limit: int = 5, language: str = "", scope: str = ""):
    def run():
        _require_capability_admin(request)
        return {
            "schema_version": "knowledge-retrieval-test/v1",
            "registry_version": CAPABILITY_CONFIG_VERSION,
            "query": query,
            "items": _capability_store().retrieve_knowledge(query, limit=limit, language=language, scope=scope),
        }
    return guard(run)


@app.get("/api/workspace/dashboard")
def dashboard(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        data = _decorate_dashboard(_scoped_workspace_service(authorized_user_id, session_id), user_id=authorized_user_id)
        data["local_library"] = local_library.list_items()
        return data

    return guard(run)


@app.get("/api/workspace/mentions")
def workspace_mentions(request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = _scoped_workspace_service(authorized_user_id, session_id)
        return _build_workspace_mentions(service.manager.list_datasets())

    return guard(run)


@app.post("/api/workspace/export")
def export_workspace(body: ExportIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        service = _scoped_workspace_service(user_id, body.session_id)
        result = service.export_results(mode=body.mode)
        result["download_url"] = artifact_download_url(str(result.get("artifact_id") or ""), user_id=user_id, session_id=service.current_session_id)
        _audit(request, user_id=user_id, action="workspace.export", resource_type="artifact", resource_id=str(result.get("zip_path") or ""), detail={"mode": body.mode, "file_count": result.get("file_count")})
        return result

    return guard(run)


@app.post("/api/workspace/artifacts/delete")
def delete_workspace_artifact(body: ArtifactDeleteIn, request: Request):
    def run():
        user_id = _require_request_user_if_present(request, body.user_id)
        service = _scoped_workspace_service(user_id, body.session_id)
        result = service.manager.delete_result_file(artifact_id=body.artifact_id, path=body.path)
        result["dashboard"] = _decorate_dashboard(service, user_id=user_id)
        _audit(
            request,
            user_id=user_id,
            action="artifact.delete",
            resource_type="artifact",
            resource_id=body.artifact_id or body.path,
            detail={k: result.get(k) for k in ("path", "deleted_files", "deleted_artifacts", "deleted_datasets")},
        )
        return result

    return guard(run)


def _public_artifact_or_error(service: GISWorkspaceService, artifact_id: str, user_id: str = "", session_id: str = "") -> dict:
    artifact = service.manager.assert_artifact_access(user_id, session_id or service.current_session_id, artifact_id)
    return public_artifact_payload(artifact, workdir=service.manager.workdir, user_id=user_id, session_id=session_id)


@app.get("/api/artifacts/{artifact_id}")
def artifact_metadata(artifact_id: str, request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = _scoped_workspace_service(authorized_user_id, session_id)
        return _public_artifact_or_error(service, artifact_id, user_id=authorized_user_id, session_id=session_id)

    return guard(run)


@app.delete("/api/artifacts/{artifact_id}")
def delete_artifact(artifact_id: str, request: Request, user_id: str = Query(default=""), session_id: str = Query(default=""), delete_file: bool = Query(default=True)):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = _scoped_workspace_service(authorized_user_id, session_id)
        service.manager.assert_artifact_access(authorized_user_id, session_id or service.current_session_id, artifact_id)
        result = service.manager.delete_result_file(artifact_id=artifact_id if delete_file else "", path="")
        status = "deleted" if result.get("deleted_files") or result.get("deleted_artifacts") or result.get("deleted_datasets") else "not_found"
        _audit(
            request,
            user_id=authorized_user_id,
            action="artifact.delete",
            resource_type="artifact",
            resource_id=artifact_id,
            detail={k: result.get(k) for k in ("deleted_files", "deleted_artifacts", "deleted_datasets")},
        )
        return {
            "ok": status == "deleted",
            "artifact_id": artifact_id,
            "status": status,
            "file_deleted": bool(result.get("deleted_files")),
            "deleted_files": result.get("deleted_files", []),
            "deleted_artifacts": result.get("deleted_artifacts", []),
            "deleted_datasets": result.get("deleted_datasets", []),
        }

    return guard(run)


@app.get("/api/artifacts/{artifact_id}/download")
def artifact_download(artifact_id: str, request: Request, user_id: str = Query(default=""), session_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user_if_present(request, user_id)
        service = _scoped_workspace_service(authorized_user_id, session_id)
        artifact = service.manager.assert_artifact_access(authorized_user_id, session_id or service.current_session_id, artifact_id)
        public = public_artifact_payload(artifact, workdir=service.manager.workdir, user_id=authorized_user_id, session_id=session_id)
        target = assert_artifact_path_allowed(service.manager.workdir, str(artifact.get("path") or ""))
        if target.suffix.lower() == ".shp":
            target = shapefile_zip_path(service.manager.workdir, target, artifact_id)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError("文件已清理、无访问权限或下载链接已失效。")
        if target.stat().st_size <= 0:
            raise FileNotFoundError("文件已清理、无访问权限或下载链接已失效。")
        _audit(request, user_id=authorized_user_id, action="artifact.download", resource_type="artifact", resource_id=artifact_id)
        return FileResponse(
            str(target),
            media_type=str(public.get("mime_type") or "application/octet-stream"),
            filename=safe_download_filename(str(public.get("filename") or target.name)),
            headers={"Content-Disposition": content_disposition_attachment(str(public.get("filename") or target.name))},
        )

    return guard(run)


@app.get("/api/files/artifact")
def artifact(request: Request, user_id: str = Query(default=""), session_id: str = Query(default=""), path: str = Query(...)):
    raise HTTPException(
        status_code=410,
        detail="Deprecated artifact path downloads are disabled. Use /api/artifacts/{artifact_id}/download.",
    )


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


@app.post("/api/downloads/submit")
def submit_download(body: DownloadIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        if body.session_id:
            _scoped_workspace_service(user_id, body.session_id)
        payload = body.model_dump()
        payload["user_id"] = user_id
        job = commercial_service.submit_job(**payload)
        auto = _maybe_start_gscloud_auto_download(job, region=body.region)
        _audit(request, user_id=user_id, action="download.submit", resource_type="download_job", resource_id=job["job_id"], detail={"source_key": job.get("source_key"), "resource_type": job.get("resource_type"), "auto_started": auto.get("auto_started")})
        payload = _attach_download_tool_result({"job": commercial_service.get_job(job["job_id"]), **auto})
        if body.include_raw:
            payload["deprecated_raw_job_api"] = True
            _compat_usage_store().record("deprecated_raw_job_api_used", source="POST /api/downloads/submit", caller=str(request.headers.get("user-agent") or ""), request_id=str(job.get("job_id") or ""), actor_type=_compat_actor_type(request))
            _compat_usage_store().record("include_raw", source="POST /api/downloads/submit", caller=str(request.headers.get("user-agent") or ""), request_id=str(job.get("job_id") or ""), actor_type=_compat_actor_type(request))
            return payload
        return {
            "ok": payload.get("ok", True),
            "auto_supported": payload.get("auto_supported"),
            "auto_started": payload.get("auto_started"),
            "reason": payload.get("reason"),
            "management_view": payload.get("management_view"),
            "presentation_result": payload.get("presentation_result"),
            "execution_summary": payload.get("execution_summary"),
            "artifact_refs": (payload.get("management_view") or {}).get("artifact_refs") if isinstance(payload.get("management_view"), dict) else [],
            "available_actions": (payload.get("management_view") or {}).get("available_actions") if isinstance(payload.get("management_view"), dict) else [],
            "deprecated_raw_job_api": False,
        }

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
def list_jobs(request: Request, user_id: str = "", session_id: str = "", include_raw: bool = Query(default=False)):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        if session_id:
            _scoped_workspace_service(authorized_user_id, session_id)
        jobs = commercial_service.list_jobs(user_id=authorized_user_id, session_id=session_id)
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
                    url = _relative_shared_download_url(str(target or ""), user_id=authorized_user_id, job_id=str(job.get("job_id") or ""), session_id=str(job.get("session_id") or ""))
                    if url:
                        job["download_url"] = url
                        break
        for job in jobs:
            if isinstance(job, dict):
                job["tool_result"] = _download_tool_result_for_job(job, user_id=authorized_user_id)
                job["management_view"] = download_job_to_management_view(job, tool_result=job["tool_result"])
        management_views = [job["management_view"] for job in jobs if isinstance(job, dict) and isinstance(job.get("management_view"), dict)]
        payload = {
            "management_views": management_views,
            "artifact_refs": [
                artifact
                for view in management_views
                for artifact in (view.get("artifact_refs") if isinstance(view.get("artifact_refs"), list) else [])
                if isinstance(artifact, dict)
            ],
            "available_actions": sorted({action for view in management_views for action in (view.get("available_actions") if isinstance(view.get("available_actions"), list) else [])}),
            "deprecated_raw_job_api": bool(include_raw),
        }
        if include_raw:
            _compat_usage_store().record("deprecated_raw_job_api_used", source="GET /api/downloads/jobs", caller=str(request.headers.get("user-agent") or ""), request_id=authorized_user_id, actor_type=_compat_actor_type(request))
            _compat_usage_store().record("include_raw", source="GET /api/downloads/jobs", caller=str(request.headers.get("user-agent") or ""), request_id=authorized_user_id, actor_type=_compat_actor_type(request))
            payload["jobs"] = jobs
        return payload
    return guard(run)


@app.get("/api/downloads/jobs/log")
def download_job_log(request: Request, user_id: str = Query(...), job_id: str = Query(...), session_id: str = Query(default=""), include_raw: bool = Query(default=False)):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        if session_id:
            _scoped_workspace_service(authorized_user_id, session_id)
        job = require_resource_owner(commercial_service.get_job(job_id), user_id=authorized_user_id, resource_name="download job")
        _assert_download_job_session(job, session_id)
        tile_jobs = []
        scene_jobs = []
        if list_gscloud_tile_jobs is not None:
            tile_jobs = [item for item in list_gscloud_tile_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id]
        if list_gscloud_scene_jobs is not None:
            scene_jobs = [item for item in list_gscloud_scene_jobs(commercial_service.workdir, limit=100) if item.get("job_id") == job_id]
        payload = _attach_download_tool_result({
            "job": job,
            "scene_jobs": scene_jobs,
            "tile_jobs": tile_jobs,
            "audit_events": commercial_service.list_audit_events(user_id=authorized_user_id, limit=20),
        })
        if not include_raw:
            return {
                "management_view": payload.get("management_view"),
                "diagnostic_event_views": payload.get("diagnostic_event_views"),
                "artifact_refs": (payload.get("management_view") or {}).get("artifact_refs") if isinstance(payload.get("management_view"), dict) else [],
                "available_actions": (payload.get("management_view") or {}).get("available_actions") if isinstance(payload.get("management_view"), dict) else [],
                "deprecated_raw_job_api": False,
            }
        payload["deprecated_raw_job_api"] = True
        _compat_usage_store().record("deprecated_raw_job_api_used", source="GET /api/downloads/jobs/log", caller=str(request.headers.get("user-agent") or ""), request_id=job_id, actor_type=_compat_actor_type(request))
        _compat_usage_store().record("include_raw", source="GET /api/downloads/jobs/log", caller=str(request.headers.get("user-agent") or ""), request_id=job_id, actor_type=_compat_actor_type(request))
        return payload

    return guard(run)


@app.get("/api/downloads/jobs/log-download")
def download_job_log_file(request: Request, user_id: str = Query(...), job_id: str = Query(...), session_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        if session_id:
            _scoped_workspace_service(authorized_user_id, session_id)
        job = require_resource_owner(commercial_service.get_job(job_id), user_id=authorized_user_id, resource_name="download job")
        _assert_download_job_session(job, session_id)
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
            headers={"Content-Disposition": content_disposition_attachment(f"{job_id}_log.txt")},
        )

    return guard(run)


@app.post("/api/downloads/jobs/delete")
def delete_download_job(body: DownloadDeleteIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        if body.session_id:
            _scoped_workspace_service(user_id, body.session_id)
            job = require_resource_owner(commercial_service.get_job(body.job_id), user_id=user_id, resource_name="download job")
            _assert_download_job_session(job, body.session_id)
        result = commercial_service.delete_job(body.job_id, user_id=user_id)
        jobs = commercial_service.list_jobs(user_id=user_id, session_id=body.session_id)
        management_views = [
            download_job_to_management_view(job, tool_result=_download_tool_result_for_job(job))
            for job in jobs
            if isinstance(job, dict)
        ]
        _audit(request, user_id=user_id, action="download.delete", resource_type="download_job", resource_id=body.job_id)
        return {
            **result,
            "management_views": management_views,
            "available_actions": sorted({action for view in management_views for action in (view.get("available_actions") if isinstance(view.get("available_actions"), list) else [])}),
            "deprecated_raw_job_api": False,
        }

    return guard(run)


@app.post("/api/downloads/jobs/cancel")
def cancel_download_job(body: DownloadActionIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        if body.session_id:
            _scoped_workspace_service(user_id, body.session_id)
            job = require_resource_owner(commercial_service.get_job(body.job_id), user_id=user_id, resource_name="download job")
            _assert_download_job_session(job, body.session_id)
        result = commercial_service.cancel_job(body.job_id, user_id=user_id, reason=body.reason)
        jobs = commercial_service.list_jobs(user_id=user_id, session_id=body.session_id)
        _audit(request, user_id=user_id, action="download.cancel", resource_type="download_job", resource_id=body.job_id)
        payload = _attach_download_tool_result({**result, "job": result, "jobs": jobs})
        return {
            "ok": payload.get("ok"),
            "management_view": payload.get("management_view"),
            "management_views": payload.get("management_views"),
            "available_actions": sorted({action for view in (payload.get("management_views") if isinstance(payload.get("management_views"), list) else []) for action in (view.get("available_actions") if isinstance(view.get("available_actions"), list) else [])}),
            "deprecated_raw_job_api": False,
        }

    return guard(run)


@app.post("/api/downloads/jobs/retry")
def retry_download_job(body: DownloadActionIn, request: Request):
    def run():
        user_id = _require_request_user(request, body.user_id)
        if body.session_id:
            _scoped_workspace_service(user_id, body.session_id)
            job = require_resource_owner(commercial_service.get_job(body.job_id), user_id=user_id, resource_name="download job")
            _assert_download_job_session(job, body.session_id)
        retry = commercial_service.retry_job(body.job_id, user_id=user_id, session_id=body.session_id)
        auto = _maybe_start_gscloud_auto_download(retry, region=str(retry.get("region") or ""))
        jobs = commercial_service.list_jobs(user_id=user_id, session_id=body.session_id)
        _audit(request, user_id=user_id, action="download.retry", resource_type="download_job", resource_id=retry["job_id"], detail={"retried_from": body.job_id, "auto_started": auto.get("auto_started")})
        payload = _attach_download_tool_result({"job": commercial_service.get_job(retry["job_id"]), **auto, "jobs": jobs})
        return {
            "ok": payload.get("ok", True),
            "auto_supported": payload.get("auto_supported"),
            "auto_started": payload.get("auto_started"),
            "reason": payload.get("reason"),
            "management_view": payload.get("management_view"),
            "management_views": payload.get("management_views"),
            "available_actions": sorted({action for view in (payload.get("management_views") if isinstance(payload.get("management_views"), list) else []) for action in (view.get("available_actions") if isinstance(view.get("available_actions"), list) else [])}),
            "deprecated_raw_job_api": False,
        }

    return guard(run)


@app.get("/api/downloads/artifact")
def download_job_artifact(request: Request, user_id: str = Query(...), job_id: str = Query(...), path: str = Query(...), session_id: str = Query(default="")):
    def run():
        authorized_user_id = _require_request_user(request, user_id)
        if session_id:
            _scoped_workspace_service(authorized_user_id, session_id)
        job = require_resource_owner(commercial_service.get_job(job_id), user_id=authorized_user_id, resource_name="download job")
        _assert_download_job_session(job, session_id)
        target = resolve_child_path(base_settings.workdir, path)
        target = assert_artifact_path_allowed(base_settings.workdir, target)
        allowed = {str(job.get("zip_path") or ""), str(job.get("output_path") or "")}
        if str(target.resolve()) not in {str(Path(item).resolve()) for item in allowed if item}:
            _audit(request, user_id=authorized_user_id, action="download.artifact", status="denied", resource_type="download_job", resource_id=job_id, detail={"path": path})
            raise PermissionError("下载路径不属于该任务。")
        _audit(request, user_id=authorized_user_id, action="download.artifact", resource_type="download_job", resource_id=job_id, detail={"path": path})
        return FileResponse(str(target), filename=target.name, headers={"Content-Disposition": content_disposition_attachment(target.name)})
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
            service = _scoped_workspace_service(user_id, body.session_id)
            return service.ask(SHANDIAN_WORKFLOW_PROMPT)
        return {"prompt": SHANDIAN_WORKFLOW_PROMPT}

    return guard(run)
