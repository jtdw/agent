from __future__ import annotations

import json
import os
import re
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from api.routes.admin_capabilities import create_capabilities_router
from api.routes.admin_operations import create_admin_operations_router
from api.routes.admin_platform import create_admin_platform_router
from api.routes.auth import create_auth_router
from api.routes.chat_actions import create_chat_actions_router
from api.routes.chat_state import create_chat_state_router
from api.routes.data_sources import create_data_sources_router
from api.routes.downloads import create_downloads_router
from api.routes.downloads_main import create_downloads_main_router
from api.routes.local_library import create_local_library_router
from api.routes.map import create_map_router
from api.routes.payments import create_payments_router
from api.routes.system import create_system_router
from api.routes.workflows import create_workflows_router
from api.routes.workspace import create_workspace_router
from api.schemas.chat import AskIn
from core.config import Settings, load_settings
from core.service import GISWorkspaceService
from core.agent_runtime import agent_runtime_rag_readiness_report
from core.agent_runtime.exposure import agent_runtime_exposure_report
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
from core.artifacts import artifact_download_url, assert_artifact_path_allowed, content_disposition_attachment, public_artifact_payload, safe_download_filename, shapefile_zip_path
from core.chat_response import attach_chat_state, build_chat_response
from core.chat_tasks import cancel_chat_task, finish_chat_task, start_chat_task
from core.download_request_executor import _attach_registered_download_artifacts
from core.durable_jobs import DurableJobStore
from core.realtime_events import GLOBAL_REALTIME_EVENT_HUB, TaskEventStore
from core.response_quality import validate_response_before_send
from core.management_views import download_job_to_management_view
from core.task_outcome_advisor import build_task_outcome, format_task_outcome_markdown
from core.tool_contracts import download_job_to_tool_result
from core.api_utils import api_guard, resolve_child_path
from core.local_library import LocalFileLibrary
from core.map_layers import read_vector_for_map
from core.capability_config import CapabilityConfigStore
from core.dataset_availability import DatasetAvailabilityStore
from core.dataset_availability_scanner import scan_dataset_availability
from core.system_reset import reset_system_workspace
from core.storage_cleanup import cleanup_storage_candidates, scan_storage_cleanup_candidates
from core.compat_usage import CompatibilityUsageStore
from core.trial_monitoring import TrialMonitoringStore
from core.semantic_parser import parse_user_semantics
from core.ismn_adapter import find_local_ismn_archives, ismn_archive_to_station_collection
from core.domestic_sources.gscloud_download_verifier import verify_gscloud_scene_download
from core.domestic_sources.gscloud_products import GSCLOUD_PRODUCTS, LANDSAT8_OLI_TIRS, MOD021KM_1KM_SURFACE_REFLECTANCE, MODEV1F_CHINA_250M_EVI_5DAY, MODL1D_CHINA_1KM_LST_DAILY, MODND1D_CHINA_500M_NDVI_DAILY, SENTINEL2_MSI
from core.domestic_sources.gscloud_reliability import inspect_storage_state, resolve_download_region
from core.domestic_sources.gscloud_adapter import gscloud_platform_state_path
from core.commercial.login_jobs import start_gscloud_login_process
from core.ops_config import require_valid_production_config
from services.data_sources.gscloud_accounts import GSCloudAccountService
from services.downloads.gscloud_auto_start import (
    GSCloudAutoStartService,
    extract_cloud_max_from_prompt as _service_extract_cloud_max_from_prompt,
    extract_gscloud_dem_dataset_id_from_prompt as _service_extract_gscloud_dem_dataset_id_from_prompt,
    extract_max_scenes_from_prompt as _service_extract_max_scenes_from_prompt,
    extract_year_from_prompt as _service_extract_year_from_prompt,
    sentinel2_processing_level_from_prompt as _service_sentinel2_processing_level_from_prompt,
)
from services.downloads.preflight import DownloadPreflightService
from services.downloads.presentation import (
    DownloadPresentationService,
    assert_download_job_session as _assert_download_job_session,
    format_download_job_log_text,
)
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


def _gscloud_auto_start_service() -> GSCloudAutoStartService:
    return GSCloudAutoStartService(
        commercial_service=lambda: commercial_service,
        workdir=lambda: base_settings.workdir,
        products={
            "modl1d": MODL1D_CHINA_1KM_LST_DAILY,
            "modnd1d": MODND1D_CHINA_500M_NDVI_DAILY,
            "modev1f": MODEV1F_CHINA_250M_EVI_5DAY,
            "mod021km": MOD021KM_1KM_SURFACE_REFLECTANCE,
            "sentinel2": SENTINEL2_MSI,
            "landsat8": LANDSAT8_OLI_TIRS,
        },
        tile_worker=start_gscloud_tile_process,
        modl1d_worker=start_gscloud_modl1d_process,
        modnd1d_worker=start_gscloud_modnd1d_process,
        modev1f_worker=start_gscloud_modev1f_process,
        mod021km_worker=start_gscloud_mod021km_process,
        sentinel2_worker=start_gscloud_sentinel2_process,
        landsat8_worker=start_gscloud_landsat8_process,
    )


def _download_resume_service() -> DownloadResumeService:
    return DownloadResumeService(
        commercial_service,
        _gscloud_account_service(),
        _gscloud_auto_start_service().maybe_start,
    )


def _download_presentation_service() -> DownloadPresentationService:
    return DownloadPresentationService(
        manager_for_job=_manager_for_download_job,
        list_scene_jobs=lambda limit=100: list_gscloud_scene_jobs(commercial_service.workdir, limit=limit) if list_gscloud_scene_jobs is not None else [],
        list_tile_jobs=lambda limit=100: list_gscloud_tile_jobs(commercial_service.workdir, limit=limit) if list_gscloud_tile_jobs is not None else [],
        attach_registered_download_artifacts=_attach_registered_download_artifacts,
    )


def _download_preflight_service() -> DownloadPreflightService:
    return DownloadPreflightService(
        commercial_service=lambda: commercial_service,
        products=GSCLOUD_PRODUCTS,
        resolve_download_region=resolve_download_region,
        inspect_storage_state=inspect_storage_state,
        verify_gscloud_scene_download=verify_gscloud_scene_download,
        workdir=lambda: base_settings.workdir,
    )


app.include_router(
    create_system_router(
        local_library_root=lambda: local_library.root,
        guard=guard,
    )
)
app.include_router(
    create_auth_router(
        commercial_service=lambda: commercial_service,
        set_session_cookies=_set_session_cookies,
        clear_session_cookies=_clear_session_cookies,
        request_session=_request_session,
        optional_authenticated_session=optional_authenticated_session,
        audit=_audit,
        guard=guard,
    )
)
app.include_router(
    create_workspace_router(
        scoped_workspace_service=_scoped_workspace_service,
        require_request_user_if_present=_require_request_user_if_present,
        decorate_dashboard=lambda service, user_id="": _decorate_dashboard(service, user_id=user_id),
        build_workspace_mentions=lambda datasets: _build_workspace_mentions(datasets),
        local_library_items=lambda: local_library.list_items(),
        artifact_download_url=artifact_download_url,
        public_artifact_or_error=lambda service, artifact_id, user_id="", session_id="": _public_artifact_or_error(service, artifact_id, user_id=user_id, session_id=session_id),
        audit=_audit,
        guard=guard,
        max_upload_files=lambda: MAX_UPLOAD_FILES,
        max_upload_bytes=lambda: MAX_UPLOAD_BYTES,
    )
)
app.include_router(
    create_map_router(
        scoped_workspace_service=_scoped_workspace_service,
        require_request_user_if_present=_require_request_user_if_present,
        load_station_collection=lambda user_id="": _load_station_collection(user_id),
        guard=guard,
    )
)
app.include_router(
    create_local_library_router(
        local_library=lambda: local_library,
        scoped_workspace_service=lambda user_id, session_id="": _scoped_workspace_service(user_id, session_id),
        require_request_user_if_present=_require_request_user_if_present,
        decorate_dashboard=lambda service, user_id="": _decorate_dashboard(service, user_id=user_id),
        guard=guard,
    )
)
app.include_router(
    create_capabilities_router(
        capability_store=_capability_store,
        require_capability_admin=_require_capability_admin,
        extract_capability_document_text=_extract_capability_document_text,
        guard=guard,
    )
)
app.include_router(
    create_admin_operations_router(
        dataset_availability_store=_dataset_availability_store,
        compatibility_usage_store=_compat_usage_store,
        trial_monitoring_store=_trial_monitoring_store,
        require_capability_admin=_require_capability_admin,
        scan_dataset_availability=scan_dataset_availability,
        reset_system_workspace=reset_system_workspace,
        get_commercial_service=lambda: commercial_service,
        set_commercial_service=lambda value: globals().__setitem__("commercial_service", value),
        clear_workspace_services=lambda: _workspace_services.clear(),
        ensure_base_dirs=lambda: base_settings.ensure_dirs(),
        scan_storage_cleanup_candidates=scan_storage_cleanup_candidates,
        cleanup_storage_candidates=cleanup_storage_candidates,
        agent_runtime_diagnostics=lambda: workspace_for(None).agent_runtime_diagnostics(),
        agent_runtime_rag_readiness=agent_runtime_rag_readiness_report,
        agent_runtime_exposure=agent_runtime_exposure_report,
        workdir=lambda: base_settings.workdir,
        guard=guard,
    )
)
app.include_router(
    create_admin_platform_router(
        commercial_service=lambda: commercial_service,
        require_capability_admin=_require_capability_admin,
        inspect_storage_state=inspect_storage_state,
        gscloud_platform_state_path=gscloud_platform_state_path,
        start_gscloud_login_process=lambda **kwargs: start_gscloud_login_process(**kwargs),
        workdir=lambda: base_settings.workdir,
        guard=guard,
    )
)
app.include_router(
    create_chat_state_router(
        scoped_workspace_service=lambda user_id, session_id="": _scoped_workspace_service(user_id, session_id),
        require_request_user_if_present=lambda request, user_id: _require_request_user_if_present(request, user_id),
        decorate_response_artifacts=lambda service, user_id, response: _decorate_response_artifacts(service, user_id, response),
        public_task_events=lambda service, **kwargs: _public_task_events(service, **kwargs),
        sse_event=lambda event: _sse_event(event),
        realtime_event_hub=GLOBAL_REALTIME_EVENT_HUB,
        cancel_chat_task=cancel_chat_task,
        workspace_services=lambda: list(_workspace_services.values()),
        durable_job_store_factory=lambda path: DurableJobStore(path),
        cancel_session_jobs=commercial_service.cancel_session_jobs,
        hard_delete_session_jobs=commercial_service.hard_delete_session_jobs,
        compat_usage_store=_compat_usage_store,
        compat_actor_type=_compat_actor_type,
        guard=guard,
    )
)
app.include_router(
    create_chat_actions_router(
        scoped_workspace_service=lambda user_id, session_id="": _scoped_workspace_service(user_id, session_id),
        require_request_user_if_present=lambda request, user_id: _require_request_user_if_present(request, user_id),
        attach_result_panel=lambda service, user_id, response: _attach_result_panel(service, user_id, response),
        attach_chat_state=lambda service, response: attach_chat_state(service, response),
        build_chat_response=lambda *args, **kwargs: build_chat_response(*args, **kwargs),
        start_chat_task=start_chat_task,
        finish_chat_task=finish_chat_task,
        is_commercial_download_status_prompt=lambda prompt: _is_commercial_download_status_prompt(prompt),
        download_requires_login_result=lambda prompt: _download_requires_login_result(prompt),
        format_commercial_download_status=lambda prompt, user_id: _format_commercial_download_status(prompt, user_id),
        attach_download_tool_result=lambda payload: _download_presentation_service().attach_download_tool_result(payload),
        realtime_event_hub=GLOBAL_REALTIME_EVENT_HUB,
        task_event_store_for_service=lambda service: _task_event_store_for_service(service),
        stream_task_update=lambda response: _stream_task_update(response),
        sse_event=lambda event: _sse_event(event),
        task_id_factory=lambda: f"chat_{uuid4().hex[:12]}",
        guard=guard,
    )
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
app.include_router(
    create_downloads_main_router(
        commercial_service=lambda: commercial_service,
        require_request_user=lambda request, user_id: _require_request_user(request, user_id),
        scoped_workspace_service=lambda user_id, session_id="": _scoped_workspace_service(user_id, session_id),
        maybe_start_gscloud_auto_download=lambda job, region="": _gscloud_auto_start_service().maybe_start(job, region=region),
        attach_download_tool_result=lambda payload: _download_presentation_service().attach_download_tool_result(payload),
        download_tool_result_for_job=lambda job, user_id="": _download_presentation_service().download_tool_result_for_job(job, user_id=user_id),
        download_job_to_management_view=lambda job, tool_result=None: download_job_to_management_view(job, tool_result=tool_result),
        require_resource_owner=lambda resource, user_id="", resource_name="": require_resource_owner(resource, user_id=user_id, resource_name=resource_name),
        assert_download_job_session=lambda job, session_id="": _assert_download_job_session(job, session_id),
        relative_shared_download_url=lambda file_path, **kwargs: _relative_shared_download_url(file_path, **kwargs),
        list_gscloud_scene_jobs=lambda workdir, limit=100: list_gscloud_scene_jobs(workdir, limit=limit) if list_gscloud_scene_jobs is not None else [],
        list_gscloud_tile_jobs=lambda workdir, limit=100: list_gscloud_tile_jobs(workdir, limit=limit) if list_gscloud_tile_jobs is not None else [],
        format_download_job_log_text=format_download_job_log_text,
        content_disposition_attachment=content_disposition_attachment,
        resolve_child_path=resolve_child_path,
        assert_artifact_path_allowed=assert_artifact_path_allowed,
        preflight_service=_download_preflight_service,
        workdir=lambda: base_settings.workdir,
        audit=_audit,
        compat_usage_store=_compat_usage_store,
        compat_actor_type=_compat_actor_type,
        guard=guard,
    )
)
app.include_router(
    create_payments_router(
        commercial_service=lambda: commercial_service,
        require_payment_user=lambda request, user_id: _require_admin_or_mock_payment_user(request, user_id),
        plan_presets=PLAN_PRESETS,
        audit=_audit,
        guard=guard,
    )
)
app.include_router(
    create_workflows_router(
        require_request_user_if_present=lambda request, user_id: _require_request_user_if_present(request, user_id),
        scoped_workspace_service=lambda user_id, session_id="": _scoped_workspace_service(user_id, session_id),
        workflow_prompt=lambda: SHANDIAN_WORKFLOW_PROMPT,
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
    archives = find_local_ismn_archives(*_station_search_roots(user_id))
    if not archives:
        return {
            "count": 0,
            "stations": [],
            "center": [116.18, 41.78],
            "bounds": [115.5, 41.5, 116.5, 42.5],
            "source": "",
            "source_name": "",
            "message": "未找到本地 ISMN 土壤水分站点压缩包。请将官方 ISMN zip 放入 local_library/data/ismn，或上传到当前工作区。",
        }
    return ismn_archive_to_station_collection(archives[0], preferred_depth="0.050000", year="2019")


def _read_vector_for_map(path: Path):
    return read_vector_for_map(path)


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


def _manager_for_download_job(user_id: str, job: dict) -> Any | None:
    session_id = str((job or {}).get("session_id") or "").strip()
    if not user_id or not session_id:
        return None
    try:
        return _scoped_workspace_service(user_id, session_id).manager
    except Exception:
        return None


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
    return _service_extract_gscloud_dem_dataset_id_from_prompt(prompt)




def _extract_year_from_prompt(prompt: str) -> str:
    return _service_extract_year_from_prompt(prompt)


def _extract_cloud_max_from_prompt(prompt: str, default: float = 30.0) -> float:
    return _service_extract_cloud_max_from_prompt(prompt, default=default)


def _extract_max_scenes_from_prompt(prompt: str, default: int = 1) -> int:
    return _service_extract_max_scenes_from_prompt(prompt, default=default)


















def _sentinel2_processing_level_from_prompt(prompt: str) -> str:
    return _service_sentinel2_processing_level_from_prompt(prompt)
















def _maybe_start_gscloud_auto_download(job: dict, region: str = "") -> dict:
    return _gscloud_auto_start_service().maybe_start(job, region=region)


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


def _download_requires_login_result(prompt: str) -> dict:
    return _api_download_requires_login_result(prompt)














def _public_artifact_or_error(service: GISWorkspaceService, artifact_id: str, user_id: str = "", session_id: str = "") -> dict:
    artifact = service.manager.assert_artifact_access(user_id, session_id or service.current_session_id, artifact_id)
    return public_artifact_payload(artifact, workdir=service.manager.workdir, user_id=user_id, session_id=session_id)


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


